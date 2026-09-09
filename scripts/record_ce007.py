#!/usr/bin/env python3
"""Promote c07-ep05-roomed to CE-007: the same class, a different bug shape.

CE-006 was a contract. One lane tightened `post.add`'s input, another wrote
call sites against the old shape, and the merged tree raised a validation
error. CE-007 merges just as cleanly, is just as stealthy, and breaks for a
reason no contract analysis reaches: the two lanes' test files run in parallel
vitest workers against one sqlite file, and one lane's `beforeEach` wipes the
other's fixtures.

`split=observed`, not gold. It happened and it is recorded faithfully, and it
is a race -- one of the affected lane's two tests failed and the other passed
in the same run -- so it must not be counted as a settled result.

Its matched control is `c07-ep03-bare`: the run's only other clean merge, whose
combined tree passed. Same task, same briefs, same model, the other arm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.episode_record import SCHEMA_VERSION, write_episode   # noqa: E402

EP = REPO_ROOT / "farm" / "episodes"
RUN = Path("/home/user/farm-c07")


def main() -> int:
    src = json.loads((EP / "c07-ep05-roomed.json").read_text())
    ctl = json.loads((EP / "c07-ep03-bare.json").read_text())
    lanes = {l["agent"]: l for l in src["lanes"]}
    lanes["lane1"]["assumptions"] = [
        "that its own test fixtures would still be in the database when its "
        "own assertions ran -- true on its branch, where nothing else writes",
        "that adding a procedure and a test file touched nothing another lane "
        "would be touching",
    ]
    lanes["lane2"]["assumptions"] = [
        "that wiping the posts table before each of its tests was a local "
        "matter -- `beforeEach(prisma.post.deleteMany({}))` is ordinary "
        "hygiene when yours is the only test file that writes",
        "that a new procedure and a new test file were additive",
    ]

    record = {
        "schema_version": SCHEMA_VERSION,
        "id": "CE-007",
        "split": "observed",
        "split_why": (
            "not gold: the failure is a race. Of the affected lane's two "
            "author tests one failed and one passed in the same run, so this "
            "is one observation of an intermittent break, not a settled "
            "result. It is recorded because it happened and because its "
            "mechanism is one the corpus had not produced before."
        ),
        "corpus": {**src["corpus"], "unseeded": True},
        "seam": {
            "kind": "same_repository_two_lanes",
            "detail": "one application, two lanes in their own containers on "
                      "their own branches, no channel. The seam is a shared "
                      "test database, not a module boundary.",
        },
        "lanes": [lanes["lane1"], lanes["lane2"]],
        "git_outcome": src["git_outcome"],
        "product_outcome": src["product_outcome"],
        "failure_class": "semantic",
        "failure_class_why": src["failure_class_why"],
        "stealth": {**src["stealth"],
                    "detail": "both branches green on tsc --noEmit and vitest "
                              "run, merge clean, combined tree red. Nothing "
                              "either agent could run would have reported it."},
        "claim": {
            **src["claim"],
            "chain": ["postRouter", "defaultPostSelect"],
            "chain_note": "what the claim map emitted, and it is not the mechanism",
            "anchor": None,
        },
        "mechanism_named_by_claim_map": src["mechanism_named_by_claim_map"],
        "convention_graders": src["convention_graders"],
        "published_surface": {
            "published": None,
            "why": "not applicable: both lanes are inside one application and "
                   "no package boundary is crossed",
            "note": (
                "CE-004 gave the rule that publication puts a call site beyond "
                "the provider's reach, and CE-006 showed concurrency does the "
                "same without a package. CE-007 is a third way: the shared "
                "thing is not a call site at all. Neither lane called the "
                "other's code. They shared a mutable resource that neither "
                "brief mentions and no import graph contains."
            ),
        },
        "cost": src["cost"],
        "prediction": {
            "frozen": src["prediction"]["frozen"],
            "observed": "one semantic failure in five roomed episodes; bare "
                        "shipped none. Fisher two-sided p = 1.000.",
            "correct": True,
            "note": "the frozen prediction was that the roomed arm would not "
                    "ship fewer than bare, because the room is generated from "
                    "the base tree and cannot describe what the other lane is "
                    "doing concurrently. It shipped one and bare shipped none.",
            "source": "config/c07_semantic_rate.json",
        },
        "patches": {
            "lane1": "farm/episodes/artifacts/CE-007/patches/lane1.patch",
            "lane2": "farm/episodes/artifacts/CE-007/patches/lane2.patch",
            "run_dir": str(RUN / "c07-ep05-roomed" / "patches"),
        },
        "merge": {"dir": "farm/episodes/artifacts/CE-007/merge",
                  "outcome": "clean",
                  "why": "lane1 added byAuthor and a migration; lane2 added an "
                         "archive procedure and its own test file. No "
                         "overlapping hunks."},
        "test_logs": {
            "dir": "farm/episodes/artifacts/CE-007/results",
            "run_dir": str(RUN / "c07-ep05-roomed" / "results"),
            "merged_failure": "AssertionError: expected [] to have a length of "
                              "2 but got +0, at post.test.ts:64 in "
                              "'get posts by author'",
        },
        "checkpoints": {"dir": None,
                        "why": "solo runs keep no cross-agent checkpoint stream"},
        "repair": {**src.get("repair", {}),
                   "verdict": "the engine flagged the correct symptom -- the "
                              "branches merge cleanly and the combined tree "
                              "fails -- the roomed repair round ran, and the "
                              "merged tree failed identically afterwards."},
        "caveats": [
            "It is a race. vitest.config.ts sets no fileParallelism, so test "
            "files run in parallel workers, and .env points every one at "
            "file:/workspace/repo/prisma/dev.db. Timing decides the outcome.",
            "Any future semantic failure on this repository has to be checked "
            "against the shared database before being called a contract "
            "failure. CE-007 needed that check; CE-006 passed it.",
            "n = 1, not reproduced.",
        ],
        "matched_control": {
            "kind": "the run's other clean merge",
            "id": "c07-ep03-bare",
            "differs_in": "the arm, and nothing else -- same task, same two "
                          "briefs, same model, same sandbox",
            "observed": {
                "merge": (ctl["git_outcome"] or {}).get("outcome"),
                "merged_suite": ctl["product_outcome"]["merged_suite"],
                "per_lane_alone": ctl["product_outcome"]["per_lane_alone"],
                "failure_class": ctl["failure_class"],
            },
            "why_it_is_the_control": (
                "Ten episodes produced exactly two clean merges. A clean merge "
                "is the only state in which a semantic failure is possible, so "
                "the informative comparison is not roomed-against-bare but "
                "this clean merge against the other one: two lanes merged "
                "cleanly and the product was right, two lanes merged cleanly "
                "and it was wrong."
            ),
            "cost_usd": ctl["cost"]["usd"],
            "record": "farm/episodes/c07-ep03-bare.json",
        },
        "report": "reports/c07_semantic_rate.md",
        "source_episode": "c07-ep05-roomed",
    }
    print(f"wrote {write_episode(record)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
