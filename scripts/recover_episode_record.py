#!/usr/bin/env python3
"""Write an episode's record from the artifacts a crashed run left behind.

c07's first episode ran both lanes, both repair lanes, and was graded twice --
$0.5459 billed -- and then the runner raised on the last statement that
assembles the record. Everything the record needs was already on disk: the
patches, both grades, the merge, the per-lane results. Only the record was
missing.

Re-running the episode would pay for it twice. This reads what is there and
writes the record the runner would have written, from the same inputs and the
same rules, with the ledger reconstructed from the meter deltas the run logged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.conventions import grade as grade_conventions          # noqa: E402
from farm.episode_record import SCHEMA_VERSION, write_episode     # noqa: E402
from farm.failure_class import classify, stealth                  # noqa: E402

LANE_DONE = re.compile(r"^\[[\d:]+Z\]\s+(lane\d+) done; lane \$([\d.]+)")
LANE_REPAIR = re.compile(r"^\[[\d:]+Z\]\s+repair (lane\d+)$")


def changed_lines(patch: Path) -> int:
    if not patch.exists():
        return 0
    return sum(1 for line in patch.read_text(errors="replace").splitlines()
               if line[:1] in ("+", "-") and not line.startswith(("+++", "---")))


def ledger_from_log(log: Path, episode: str, arm: str) -> list[dict]:
    """Per-lane billed cost, read back from what the run printed.

    The runner writes its ledger only at the end, with the record. The log is
    the only place the per-lane meter deltas survived a crash.
    """
    rows, inside = [], False
    for line in log.read_text(errors="replace").splitlines():
        if line.startswith("[") and "=== " in line:
            inside = f"=== {episode} " in line
            continue
        if not inside:
            continue
        m = LANE_DONE.match(line)
        if m:
            rows.append({"episode": episode, "arm": arm, "lane": m.group(1),
                         "phase": "initial", "lane_cost": float(m.group(2)),
                         "source": "recovered from the run log"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    ep = next(e for e in plan["episodes"] if e["id"] == args.episode)
    out = Path(args.data_root) / ep["id"]
    patches = out / "patches"

    tag = "after_repair" if (out / "results" / "after_repair_grade.json").exists() else "initial"
    graded = json.loads((out / "results" / f"{tag}_grade.json").read_text())
    alone = graded["alone"]
    merge_outcome = (graded["merge"] or {}).get("outcome")
    both_pass = (len(alone) == len(ep["lanes"])
                 and all(o == "pass" for o in alone.values()))
    failure_class, why = classify(merge_outcome, graded["merged"], both_pass)

    lanes = []
    for i, l in enumerate(ep["lanes"], start=1):
        res = out / f"{l['id']}_result.json"
        salvaged = False
        if res.exists():
            salvaged = bool(json.loads(res.read_text())["agent"].get("patch_salvaged"))
        lanes.append({
            "agent": l["id"], "model": plan["model"],
            "runtime": "cooperbench solo: own container, own branch, no mailbox, "
                       "no shared git remote"
                       + (" ; roomed brief from the claim map" if ep["arm"] == "roomed" else ""),
            "brief": l["brief"], "assumptions": [],
            "alone_suite": alone.get(l["id"]),
            "changed_lines": changed_lines(patches / f"{l['id']}.patch"),
            "salvaged": salvaged,
            "run_position": ep.get("run_position"),
            "lane_position": i,
        })

    ledger = ledger_from_log(Path(args.log), ep["id"], ep["arm"])
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": ep["id"], "split": "train",
        "corpus": {"name": plan["corpus"], "repo": plan["repo"],
                   "base_commit": plan["base_commit"], "language": "typescript",
                   "arm": ep["arm"]},
        "seam": {"kind": "same_repository_two_lanes",
                 "detail": "two lanes, own containers, own branches, no channel"},
        "lanes": lanes,
        "git_outcome": graded["merge"] or {"outcome": None,
                                           "why": "fewer than two lanes produced a patch"},
        "product_outcome": {"per_lane_alone": alone,
                            "merged_suite": graded["merged"],
                            "both_pass": both_pass,
                            "checks": "tsc --noEmit and vitest run"},
        "failure_class": failure_class,
        "failure_class_why": why,
        "stealth": stealth(failure_class, merge_outcome, both_pass),
        "claim": {"pairs": graded["claim_pairs"],
                  "room_used": ep["arm"] == "roomed",
                  "room_cfg": plan.get("room") if ep["arm"] == "roomed" else None,
                  "room": str(out / "room.md") if (out / "room.md").exists() else None},
        "convention_graders": graded["conventions"],
        "published_surface": {"published": None,
                              "why": "both lanes are inside one application; no "
                                     "package boundary is crossed"},
        "cost": {"usd": round(sum(e["lane_cost"] for e in ledger), 4),
                 "source": "provider meter deltas per lane, recovered from the run log",
                 "ledger": ledger,
                 "incomplete": "repair-lane costs are not in the log and are not "
                               "included; the episode billed more than this"},
        "prediction": {"frozen": plan["predictions"].get(f"{ep['arm']}_semantic")
                       or plan["predictions"].get(ep["arm"]),
                       "observed": {"both_pass": both_pass, "own_tests": alone,
                                    "failure_class": failure_class},
                       "correct": None, "source": args.plan},
        "patches": {l["id"]: str(patches / f"{l['id']}.patch")
                    for l in ep["lanes"] if (patches / f"{l['id']}.patch").exists()},
        "merge": {"dir": str(out / f"merge_{tag}"), "outcome": merge_outcome},
        "test_logs": {"dir": str(out / "results")},
        "checkpoints": {"dir": None,
                        "why": "solo runs keep no cross-agent checkpoint stream"},
        "recovered": {
            "why": "the runner raised while assembling this record, after the "
                   "episode was fully run and graded; nothing was re-run",
            "graded_from": f"{tag}_grade.json",
            "by": "scripts/recover_episode_record.py",
        },
    }
    print(f"wrote {write_episode(record)}")
    print(f"  class={failure_class} stealth={record['stealth']['flag']} "
          f"both_pass={both_pass} cost=${record['cost']['usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
