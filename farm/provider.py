"""Authoritative spend, read from the provider rather than inferred from a transcript.

`farm/cost.py` computes cost from token counts against a pinned price table,
deliberately distrusting the harness's own reported figure (which is `0.0` on any
pricing failure -- see `docs/HARNESS_NOTES.md` §1).  Campaign `c01` showed that
this is necessary but **not sufficient**: the token counts themselves are
incomplete.

Measured on the first billed episode of `c01`
(`pallets_click_task/task2800 f5+f6`):

| source | episode cost |
|---|---:|
| OpenRouter, the actual biller | **$1.2228** |
| the harness's own LiteLLM figure | $0.9043 |
| our ledger, from trajectory token counts | **$0.2301** |

The trajectory recorded 60 usage-bearing requests where the harness counted 200
agent steps, so our token sum covered roughly a fifth of what was really billed.
Every one of the three numbers disagrees with the other two, and the only one
that can settle an invoice is the provider's.

A cap enforced against a figure that is 5x low is not a cap.  So the ledger is
settled from the provider's own cumulative usage: read it before an episode, read
it after, and bill the difference.  The token-derived figure is still computed and
retained, because the *gap between them* is itself a finding worth keeping.

Limits, stated rather than hidden:

* This measures spend for the whole **key**, not for one episode.  If anything
  else uses the same key concurrently, the delta absorbs it.  Campaign runs are
  serial and the key is dedicated, so the attribution holds here; it would not
  under concurrency.
* OpenRouter's usage figure settles asynchronously, so a read taken immediately
  after an agent stops can still be climbing.  `settled_usage` polls until the
  value stops moving before returning it.
* If the endpoint cannot be reached, this returns `None` and the caller falls
  back to the token-derived figure -- degraded, and recorded as degraded, rather
  than silently reporting a cost of zero.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"


@dataclass
class Reconciliation:
    """One episode's spend, from both sources, with the gap made explicit."""

    provider_usd: float | None
    tokens_usd: float
    source: str
    note: str = ""

    @property
    def billed_usd(self) -> float:
        """What the ledger should commit: the provider's number when we have it."""
        return self.tokens_usd if self.provider_usd is None else self.provider_usd

    @property
    def ratio(self) -> float | None:
        if self.provider_usd is None or self.tokens_usd <= 0:
            return None
        return round(self.provider_usd / self.tokens_usd, 3)

    def to_dict(self) -> dict:
        return {"billed_usd": round(self.billed_usd, 6),
                "provider_usd": None if self.provider_usd is None else round(self.provider_usd, 6),
                "tokens_usd": round(self.tokens_usd, 6),
                "provider_over_tokens": self.ratio,
                "source": self.source,
                "note": self.note}


def account_usage(api_key: str | None = None, *, timeout: float = 30.0) -> float | None:
    """Cumulative USD this key has spent, per OpenRouter.  None if unreachable.

    The key travels only in the Authorization header and is never logged.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    req = urllib.request.Request(
        KEY_URL, headers={"Authorization": f"Bearer {key}",
                          "User-Agent": "conetic-farm/cost-reconciliation"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode()).get("data", {})
    except (urllib.error.URLError, OSError, ValueError):
        return None
    usage = data.get("usage")
    try:
        return float(usage)
    except (TypeError, ValueError):
        return None


def settled_usage(api_key: str | None = None, *, tries: int = 6, interval: float = 5.0,
                  sleep: Callable[[float], None] = time.sleep) -> float | None:
    """Read cumulative usage, waiting for it to stop climbing.

    OpenRouter bills asynchronously: a read taken the moment an agent stops can
    still be rising as generations settle.  Two consecutive equal reads are taken
    as settled.  Returns the last value read even if it never stabilises, because
    a late-but-close number beats no number at all -- the caller records which.
    """
    last = account_usage(api_key)
    if last is None:
        return None
    for _ in range(max(0, tries - 1)):
        sleep(interval)
        cur = account_usage(api_key)
        if cur is None:
            return last
        if cur == last:
            return cur
        last = cur
    return last


def reconcile(before: float | None, tokens_usd: float,
              api_key: str | None = None, **kw) -> Reconciliation:
    """Bill an episode from the provider's usage delta where possible."""
    if before is None:
        return Reconciliation(None, tokens_usd, "tokens_only",
                              "no provider reading before the episode")
    after = settled_usage(api_key, **kw)
    if after is None:
        return Reconciliation(None, tokens_usd, "tokens_only",
                              "provider unreachable after the episode")
    delta = round(after - before, 6)
    if delta < 0:
        # Usage should be monotonic; a decrease means the reading is not
        # comparable (key rotated, account reset).  Do not bill a negative.
        return Reconciliation(None, tokens_usd, "tokens_only",
                              f"provider usage went backwards ({before} -> {after})")
    return Reconciliation(delta, tokens_usd, "provider_delta")


@dataclass
class Credits:
    """The prepaid balance behind the key.

    Two ceilings bind a campaign and they are not the same thing.  The campaign
    cap is a policy we choose; the prepaid balance is a fact about the account.
    A run can be well inside its cap and still be unable to pay for the next
    episode, and discovering that halfway through one wastes it.
    """

    total_credits: float | None = None
    total_usage: float | None = None

    @property
    def remaining(self) -> float | None:
        if self.total_credits is None or self.total_usage is None:
            return None
        return round(self.total_credits - self.total_usage, 6)

    def to_dict(self) -> dict:
        return {"total_credits": self.total_credits,
                "total_usage": self.total_usage,
                "remaining": self.remaining}


def credits(api_key: str | None = None, *, timeout: float = 30.0) -> Credits:
    """Prepaid credits and usage.  Fields are None when unreadable."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return Credits()
    req = urllib.request.Request(
        CREDITS_URL, headers={"Authorization": f"Bearer {key}",
                              "User-Agent": "conetic-farm/balance"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode()).get("data", {})
    except (urllib.error.URLError, OSError, ValueError):
        return Credits()

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return Credits(_f(data.get("total_credits")), _f(data.get("total_usage")))
