#!/usr/bin/env python3
"""Build and freeze the 20-episode task plan.

Run once, before the campaign.  Writes config/task_plan.json.  Re-running with
the same seed and the same dataset reproduces it byte for byte; re-running after
results exist is refused unless --force is given, because the plan must not be
able to react to outcomes.

Controls are not sampled blindly.  "No conflict is expected" is a claim about
the code, and it has to be made deliberately.

The obvious criterion -- the two gold patches touch no file in common -- selects
**zero** of CooperBench's 652 pairs.  Every pair in the dataset edits at least
one shared file, because a task pairs two features drawn from the same upstream
pull request.  That is a property of the benchmark, not a bug, and it means
CooperBench cannot supply a control in the strict sense.  See
docs/HARNESS_NOTES.md.

The best available proxy is used instead, and named for what it is: a
**separation control**.  A pair qualifies when

  * the gold patches merge cleanly (has_conflict = false),
  * neither gold patch failed to apply,
  * the nearest pair of changed hunks across the two patches is at least
    ``--control-min-distance`` lines apart in every shared file, and
  * no more than two controls come from any single task, so the stratum is not
    dominated by one file.

That is a claim about *textual* distance only.  A separation control still
leaves both agents editing the same file, so a semantic interaction remains
possible; a conflict here is weaker evidence of a harness problem than a true
disjoint control would have been.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farm.plan import Pair, build_plan, load_pairs, stratify  # noqa: E402

DIFF_PATH = re.compile(r"^(?:---|\+\+\+)\s+[ab]/(.+?)(?:\t|$)", re.MULTILINE)


def patch_files(dataset: Path, repo: str, task_id: int, feature: int) -> set[str]:
    p = dataset / repo / f"task{task_id}" / f"feature{feature}" / "feature.patch"
    if not p.exists():
        return set()
    text = p.read_text(errors="replace")
    return {m.group(1) for m in DIFF_PATH.finditer(text) if m.group(1) != "dev/null"}


def top_module(path: str) -> str:
    parts = Path(path).parts
    return "/".join(parts[:2]) if len(parts) > 1 else parts[0] if parts else ""


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
NEWFILE = re.compile(r"^\+\+\+ b/(.+?)(?:\t|$)", re.MULTILINE)


def patch_hunks(dataset: Path, repo: str, task_id: int, feature: int) -> dict[str, list[tuple[int, int]]]:
    """Changed line ranges per file, read from the gold patch's hunk headers."""
    p = dataset / repo / f"task{task_id}" / f"feature{feature}" / "feature.patch"
    if not p.exists():
        return {}
    out: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in p.read_text(errors="replace").splitlines():
        m = NEWFILE.match(line)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        m = HUNK.match(line)
        if m and current:
            start = int(m.group(1))
            out[current].append((start, start + int(m.group(2) or 1)))
    return out


def min_hunk_distance(h1: dict, h2: dict) -> int | None:
    """Smallest line gap between any hunk of one patch and any hunk of the other.

    ``0`` means the hunks overlap.  ``None`` means the patches share no file,
    which does not occur anywhere in this dataset.
    """
    best: int | None = None
    for f in set(h1) & set(h2):
        for a0, a1 in h1[f]:
            for b0, b1 in h2[f]:
                d = 0 if (a0 <= b1 and b0 <= a1) else min(abs(b0 - a1), abs(a0 - b1))
                best = d if best is None else min(best, d)
    return best


def separation_controls(
    pairs: list[Pair], dataset: Path, *, min_distance: int, max_per_task: int = 2
) -> list[Pair]:
    scored: list[tuple[int, Pair]] = []
    for p in pairs:
        d = min_hunk_distance(
            patch_hunks(dataset, p.repo, p.task_id, p.f1),
            patch_hunks(dataset, p.repo, p.task_id, p.f2),
        )
        if d is not None and d >= min_distance:
            scored.append((d, p))
    scored.sort(key=lambda r: (-r[0], r[1].key))
    per_task: dict[tuple[str, int], int] = {}
    out: list[Pair] = []
    for _, p in scored:
        k = (p.repo, p.task_id)
        if per_task.get(k, 0) >= max_per_task:
            continue
        per_task[k] = per_task.get(k, 0) + 1
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cooperbench-dir", type=Path,
                    default=Path("/home/user/work/CooperBench"))
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / "config" / "task_plan.json")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--conflicting", type=int, default=10)
    ap.add_argument("--compatible", type=int, default=6)
    ap.add_argument("--control", type=int, default=4)
    ap.add_argument("--typescript-floor", type=int, default=4,
                    help="minimum conflicting episodes drawn from the TypeScript slice")
    ap.add_argument("--control-min-distance", type=int, default=150,
                    help="minimum line gap between the two gold patches' nearest hunks")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing frozen plan (do not use mid-campaign)")
    args = ap.parse_args()

    if args.out.exists() and not args.force:
        print(f"REFUSING: {args.out} already exists.  The plan is frozen before "
              f"the campaign and must not change once episodes have run.\n"
              f"Pass --force only if no episode has been executed yet.", file=sys.stderr)
        return 1

    dataset = args.cooperbench_dir / "dataset"
    pairs = load_pairs(dataset / "gold_conflict_report.json")
    buckets = stratify(pairs)

    controls = separation_controls(buckets["compatible"], dataset,
                                   min_distance=args.control_min_distance)
    strict = [p for p in buckets["compatible"]
              if not (set(patch_hunks(dataset, p.repo, p.task_id, p.f1))
                      & set(patch_hunks(dataset, p.repo, p.task_id, p.f2)))]

    print(f"pairs total                       {len(pairs)}")
    print(f"  conflicting (gold, both apply)  {len(buckets['conflicting'])}")
    print(f"  compatible  (gold, both apply)  {len(buckets['compatible'])}")
    print(f"  excluded: a gold patch failed to apply  {len(buckets['excluded_apply_failed'])}")
    print(f"  control candidates: strictly file-disjoint  {len(strict)}  (CooperBench has none by construction)")
    print(f"  control candidates: separation >= {args.control_min_distance} lines  {len(controls)}")

    plan = build_plan(
        pairs,
        n_conflicting=args.conflicting,
        n_compatible=args.compatible,
        n_control=args.control,
        seed=args.seed,
        control_pairs=controls,
        language_floor={"typescript": args.typescript_floor},
    )

    payload = {
        "schema": "conetic-farm/task-plan/1",
        "frozen": True,
        "seed": args.seed,
        "source": {
            "gold_conflict_report": str(dataset / "gold_conflict_report.json"),
            "cooperbench_commit": _git_head(args.cooperbench_dir),
        },
        "language_floor": {"typescript": args.typescript_floor},
        "strata_requested": {
            "conflicting": args.conflicting,
            "compatible": args.compatible,
            "control": args.control,
        },
        "pool_sizes": {
            "conflicting": len(buckets["conflicting"]),
            "compatible": len(buckets["compatible"]),
            "control_candidates_separation": len(controls),
            "control_candidates_strictly_disjoint": len(strict),
            "excluded_apply_failed": len(buckets["excluded_apply_failed"]),
        },
        "control_criteria": {
            "type": "separation_control",
            "definition": (
                "gold patches merge cleanly; neither gold patch failed to apply; "
                f"nearest changed hunks at least {args.control_min_distance} lines "
                "apart in every shared file; at most 2 per task"
            ),
            "caveat": (
                "NOT a disjoint control.  Zero of CooperBench's 652 pairs have "
                "disjoint gold-patch file sets -- every task pairs two features "
                "from the same upstream PR, editing the same file(s).  A "
                "separation control still has both agents editing one file, so "
                "semantic interaction remains possible."
            ),
            "strictly_disjoint_candidates_available": len(strict),
        },
        "episodes": [e.to_dict() for e in plan],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(f"\nwrote {args.out}")
    by_lang: dict[str, int] = {}
    by_stratum: dict[str, int] = {}
    for e in plan:
        by_lang[e.language] = by_lang.get(e.language, 0) + 1
        by_stratum[e.stratum] = by_stratum.get(e.stratum, 0) + 1
    print(f"  strata:    {by_stratum}")
    print(f"  languages: {by_lang}")
    return 0


def _git_head(path: Path) -> str:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
