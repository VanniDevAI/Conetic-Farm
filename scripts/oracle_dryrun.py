#!/usr/bin/env python3
"""Validate the grading pipeline against known ground truth, without agents.

Substitutes each feature's **gold** patch for the agent patch and runs the whole
triad: A alone, B alone, three-way merge, merged tests, classification.

The gold patches are the benchmark's own reference solutions, so the expected
label is known in advance:

  * a pair the dataset marks ``has_conflict: true``  -> integration_failure_merge
  * a pair it marks ``has_conflict: false``          -> both_pass_merge_passes

Any disagreement is a bug in our grading, in the task image, or in the dataset's
labels -- and we would much rather find it here than infer it from agent runs.
This also doubles as CooperBench's "oracle" check that the infrastructure works.

    scripts/oracle_dryrun.py --episode <episode_id>
    scripts/oracle_dryrun.py --repo react_hook_form_task --task 153 --features 1,6
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm import sandbox                                          # noqa: E402
from farm.classify import Label                                    # noqa: E402
from farm.episode import EpisodeRunner, EpisodeSpec                # noqa: E402
from farm.cost import Budget                                       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode")
    ap.add_argument("--repo")
    ap.add_argument("--task", type=int)
    ap.add_argument("--features", help="e.g. 1,6")
    ap.add_argument("--plan", default=str(REPO_ROOT / "config" / "task_plan.json"))
    ap.add_argument("--data-root", default="/home/user/farm-data-dryrun")
    ap.add_argument("--cooperbench-dir", default="/home/user/work/CooperBench")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())["episodes"]
    if args.episode:
        e = next((x for x in plan if x["episode_id"] == args.episode), None)
        if not e:
            raise SystemExit(f"no episode {args.episode!r} in the plan")
    elif args.repo and args.task and args.features:
        f1, f2 = (int(x) for x in args.features.split(","))
        e = next((x for x in plan if x["repo"] == args.repo and x["task_id"] == args.task
                  and {x["f1"], x["f2"]} == {f1, f2}), None)
        e = e or {"episode_id": f"adhoc__{args.repo}__task{args.task}__f{f1}_f{f2}",
                  "repo": args.repo, "task_id": args.task, "f1": f1, "f2": f2,
                  "language": "?", "stratum": "?", "gold_has_conflict": None, "order": 0}
    else:
        e = plan[0]

    spec = EpisodeSpec(**{k: e[k] for k in
                          ("episode_id", "repo", "task_id", "f1", "f2",
                           "language", "stratum", "gold_has_conflict", "order")})
    print(f"episode  {spec.episode_id}")
    print(f"stratum  {spec.stratum}   language {spec.language}")
    print(f"gold_has_conflict = {spec.gold_has_conflict}")

    data_root = Path(args.data_root)
    runner = EpisodeRunner(
        spec, data_root=data_root, cooperbench_dir=Path(args.cooperbench_dir),
        budget=Budget(1.0, data_root / "dryrun_ledger.jsonl"),
        model_a="gold", model_b="gold", campaign="oracle",
    )
    print(f"image    {runner.image}")
    runner.ensure_image()
    runner.prepare_base()

    attempt = runner.paths.attempt(1)
    if attempt.exists():
        shutil.rmtree(attempt)
    attempt.mkdir(parents=True)

    # Gold patches stand in for agent output.
    task = runner.paths.base / "task"
    collected = {"agents": {}}
    for role, fid in (("A", spec.f1), ("B", spec.f2)):
        adir = attempt / "agents" / role
        adir.mkdir(parents=True)
        gold = task / f"feature{fid}" / "feature.patch"
        shutil.copy2(gold, adir / "patch.diff")
        collected["agents"][role] = {
            "feature_id": fid, "model": "gold", "status": "gold",
            "has_patch": True, "patch_bytes": gold.stat().st_size,
        }

    print("\nrunning the triad (each in a fresh container)...")
    cls, parts = runner.grade(attempt, collected)

    a, b, m = parts["a"], parts["b"], parts["merge"]
    print(f"\n  A alone: own={a.own_tests.value:<8} partner={a.partner_tests.value}")
    print(f"  B alone: own={b.own_tests.value:<8} partner={b.partner_tests.value}")
    print(f"  merge  : {m.outcome.value}"
          + (f"  conflicts={list(m.conflicted_paths)}" if m.conflicted_paths else "")
          + (f"  a_tests={m.a_tests.value} b_tests={m.b_tests.value}"
             if m.outcome.value == "clean" else ""))
    print(f"\n  LABEL  : {cls.label.value}")
    print(f"  reason : {cls.rationale}")
    for w in cls.warnings:
        print(f"  warn   : {w}")

    if spec.gold_has_conflict is None:
        print("\nno gold label to compare against.")
        return 0
    expected = (Label.INTEGRATION_FAILURE_MERGE if spec.gold_has_conflict
                else Label.BOTH_PASS_MERGE_PASSES)
    ok = cls.label is expected
    print(f"\n  expected from the dataset's gold label: {expected.value}")
    print(f"  {'MATCH' if ok else 'MISMATCH'}")
    if not ok:
        print("\n  A mismatch is informative, not automatically a bug:")
        print("   - gold patches passing alone but failing merged tests is a real")
        print("     semantic integration failure the textual label cannot see;")
        print("   - a gold patch failing its own tests points at the task image;")
        print("   - a clean merge where a conflict was predicted means the dataset's")
        print("     label disagrees with git's own three-way merge.")
    print(f"\n  artifacts: {attempt}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
