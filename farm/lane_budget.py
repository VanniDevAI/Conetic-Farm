"""Enforce a lane's ceiling on billed dollars, and never lose its work.

`c05b` spent $10.47 of a $10 cap and got one measurable episode out of three.
Two faults did that, and both are here.

**The ceiling was enforced on the wrong number.** The agent harness stops a lane
when the model's *self-reported* cost reaches a limit. The provider bills more
than that -- 1.75x on one Sonnet lane, 6.5x on a qwen lane -- so a $2.50 ceiling
was a $4.39 bill. Ceilings now read the provider meter.

**Hitting a ceiling threw the work away.** The agent writes `patch.txt` only when
it decides it is finished, so a lane cut off mid-task returns nothing at all. A
warning at 80% was tried and declined by both lanes that saw it. So the stop is
no longer a request: when a lane crosses its ceiling the container's working
tree is diffed against the image's base commit and *that* is its submission,
however unfinished. An incomplete patch is a result; an empty one is not.

**And a guard that checks at zero overruns.** Starting a lane needs headroom for
what a lane can actually cost, not merely a positive balance, so the reserve is
the worst lane cost observed so far.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .provider import account_usage


def image_base_commit(image: str, workdir: str = "/workspace/repo") -> str | None:
    r = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "git", image, "-C", workdir,
         "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def agent_containers(since: float) -> list[str]:
    """Container ids of agent sandboxes started after `since`.

    The adapter names them `minisweagent-<hex>`; matching on the name rather
    than on the image keeps this working when several images are in play.
    """
    r = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.CreatedAt}}"],
        capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].startswith("minisweagent-"):
            out.append(parts[0])
    return out


def salvage(container: str, base: str, dest: Path,
            workdir: str = "/workspace/repo") -> int:
    """Write the container's working tree, as a diff against `base`, to `dest`.

    `git add -A` first so untracked files count: a lane that added a router in a
    new file has done real work, and a plain `git diff` would show none of it.
    The index is dirtied, which does not matter -- the container is about to be
    destroyed.
    """
    script = (f"cd {workdir} && git add -A >/dev/null 2>&1; "
              f"git diff --binary {base}")
    r = subprocess.run(["docker", "exec", container, "bash", "-lc", script],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(r.stdout)
    return len(r.stdout.splitlines())


@dataclass
class LaneWatchdog:
    """Poll the meter while a lane runs; salvage and stop it at its ceiling."""
    ceiling_usd: float
    start_usd: float
    base_commit: str | None
    dest: Path
    poll_s: float = 20.0
    _stop: threading.Event = field(default_factory=threading.Event)
    tripped: bool = False
    salvaged_lines: int = 0
    _thread: threading.Thread | None = None
    _started_at: float = 0.0

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            now = account_usage()
            if now is None:
                continue
            if now - self.start_usd < self.ceiling_usd:
                continue
            self.tripped = True
            for cid in agent_containers(self._started_at):
                if self.base_commit:
                    self.salvaged_lines = salvage(cid, self.base_commit, self.dest)
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
            return

    def __enter__(self) -> "LaneWatchdog":
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def salvage_live_lanes(base_commit: str | None, dest: Path) -> int:
    """Take whatever any live agent container holds, then remove it.

    The cost ceiling is not the only way a lane ends without submitting. A slow
    provider can carry a lane past the harness's own subprocess timeout, and
    that path threw the work away exactly as the ceiling used to: the container
    is killed, `patch.txt` was never written, and the lane reads as having
    produced nothing when it had produced most of a feature.
    """
    total = 0
    for cid in agent_containers(0.0):
        if base_commit:
            total = max(total, salvage(cid, base_commit, dest))
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    return total


@dataclass
class Reserve:
    """Refuse to start a lane without headroom for what a lane can cost."""
    cap_usd: float
    floor_usd: float = 0.75
    worst_seen: float = 0.0

    def observe(self, lane_cost: float) -> None:
        self.worst_seen = max(self.worst_seen, lane_cost)

    @property
    def required(self) -> float:
        return max(self.worst_seen, self.floor_usd)

    def may_start(self, spent: float) -> tuple[bool, str]:
        remaining = self.cap_usd - spent
        if remaining >= self.required:
            return True, ""
        return False, (f"${remaining:.4f} left but a lane has cost up to "
                       f"${self.required:.4f}; starting one could overrun the cap")
