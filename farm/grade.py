"""Run the A-alone / B-alone / merged triad and record every raw result.

CooperBench's own eval policy is `identical -> naive merge -> lead's patch
alone`, which scores an episode as a *pass* when the merge conflicted but one
agent's patch happens to satisfy both feature suites.  That is the wrong
instrument for this corpus: it converts an integration failure into a success.

So we grade independently.  Three fresh containers, one per condition, from the
same task image, each testing a tree we constructed ourselves:

    a_alone   base + A's patch      -> A's tests, then B's tests
    b_alone   base + B's patch      -> B's tests, then A's tests
    merged    base + merge(A, B)    -> both suites

The merge is a real three-way ``git merge`` of two branches rooted at the base
commit, not a sequential ``git apply``.  Sequential application hides conflicts
behind ordering: apply A then B and you learn whether B fits *after* A, which is
not the same question and is not symmetric.

CooperBench's ``eval.json`` is still collected alongside, unused for labelling,
so the two verdicts can be compared and their disagreement rate reported.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classify import MergeOutcome, TestOutcome

DEFAULT_TEST_TIMEOUT_S = 1800
DEFAULT_MERGE_TIMEOUT_S = 300


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class CommandRun:
    """Everything needed to re-run a step by hand, plus what it produced."""

    argv: list[str]
    cwd: str
    exit_code: int | None
    duration_s: float
    timed_out: bool
    stdout: str
    stderr: str
    started_at: str
    finished_at: str

    @property
    def command(self) -> str:
        return " ".join(shlex.quote(a) for a in self.argv)


def run_cmd(
    argv: list[str],
    *,
    cwd: str | Path = ".",
    timeout_s: int = DEFAULT_TEST_TIMEOUT_S,
    env: dict[str, str] | None = None,
    max_capture: int = 4_000_000,
) -> CommandRun:
    started = _utcnow()
    t0 = time.monotonic()
    timed_out = False
    try:
        p = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout_s, env=env, errors="replace",
        )
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        code = None
    return CommandRun(
        argv=list(argv), cwd=str(cwd), exit_code=code,
        duration_s=round(time.monotonic() - t0, 3), timed_out=timed_out,
        stdout=out[-max_capture:], stderr=err[-max_capture:],
        started_at=started, finished_at=_utcnow(),
    )


# ---------------------------------------------------------------------------
# Test-outcome interpretation
# ---------------------------------------------------------------------------

# A suite that never started is not a failing suite.  Distinguishing the two is
# the difference between "this patch is wrong" and "we learned nothing".
_ERROR_SIGNATURES = (
    "cannot find module", "modulenotfounderror", "importerror",
    "command not found", "no such file or directory",
    "econnrefused", "enospc", "out of memory", "killed",
    "error: could not compile", "cannot find name",
    "sh: 1:", "segmentation fault",
)
_NO_TESTS_SIGNATURES = (
    "no tests found", "no test files found", "0 passing", "collected 0 items",
    "no tests ran", "testing started" ,
)


def interpret_tests(run: CommandRun) -> tuple[TestOutcome, dict[str, Any]]:
    """Map a test-runner invocation onto pass / fail / error / not_run.

    Exit code is the primary signal.  It is overridden only when the output
    shows the suite could not run at all, because a build error and a genuine
    assertion failure both exit non-zero and mean entirely different things.
    """
    blob = f"{run.stdout}\n{run.stderr}".lower()
    detail: dict[str, Any] = {
        "exit_code": run.exit_code,
        "timed_out": run.timed_out,
        "duration_s": run.duration_s,
    }

    if run.timed_out:
        detail["reason"] = "timed out"
        return TestOutcome.ERROR, detail

    if run.exit_code == 0:
        # A green exit with zero tests collected is not a pass.
        if any(s in blob for s in ("no tests found", "no test files found",
                                   "collected 0 items", "no tests ran")):
            detail["reason"] = "exit 0 but no tests were collected"
            return TestOutcome.ERROR, detail
        detail["reason"] = "exit 0"
        return TestOutcome.PASS, detail

    hit = next((s for s in _ERROR_SIGNATURES if s in blob), None)
    if hit:
        detail["reason"] = f"suite could not run (matched {hit!r})"
        return TestOutcome.ERROR, detail

    detail["reason"] = f"non-zero exit ({run.exit_code}) with test output"
    detail.update(_parse_counts(blob))
    return TestOutcome.FAIL, detail


def _parse_counts(blob: str) -> dict[str, int]:
    """Best-effort pass/fail counts.  Advisory only; never used for labelling."""
    out: dict[str, int] = {}
    for key, pats in (
        ("tests_passed", (r"(\d+)\s+pass(?:ed|ing)", r"passed[,:]?\s+(\d+)")),
        ("tests_failed", (r"(\d+)\s+fail(?:ed|ing)", r"failed[,:]?\s+(\d+)")),
    ):
        for pat in pats:
            m = re.search(pat, blob)
            if m:
                out[key] = int(m.group(1))
                break
    return out


# ---------------------------------------------------------------------------
# Three-way merge
# ---------------------------------------------------------------------------


@dataclass
class MergeReport:
    outcome: MergeOutcome
    strategy: str
    conflicted_paths: list[str] = field(default_factory=list)
    merged_diff: str = ""
    commands: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d


def three_way_merge(
    repo_dir: Path,
    base_commit: str,
    patch_a: Path,
    patch_b: Path,
    *,
    timeout_s: int = DEFAULT_MERGE_TIMEOUT_S,
) -> MergeReport:
    """Merge two patches as sibling branches off ``base_commit``.

    Symmetric by construction: neither patch is privileged by application order.
    Every command is recorded so the merge can be reproduced exactly.
    """
    cmds: list[dict[str, Any]] = []

    def git(*args: str, check: bool = False) -> CommandRun:
        r = run_cmd(["git", *args], cwd=repo_dir, timeout_s=timeout_s)
        cmds.append({"cmd": r.command, "exit": r.exit_code,
                     "stdout": r.stdout[-8000:], "stderr": r.stderr[-8000:]})
        if check and r.exit_code != 0:
            raise RuntimeError(f"{r.command} failed: {r.stderr[-2000:]}")
        return r

    strategy = (
        "git checkout -B farm/base <base_commit>; "
        "for each side: branch off base, `git apply --index` the patch, commit; "
        "then `git merge --no-commit --no-ff` side B into side A"
    )

    try:
        git("checkout", "-B", "farm/base", base_commit, check=True)
        for branch, patch in (("farm/a", patch_a), ("farm/b", patch_b)):
            git("checkout", "-B", branch, "farm/base", check=True)
            ap = git("apply", "--index", "--ignore-whitespace", str(patch))
            if ap.exit_code != 0:
                # Fall back to 3-way application before declaring failure: a
                # patch with fuzzy context is not the same as a bad patch.
                ap = git("apply", "--3way", "--index", str(patch))
                if ap.exit_code != 0:
                    return MergeReport(
                        MergeOutcome.ERROR, strategy, commands=cmds,
                        note=f"patch for {branch} would not apply to the base tree",
                    )
            git("commit", "--quiet", "--allow-empty", "-m", f"{branch} patch",
                check=True)

        git("checkout", "farm/a", check=True)
        m = git("merge", "--no-commit", "--no-ff", "farm/b")
        if m.exit_code != 0:
            names = git("diff", "--name-only", "--diff-filter=U")
            paths = [p for p in names.stdout.splitlines() if p.strip()]
            git("merge", "--abort")
            return MergeReport(MergeOutcome.CONFLICT, strategy,
                               conflicted_paths=paths, commands=cmds,
                               note=f"{len(paths)} conflicted path(s)")

        diff = git("diff", "--binary", "farm/base")
        return MergeReport(MergeOutcome.CLEAN, strategy,
                           merged_diff=diff.stdout, commands=cmds)
    except RuntimeError as exc:
        return MergeReport(MergeOutcome.ERROR, strategy, commands=cmds,
                           note=str(exc))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
