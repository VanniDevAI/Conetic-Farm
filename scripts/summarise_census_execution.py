#!/usr/bin/env python3
"""The execution pass, counted, and set against what the static pass predicted."""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execution", default=str(REPO_ROOT / "farm" / "census" / "execution.jsonl"))
    ap.add_argument("--grade", default=str(REPO_ROOT / "farm" / "census" / "claim_grade.jsonl"))
    ap.add_argument("--out", default=str(REPO_ROOT / "farm" / "census" / "execution_summary.json"))
    args = ap.parse_args()

    ex = [json.loads(l) for l in Path(args.execution).read_text().splitlines() if l.strip()]
    cg = [json.loads(l) for l in Path(args.grade).read_text().splitlines() if l.strip()]
    key = lambda r: (r["repo"], r["task"], tuple(r["features"]))

    def tr(r, side, hops):
        return r["combined"]["tests_reach"][str(side)][str(hops)]

    strict = {key(r) for r in cg
              if r["chain_1"]["direction"] and all(tr(r, f, 1) for f in r["features"])}
    scored = [r for r in ex if r.get("combined")]
    scored_keys = {key(r) for r in scored}
    semantic = [r for r in scored if r.get("verdict") == "semantic"]

    reasons = collections.Counter(r.get("why") for r in ex if r.get("verdict") is None)
    summary = {
        "generated": "2026-09-10",
        "prediction": "config/census_execution_grade.json",
        "corpus": {"merge_clean_pairs": len(cg), "executed": len(ex),
                   "not_executed": len(cg) - len(ex)},
        "by_repo": {
            "executed": dict(collections.Counter(r["repo"] for r in ex)),
            "scored": dict(collections.Counter(r["repo"] for r in scored)),
        },
        "toolchain_chosen": dict(collections.Counter(
            str(r.get("toolchain")) for r in ex)),
        "outcomes": {
            "fully_scored": len(scored),
            "semantic_failures": len(semantic),
            "combined_tree": dict(collections.Counter(
                r["combined"]["outcome"] for r in scored)),
            "every_lane_green": dict(collections.Counter(
                str(r.get("every_lane_green")) for r in scored)),
        },
        "not_scored_reasons": {str(k): v for k, v in reasons.most_common()},
        "head_sha_reproduced": dict(collections.Counter(
            str(r.get("head_sha_reproduced")) for r in ex if "head_sha_reproduced" in r)),
        "against_the_static_pass": {
            "ce006_shaped_statically": len(strict),
            "of_those_fully_scored": len(strict & scored_keys),
            "of_those_a_semantic_failure": sum(1 for r in semantic if key(r) in strict),
        },
        "semantic_pairs": [
            {"repo": r["repo"], "task": r["task"], "features": r["features"],
             "toolchain": r.get("toolchain"),
             "tests_patches_applied": r.get("tests_patches_applied")}
            for r in semantic],
        "not_claimed": [
            "A merged tree that passes is not a safe pair. It means the tests "
            "present did not catch anything.",
            "A pair that could not be scored is not evidence either way.",
        ],
    }
    Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
