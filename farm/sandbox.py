"""Run graded work inside task containers.

Every grading condition gets a **fresh** container from the task image, so no
condition can see another's tree.  Nothing is graded on the host.

The task images expose ``runner.sh <test_patch> [feature_patch]`` with patches
mounted at ``/patches``; it applies the feature patch, then the test patch, runs
the suite, and cleans the tree on exit.  We reuse that entrypoint rather than
reimplementing it, so a graded run executes the same commands the benchmark
authors intended.

The three-way merge also happens in a container, against the repository's real
git history at the base commit.  Doing it on the host would need a second
checkout and would risk grading a tree that differs from the one under test.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .classify import MergeOutcome
from .grade import CommandRun, run_cmd

WORKDIR = "/workspace/repo"


class SandboxError(RuntimeError):
    pass


def image_exists(image: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", image],
                          capture_output=True).returncode == 0


def _run_in_image(
    image: str,
    script: str,
    *,
    mounts: dict[str, str] | None = None,
    rw_mounts: dict[str, str] | None = None,
    timeout_s: int = 1800,
    entrypoint: str = "/bin/bash",
) -> CommandRun:
    argv = ["docker", "run", "--rm", "--entrypoint", entrypoint]
    for host, cont in (mounts or {}).items():
        argv += ["-v", f"{host}:{cont}:ro"]
    for host, cont in (rw_mounts or {}).items():
        argv += ["-v", f"{host}:{cont}"]
    argv += [image, "-lc", script]
    return run_cmd(argv, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Base repository state
# ---------------------------------------------------------------------------


def export_base_bundle(image: str, dest_dir: Path, *, timeout_s: int = 900) -> dict[str, Any]:
    """Export the pre-agent repository state as a standalone git bundle.

    A bundle rather than a tarball: it carries the real history, so a replayer
    can diff, branch and merge against the exact base commit without needing
    network access or this repository.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"farm-bundle-{uuid.uuid4().hex[:8]}"

    cid = subprocess.run(
        ["docker", "run", "-d", "--name", name, "--entrypoint", "/bin/bash",
         image, "-c", "sleep 900"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        head = subprocess.run(
            ["docker", "exec", "-w", WORKDIR, cid, "git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        r = subprocess.run(
            ["docker", "exec", "-w", WORKDIR, cid, "git", "bundle", "create",
             "/tmp/base.bundle", "HEAD"],
            capture_output=True, text=True, timeout=timeout_s)
        if r.returncode != 0:
            raise SandboxError(f"git bundle failed: {r.stderr[-500:]}")
        subprocess.run(["docker", "cp", f"{cid}:/tmp/base.bundle",
                        str(dest_dir / "base.bundle")], check=True,
                       capture_output=True)
        (dest_dir / "base_commit.txt").write_text(head + "\n")
        return {
            "base_commit": head,
            "bundle": str(dest_dir / "base.bundle"),
            "bundle_bytes": (dest_dir / "base.bundle").stat().st_size,
        }
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


def run_feature_tests(
    image: str,
    patches_dir: Path,
    test_patch: str,
    feature_patch: str | None,
    *,
    timeout_s: int = 1800,
) -> CommandRun:
    """Run one feature's test suite against base + an optional patch.

    ``feature_patch=None`` runs the tests against the untouched base, which is
    how we confirm a suite actually discriminates rather than passing anyway.
    """
    argv = ["docker", "run", "--rm", "-v", f"{patches_dir}:/patches:ro", image, test_patch]
    if feature_patch:
        argv.append(feature_patch)
    return run_cmd(argv, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Three-way merge, in the container, against real history
# ---------------------------------------------------------------------------

_MERGE_SCRIPT = r"""
set -uo pipefail
cd {workdir}
git config user.email farm@conetic-farm.invalid
git config user.name  conetic-farm
git config core.fileMode false

BASE="$(git rev-parse HEAD)"
echo "FARM_BASE=$BASE"

apply_side () {{   # $1 branch, $2 patch file
  git checkout -q -B "$1" "$BASE" || return 90
  git apply --index --ignore-whitespace "/patches/$2" 2>/tmp/apply.err \
    || git apply --3way --index "/patches/$2" 2>>/tmp/apply.err \
    || {{ echo "FARM_APPLY_FAILED=$1"; cat /tmp/apply.err; return 91; }}
  git commit -q --allow-empty -m "$1"
}}

apply_side farm_a "{patch_a}" || exit 91
apply_side farm_b "{patch_b}" || exit 92

git checkout -q farm_a
if git merge --no-commit --no-ff farm_b >/tmp/merge.out 2>&1; then
  echo "FARM_MERGE=clean"
  # Write the diff to a file rather than stdout.  Piping `git diff --binary`
  # through the captured stream corrupts it: text decoding mangles binary
  # hunks and trailing whitespace, and `git apply` then rejects the result
  # with "corrupt patch at line N" -- which grades as a failing test when in
  # fact no test ever ran.
  git diff --binary "$BASE" > /out/merged.diff
  echo "FARM_DIFF_BYTES=$(wc -c < /out/merged.diff)"
  exit 0
else
  echo "FARM_MERGE=conflict"
  echo "FARM_CONFLICTS_BEGIN"
  git diff --name-only --diff-filter=U
  echo "FARM_CONFLICTS_END"
  echo "FARM_MERGEOUT_BEGIN"; cat /tmp/merge.out; echo "FARM_MERGEOUT_END"
  git merge --abort 2>/dev/null || true
  exit 10
fi
"""


@dataclass
class ContainerMergeReport:
    outcome: MergeOutcome
    base_commit: str = ""
    conflicted_paths: list[str] = field(default_factory=list)
    merged_diff: str = ""
    raw: str = ""
    note: str = ""
    strategy: str = (
        "in-container three-way merge: branch farm_a and farm_b off HEAD (the "
        "task's base commit), `git apply --index` each agent patch (falling back "
        "to --3way), commit, then `git merge --no-commit --no-ff farm_b` into "
        "farm_a. Symmetric: neither patch is privileged by application order."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "strategy": self.strategy,
            "base_commit": self.base_commit,
            "conflicted_paths": self.conflicted_paths,
            "merged_diff_bytes": len(self.merged_diff),
            "note": self.note,
        }


def _between(text: str, start: str, end: str) -> str:
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n")


def three_way_merge(
    image: str,
    patches_dir: Path,
    patch_a: str,
    patch_b: str,
    *,
    out_dir: Path | None = None,
    timeout_s: int = 600,
) -> ContainerMergeReport:
    import tempfile
    tmp = None
    if out_dir is None:
        tmp = tempfile.mkdtemp(prefix="farm-merge-")
        out_dir = Path(tmp)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = _MERGE_SCRIPT.format(
        workdir=WORKDIR, patch_a=patch_a, patch_b=patch_b
    )
    r = _run_in_image(image, script, mounts={str(patches_dir): "/patches"},
                      rw_mounts={str(out_dir): "/out"}, timeout_s=timeout_s)
    out = r.stdout + r.stderr
    base = ""
    for line in out.splitlines():
        if line.startswith("FARM_BASE="):
            base = line.split("=", 1)[1].strip()
            break

    if r.timed_out:
        return ContainerMergeReport(MergeOutcome.ERROR, base, raw=out[-8000:],
                                    note="merge timed out")
    if "FARM_MERGE=clean" in out:
        produced = out_dir / "merged.diff"
        diff = produced.read_text(errors="replace") if produced.exists() else ""
        if not diff.strip():
            return ContainerMergeReport(
                MergeOutcome.ERROR, base, raw=out[-8000:],
                note="merge reported clean but produced no diff")
        return ContainerMergeReport(MergeOutcome.CLEAN, base,
                                    merged_diff=diff, raw=out[-8000:])
    if "FARM_MERGE=conflict" in out:
        paths = [p for p in
                 _between(out, "FARM_CONFLICTS_BEGIN", "FARM_CONFLICTS_END").splitlines()
                 if p.strip()]
        return ContainerMergeReport(
            MergeOutcome.CONFLICT, base, conflicted_paths=paths, raw=out[-8000:],
            note=f"{len(paths)} conflicted path(s)")
    if "FARM_APPLY_FAILED=" in out:
        side = out.split("FARM_APPLY_FAILED=", 1)[1].split()[0]
        # A patch that will not apply to the base is a property of that patch,
        # not of the merge.  Reported distinctly so it is never mislabelled as
        # an integration failure.
        return ContainerMergeReport(
            MergeOutcome.ERROR, base, raw=out[-8000:],
            note=f"patch for {side} would not apply to the base tree")
    return ContainerMergeReport(MergeOutcome.ERROR, base, raw=out[-8000:],
                                note=f"unrecognised merge output (exit {r.exit_code})")
