#!/usr/bin/env python3
"""Promote c06b-pair1-bare to CE-006: the first unseeded coordination episode.

Every earlier episode in the corpus was built. CE-001 through CE-003 were
seeded pairs in a constructed sandbox; CE-004 was a provider and a consumer
chosen because a symbol crossed a published boundary; CE-005 was a textual
conflict on a field run. CE-006 is the first one nobody arranged: two ordinary
briefs on one application, two agents who could not see each other, and a
failure that git merged without comment.

Its roomed twin is recorded as the matched control -- the same two briefs, the
same model, the same sandbox, differing only in the room -- with the limits of
that comparison stated rather than implied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.episode_record import SCHEMA_VERSION, write_episode   # noqa: E402
from farm.failure_class import classify                        # noqa: E402

EP = REPO_ROOT / "farm" / "episodes"
RUN = Path("/home/user/farm-c06b")


def main() -> int:
    src = json.loads((EP / "c06b-pair1-bare.json").read_text())
    ctl = json.loads((EP / "c06b-pair1-roomed.json").read_text())

    lanes = {l["agent"]: l for l in src["lanes"]}
    lanes["lane1"]["assumptions"] = [
        "that repairing every call site it could see was enough -- it updated "
        "prisma/seed.ts, src/pages/index.tsx and its own tests, and every one "
        "of them was inside its own branch",
        "that adding a required field to post.add's input was a safe extension, "
        "because nothing on its branch called post.add without one",
    ]
    lanes["lane2"]["assumptions"] = [
        "that post.add's input contract was stable -- it read the procedure on "
        "its own branch, where title and text are the only required fields",
        "that adding test cases to post.test.ts touched nothing anyone else "
        "would be editing",
    ]

    record = {
        "schema_version": SCHEMA_VERSION,
        "id": "CE-006",
        "split": "gold",
        "corpus": {**src["corpus"], "unseeded": True,
                   "note": "no planted contract, no chosen symbol; two ordinary "
                           "feature briefs on one application"},
        "seam": {
            "kind": "same_repository_two_lanes",
            "detail": "one application, two lanes in their own containers on "
                      "their own branches, no channel. The seam is a module "
                      "boundary inside a repository, not a package boundary.",
        },
        "lanes": [lanes["lane1"], lanes["lane2"]],
        "git_outcome": src["git_outcome"],
        "product_outcome": src["product_outcome"],
        "failure_class": "semantic",
        # The source record predates the rule being wired into the runner, so
        # the reason is recomputed here from the same three inputs rather than
        # copied from a key that will not be there.
        "failure_class_why": classify(
            src["git_outcome"]["outcome"],
            src["product_outcome"]["merged_suite"],
            src["product_outcome"]["both_pass"])[1],
        "stealth": {
            **src["stealth"],
            "detail": "lane1's branch is green on tsc --noEmit and vitest run; "
                      "lane2's branch is green on both; git merges without a "
                      "conflict. Nothing either agent could run would have "
                      "reported this.",
        },
        "claim": {
            "chain": ["post.test.ts::caller.post.add",
                      "postRouter.add.input",
                      "z.object{authorId: z.string()}"],
            "anchor": "src/server/routers/post.ts:143",
            "consumers": ["src/server/routers/post.test.ts:35",
                          "src/server/routers/post.test.ts:40",
                          "src/server/routers/post.test.ts:45"],
            "direction": "lane1 provides, lane2 consumes",
            "diff_only_verdict": "textual",
            "diff_only_note": "the diff classifier called this pair textual -- "
                              "both patches touch post.test.ts and post.ts -- "
                              "and git merged it anyway. The same shape as the "
                              "65 textual-but-clean pairs in "
                              "farm/census/manifest.jsonl.",
            "pairs": src["claim"]["pairs"],
            "room_used": False,
            "room": None,
        },
        "convention_graders": src["convention_graders"],
        "published_surface": {
            "published": None,
            "why": "not applicable: both lanes are inside one application and no "
                   "package boundary is crossed.",
            "refines_the_rule": (
                "CE-004 gave the rule that a coordination failure crosses a "
                "package boundary only when the changed contract is on the "
                "published surface, because a provider agent repairs its own "
                "call sites and publication is what puts a call site out of its "
                "reach. CE-006 is the same mechanism with no package anywhere: "
                "lane1 repaired every call site it could see, and the ones it "
                "could not see were in another agent's container. Publication is "
                "one way a call site becomes invisible to the provider. A second "
                "agent working without a channel is another, and it needs no "
                "package boundary at all."
            ),
        },
        "cost": src["cost"],
        "prediction": {
            "frozen": ctl["prediction"]["frozen"],
            "observed": "a semantic failure, stealthy, in the bare arm",
            "correct": False,
            "note": "not predicted. c06b's frozen predictions were about pass "
                    "rates, cost and merge outcome, and they explicitly expected "
                    "a textual conflict in every episode where both lanes "
                    "landed. Three of six merged cleanly and this one broke.",
            "source": "config/c06b_rerun.json",
        },
        "patches": {
            "lane1": "farm/episodes/artifacts/CE-006/patches/lane1.patch",
            "lane2": "farm/episodes/artifacts/CE-006/patches/lane2.patch",
            "run_dir": str(RUN / "c06b-pair1-bare" / "patches"),
        },
        "merge": {
            "dir": str(RUN / "c06b-pair1-bare" / "merge_initial"),
            "outcome": "clean",
            "why": "lane1 changed post.ts and its own regions of post.test.ts; "
                   "lane2 added new cases elsewhere in post.test.ts. No "
                   "overlapping hunks.",
        },
        "test_logs": {
            "dir": "farm/episodes/artifacts/CE-006/results",
            "run_dir": str(RUN / "c06b-pair1-bare" / "results"),
            "merged_failure": "ZodError: expected string, received undefined at "
                              "authorId, raised from post.test.ts:35 through "
                              "@trpc/server's inputValidatorMiddleware",
        },
        "checkpoints": {"dir": None,
                        "why": "solo runs keep no cross-agent checkpoint stream"},
        "caveats": [
            "lane1 never ran a git command. It worked 79 steps, wrote a summary "
            "and exited Submitted; its 242 changed lines were taken from the "
            "container's working tree by the solo capture fallback added the "
            "same day. Under the previous harness this episode does not exist.",
            "that capture used `git add -A`, which swept a scratch file, "
            "test_author_posts.ts, into lane1's patch. It is at the repository "
            "root, it is not imported by anything, and tsc --noEmit is clean "
            "with it present.",
            "n = 1. Not reproduced. c07 repeats these exact two briefs to find "
            "out whether it recurs.",
        ],
        "matched_control": {
            "kind": "arm-matched twin",
            "id": "c06b-pair1-roomed",
            "differs_in": "the roomed brief, built from the claim map; "
                          "everything else is identical -- same two briefs, "
                          "same model, same image, same sandbox rules, no "
                          "channel",
            "observed": {
                "merge": "conflict",
                "conflicted_paths": ["src/server/routers/post.test.ts"],
                "per_lane_alone": ctl["product_outcome"]["per_lane_alone"],
                "failure_class": ctl["failure_class"],
            },
            "what_it_does_not_show": (
                "It does not show that the room prevents the failure. The roomed "
                "twin conflicted textually, so the merge never got far enough "
                "for a semantic failure to be possible; a different outcome is "
                "not a prevented one. At n = 1 per arm this control bounds "
                "nothing, and it is recorded because the run design paired the "
                "two, not because the pair settles anything."
            ),
            "cost_usd": ctl["cost"]["usd"],
            "record": "farm/episodes/c06b-pair1-roomed.json",
        },
        "report": "reports/c06b_rerun_fixed_harness.md",
        "supersedes": None,
        "source_episode": "c06b-pair1-bare",
    }
    path = write_episode(record)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
