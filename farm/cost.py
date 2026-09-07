"""Cost accounting and hard spend cap.

Two independent jobs:

1. Convert per-agent token usage into USD, per attempt, per episode, in total.
2. Refuse to start work that could take the campaign past the cap.

The cap is a *hard stop*.  ``Budget.reserve`` is called before an agent is
launched and raises :class:`BudgetExceeded` when the reservation would not fit.
Ledger writes are append-only and fsync'd, so a crashed run still leaves an
accurate total; the ledger, not an in-memory counter, is the source of truth
and is re-read on startup.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised when an operation would take spend past the hard cap."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens, as published by the provider."""

    prompt_per_mtok: float
    completion_per_mtok: float
    # Some providers bill cached reads at a discount; None means "same as prompt".
    cached_prompt_per_mtok: float | None = None

    def cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cached_prompt_tokens: int = 0,
    ) -> float:
        uncached = max(0, prompt_tokens - cached_prompt_tokens)
        cached_rate = (
            self.cached_prompt_per_mtok
            if self.cached_prompt_per_mtok is not None
            else self.prompt_per_mtok
        )
        return (
            uncached * self.prompt_per_mtok
            + cached_prompt_tokens * cached_rate
            + completion_tokens * self.completion_per_mtok
        ) / 1_000_000.0


@dataclass
class Usage:
    """Token counts for one agent run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_prompt_tokens=self.cached_prompt_tokens + other.cached_prompt_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            requests=self.requests + other.requests,
        )


@dataclass
class LedgerEntry:
    ts: str
    kind: str  # "reserve" | "settle" | "release" | "note"
    episode_id: str | None
    attempt: str | None
    agent: str | None
    model: str | None
    amount_usd: float
    usage: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # "provider_reported" | "computed_from_tokens" | "estimate"
    note: str = ""


class Budget:
    """Append-only USD ledger with a hard cap.

    Money moves through three states:

    ``reserve``  optimistic hold taken *before* an agent runs, sized from the
                 model's price and the agent's max token budget.
    ``settle``   the hold is replaced by the real cost once the run reports usage.
    ``release``  the hold is dropped without charge (agent never started).

    ``committed`` (settled) plus ``held`` (outstanding reservations) is what is
    checked against the cap, so two concurrent agents can never jointly overshoot.
    """

    def __init__(self, cap_usd: float, ledger_path: str | os.PathLike[str]) -> None:
        if cap_usd <= 0:
            raise ValueError("cap_usd must be positive")
        self.cap_usd = float(cap_usd)
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._committed = 0.0
        self._holds: dict[str, float] = {}
        self._replay()

    # -- persistence -------------------------------------------------------

    def _replay(self) -> None:
        """Rebuild state from the ledger so a restart cannot double-spend."""
        if not self.ledger_path.exists():
            return
        with self.ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # A torn final line from a hard kill.  Ignore it, but do not
                    # silently forget: the note is surfaced by `farm report`.
                    continue
                kind = rec.get("kind")
                if kind == "settle":
                    self._committed += float(rec.get("amount_usd", 0.0))
                    self._holds.pop(rec.get("hold_id", ""), None)
                elif kind == "reserve":
                    self._holds[rec.get("hold_id", "")] = float(rec.get("amount_usd", 0.0))
                elif kind == "release":
                    self._holds.pop(rec.get("hold_id", ""), None)

    def _append(self, entry: LedgerEntry, **extra: Any) -> None:
        rec = asdict(entry)
        rec.update(extra)
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- accounting --------------------------------------------------------

    @property
    def committed_usd(self) -> float:
        with self._lock:
            return self._committed

    @property
    def held_usd(self) -> float:
        with self._lock:
            return sum(self._holds.values())

    @property
    def exposure_usd(self) -> float:
        """Settled spend plus outstanding reservations."""
        with self._lock:
            return self._committed + sum(self._holds.values())

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.exposure_usd)

    def would_exceed(self, amount_usd: float) -> bool:
        return self.exposure_usd + amount_usd > self.cap_usd

    def reserve(
        self,
        hold_id: str,
        amount_usd: float,
        *,
        episode_id: str | None = None,
        attempt: str | None = None,
        agent: str | None = None,
        model: str | None = None,
    ) -> None:
        """Take a hold, or raise :class:`BudgetExceeded`."""
        with self._lock:
            if hold_id in self._holds:
                raise ValueError(f"hold {hold_id!r} already outstanding")
            if self.would_exceed(amount_usd):
                raise BudgetExceeded(
                    f"reserving ${amount_usd:.4f} would take exposure to "
                    f"${self.exposure_usd + amount_usd:.4f}, past the "
                    f"${self.cap_usd:.2f} cap "
                    f"(settled ${self._committed:.4f}, held ${self.held_usd:.4f})"
                )
            self._holds[hold_id] = amount_usd
            self._append(
                LedgerEntry(
                    ts=_utcnow(), kind="reserve", episode_id=episode_id,
                    attempt=attempt, agent=agent, model=model,
                    amount_usd=amount_usd, source="estimate",
                    note="pre-run hold",
                ),
                hold_id=hold_id,
            )

    def settle(
        self,
        hold_id: str,
        amount_usd: float,
        *,
        usage: Usage | None = None,
        source: str = "computed_from_tokens",
        episode_id: str | None = None,
        attempt: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        note: str = "",
    ) -> None:
        """Replace a hold with the real cost.

        Settling is never refused: the money is already spent.  Overshoot past
        the cap is recorded and surfaced, and the *next* ``reserve`` fails.
        """
        with self._lock:
            self._holds.pop(hold_id, None)
            self._committed += amount_usd
            self._append(
                LedgerEntry(
                    ts=_utcnow(), kind="settle", episode_id=episode_id,
                    attempt=attempt, agent=agent, model=model,
                    amount_usd=amount_usd,
                    usage=asdict(usage) if usage else {},
                    source=source, note=note,
                ),
                hold_id=hold_id,
            )

    def release(self, hold_id: str, *, note: str = "") -> None:
        """Drop a hold without charge."""
        with self._lock:
            if self._holds.pop(hold_id, None) is None:
                return
            self._append(
                LedgerEntry(
                    ts=_utcnow(), kind="release", episode_id=None, attempt=None,
                    agent=None, model=None, amount_usd=0.0, note=note,
                ),
                hold_id=hold_id,
            )

    def note(self, text: str, **extra: Any) -> None:
        self._append(
            LedgerEntry(
                ts=_utcnow(), kind="note", episode_id=None, attempt=None,
                agent=None, model=None, amount_usd=0.0, note=text,
            ),
            **extra,
        )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cap_usd": self.cap_usd,
                "settled_usd": round(self._committed, 6),
                "held_usd": round(self.held_usd, 6),
                "exposure_usd": round(self.exposure_usd, 6),
                "remaining_usd": round(self.remaining_usd, 6),
                "cap_reached": self.remaining_usd <= 0.0,
            }


# ---------------------------------------------------------------------------
# Pinned price table
# ---------------------------------------------------------------------------

_PRICING_PATH = Path(__file__).resolve().parents[1] / "config" / "pricing.json"


class MissingPrice(RuntimeError):
    """No pinned price for a model.  Never treated as free inference."""


class ZeroCostWithUsage(RuntimeError):
    """A settlement reported $0 while real tokens were consumed.

    This is the failure mode that made CooperBench's own benchmark table record
    ``$0`` for `codex` while it did 400k+ input tokens of billable work: LiteLLM
    returns no cost for a model absent from its registry, and the harness's
    default ``cost_tracking: ignore_errors`` (config/coop.yaml:224) suppresses
    even the warning.  Against a hard spend cap, silently free inference is the
    most dangerous possible bug, so we refuse it rather than record it.
    """


def load_pricing(path: Path | None = None) -> dict[str, Price]:
    """Load the pinned price table.  Prices are pinned, not fetched at runtime.

    A campaign's totals must not change because a provider repriced midway --
    the recorded number has to mean the same thing on every episode.
    """
    p = Path(path or _PRICING_PATH)
    if not p.exists():
        raise MissingPrice(f"no pinned price table at {p}")
    data = json.loads(p.read_text())
    return {
        name: Price(
            prompt_per_mtok=float(v["prompt_per_mtok"]),
            completion_per_mtok=float(v["completion_per_mtok"]),
            cached_prompt_per_mtok=(
                float(v["cached_prompt_per_mtok"]) if "cached_prompt_per_mtok" in v else None
            ),
        )
        for name, v in data.get("models", {}).items()
    }


def price_for(model: str, table: dict[str, Price] | None = None) -> Price:
    table = table if table is not None else load_pricing()
    if model in table:
        return table[model]
    raise MissingPrice(
        f"no pinned price for {model!r}; add it to config/pricing.json rather "
        f"than letting the run record zero cost"
    )


def cost_of(model: str, usage: Usage, table: dict[str, Price] | None = None) -> float:
    """Cost from token counts and the pinned table -- never a reported figure.

    Raises if the result would be $0 despite real usage, so a missing price is
    surfaced instead of quietly consuming budget.
    """
    price = price_for(model, table)
    amount = price.cost(
        usage.prompt_tokens, usage.completion_tokens, usage.cached_prompt_tokens
    )
    if amount <= 0.0 and (usage.prompt_tokens or usage.completion_tokens):
        raise ZeroCostWithUsage(
            f"computed $0.00 for {model!r} despite "
            f"{usage.prompt_tokens} prompt + {usage.completion_tokens} completion "
            f"tokens -- the price table is wrong or incomplete"
        )
    return amount
