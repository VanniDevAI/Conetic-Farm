"""Merge N branches the way a team would, and say exactly where it broke.

`farm.sandbox.three_way_merge` handles two patches, which is all a pair needs.
Step B runs three lanes, and three lanes fail in ways two cannot: the pairwise
merges can all be clean while the three-way is not, and which pair conflicts is
part of the finding rather than a detail.

So this does the real thing -- a branch per lane off the same base, merged one
at a time -- rather than applying patches in sequence with `git apply`, which
answers a different and easier question. A patch that will not apply at all is
reported separately from a merge that conflicts, because a lane that never
produced an applicable patch has not disagreed with anyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .grade import CommandRun
from .sandbox import WORKDIR, _run_in_image

_SCRIPT = r"""
set -uo pipefail
cd {workdir}
git config user.email farm@conetic-farm.invalid
git config user.name  conetic-farm
git config core.fileMode false

BASE="$(git rev-parse HEAD)"
echo "FARM_BASE=$BASE"

{apply_block}

git checkout -q -B farm_merge "$BASE"
{merge_block}

echo "FARM_MERGE=clean"
git diff --binary "$BASE" > /out/merged.diff
echo "FARM_DIFF_BYTES=$(wc -c < /out/merged.diff)"
exit 0
"""

_APPLY = r"""
git checkout -q -B {branch} "$BASE" || exit 90
if ! git apply --index --ignore-whitespace "/patches/{patch}" 2>/tmp/e; then
  if ! git apply --3way --index "/patches/{patch}" 2>>/tmp/e; then
    echo "FARM_APPLY_FAILED={lane}"; cat /tmp/e; exit 91
  fi
fi
git commit -q --allow-empty -m "{branch}"
"""

_MERGE = r"""
if ! git merge --no-commit --no-ff {branch} >/tmp/m 2>&1; then
  echo "FARM_MERGE=conflict"
  echo "FARM_CONFLICT_LANE={lane}"
  echo "FARM_CONFLICTS_BEGIN"; git diff --name-only --diff-filter=U; echo "FARM_CONFLICTS_END"
  echo "FARM_MERGEOUT_BEGIN"; cat /tmp/m; echo "FARM_MERGEOUT_END"
  git merge --abort 2>/dev/null || true
  exit 10
fi
git commit -q --no-edit -m "merge {lane}" || true
"""


@dataclass
class NWayReport:
    outcome: str                       # "clean" | "conflict" | "apply_failed" | "error"
    lanes: tuple[str, ...] = ()
    conflicted_paths: tuple[str, ...] = ()
    conflict_lane: str | None = None
    failed_lane: str | None = None
    merged_diff: str = ""
    raw: str = ""
    base: str = ""

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "lanes": list(self.lanes),
                "conflicted_paths": list(self.conflicted_paths),
                "conflict_lane": self.conflict_lane,
                "failed_lane": self.failed_lane, "base": self.base}


def _between(text: str, start: str, end: str) -> list[str]:
    if start not in text or end not in text:
        return []
    body = text.split(start, 1)[1].split(end, 1)[0]
    return [line.strip() for line in body.splitlines() if line.strip()]


def merge_lanes(image: str, patches_dir: Path, lane_patches: list[tuple[str, str]],
                *, out_dir: Path, timeout_s: int = 900) -> NWayReport:
    """Merge every lane's patch onto one base, in the order given."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    apply_block = "\n".join(
        _APPLY.format(branch=f"farm_{lane}", patch=patch, lane=lane)
        for lane, patch in lane_patches)
    merge_block = "\n".join(
        _MERGE.format(branch=f"farm_{lane}", lane=lane) for lane, _ in lane_patches)
    script = _SCRIPT.format(workdir=WORKDIR, apply_block=apply_block,
                            merge_block=merge_block)
    r: CommandRun = _run_in_image(image, script,
                                  mounts={str(patches_dir): "/patches"},
                                  rw_mounts={str(out_dir): "/out"},
                                  timeout_s=timeout_s)
    text = r.stdout + r.stderr
    base = ""
    for line in text.splitlines():
        if line.startswith("FARM_BASE="):
            base = line.split("=", 1)[1].strip()
    lanes = tuple(lane for lane, _ in lane_patches)

    if "FARM_APPLY_FAILED=" in text:
        lane = text.split("FARM_APPLY_FAILED=", 1)[1].splitlines()[0].strip()
        return NWayReport("apply_failed", lanes, failed_lane=lane, raw=text, base=base)
    if "FARM_MERGE=conflict" in text:
        lane = None
        if "FARM_CONFLICT_LANE=" in text:
            lane = text.split("FARM_CONFLICT_LANE=", 1)[1].splitlines()[0].strip()
        return NWayReport("conflict", lanes,
                          conflicted_paths=tuple(_between(text, "FARM_CONFLICTS_BEGIN",
                                                          "FARM_CONFLICTS_END")),
                          conflict_lane=lane, raw=text, base=base)
    if "FARM_MERGE=clean" in text:
        merged = out_dir / "merged.diff"
        return NWayReport("clean", lanes,
                          merged_diff=merged.read_text() if merged.exists() else "",
                          raw=text, base=base)
    return NWayReport("error", lanes, raw=text, base=base)
