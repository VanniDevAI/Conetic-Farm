#!/usr/bin/env python3
"""Write CE-001..CE-004 as durable episode records.

The four episodes existed only as prose and as four differently-shaped artifact
trees. This reads each tree for the numbers it can -- labels, merge outcomes,
costs, grading results -- and supplies from the transcripts only what is not in
a file, which is the agents' stated assumptions. Everything it asserts is either
read from an artifact or quoted, and each record carries the paths it came from
so a reader can check it.

All four are written `split=gold`: they have been read and verified by a human.
Step B writes `split=train`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.episode_record import SCHEMA_VERSION, write_episode   # noqa: E402

S01 = Path("/home/user/farm-sweep-s01/qwen3-coder/episodes/"
           "react_hook_form_task__task153__f1_f2__ae72500f/attempts/attempt-001")
S04 = Path("/home/user/farm-seed-s04")
C05A = Path("/home/user/farm-c05a")


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def ce001() -> dict:
    cls = read(S01 / "results" / "classification.json")
    cost = read(S01 / "cost.json")
    merge = cls["evidence"]["merge"]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "CE-001",
        "split": "gold",
        "corpus": {
            "name": "cooperbench/react_hook_form_task",
            "task": "task153",
            "base_commit": "cec3267e12aaee01b6a17b657f9297021defdc50",
            "language": "typescript",
        },
        "seam": {
            "kind": "none",
            "detail": "both lanes edit one file in one repository; there is no "
                      "boundary of any kind between them",
        },
        "lanes": [
            {"agent": "A", "model": "openrouter/qwen/qwen3-coder",
             "runtime": "cooperbench coop, shared repository, message channel available",
             "brief": "dataset/react_hook_form_task/task153/feature1/feature.md "
                      "-- leave formState flags consistent when onValid throws",
             "assumptions": ["owns the submission path in createFormControl.ts"]},
            {"agent": "B", "model": "openrouter/qwen/qwen3-coder",
             "runtime": "cooperbench coop, shared repository, message channel available",
             "brief": "dataset/react_hook_form_task/task153/feature2/feature.md "
                      "-- add an onFinally callback to handleSubmit",
             "assumptions": ["owns the submission path in createFormControl.ts"]},
        ],
        "git_outcome": {
            "outcome": merge["outcome"],
            "conflicted_paths": merge["conflicted_paths"],
            "note": "A's hunk starts at createFormControl.ts:1122; B's cover "
                    "1097, 1118 and 1131",
        },
        "product_outcome": {
            "a_alone_own": cls["evidence"]["a"]["own_tests"],
            "b_alone_own": cls["evidence"]["b"]["own_tests"],
            "merged_a": merge["a_tests"],
            "merged_b": merge["b_tests"],
            "note": "the merge refused, so no combined tree was ever tested",
        },
        "failure_class": "textual",
        "stealth": {
            "flag": None,
            "why": "not applicable: git refused the merge, so nothing reached a "
                   "state where a test suite could have been the last line of defence",
        },
        "claim": {
            "chain": None, "anchor": None,
            "why": "not required -- the two patches overlap textually and no "
                   "claim map is needed to see it",
        },
        "convention_graders": {"migration_ordinals": [], "route_paths": [],
                               "config_keys": [],
                               "note": "the graders did not exist when this ran"},
        "published_surface": {"published": None,
                              "why": "the collision is inside one file, not across a contract"},
        "cost": {"usd": cost["episode_cost_usd"], "source": "provider meter delta",
                 "path": str(S01 / "cost.json")},
        "prediction": {
            "frozen": "arm-level only: docs/SWEEP_S01_PREDICTIONS.md predicted p "
                      "and both-pass rates per model, not an outcome for this episode",
            "observed": "integration_failure_merge (textual)",
            "correct": None,
            "source": "docs/SWEEP_S01_PREDICTIONS.md",
        },
        "patches": {"A": str(S01 / "patches" / "agent_A.patch"),
                    "B": str(S01 / "patches" / "agent_B.patch")},
        "merge": {"dir": str(S01 / "merge"), "outcome": merge["outcome"]},
        "test_logs": {"dir": str(S01 / "results")},
        "checkpoints": {"dir": str(S01 / "checkpoints_raw")},
        "matched_control": None,
        "report": "reports/sweep_s01.md",
    }


def _s04(pair_id: str, ce: str, corpus: dict, seam_detail: str,
         lanes: list, claim_chain, anchor, published, cost_usd: float,
         null_id: str, null_cost: float) -> dict:
    res = read(S04 / pair_id / "pair_result.json")
    ev = res["graded"]["classification"]["evidence"]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": ce,
        "split": "gold",
        "corpus": corpus,
        "seam": {"kind": "constructed", "detail": seam_detail},
        "lanes": lanes,
        "git_outcome": {"outcome": ev["merge"]["outcome"],
                        "conflicted_paths": ev["merge"]["conflicted_paths"],
                        "note": "the two patches touch different files"},
        "product_outcome": {
            "a_alone_own": ev["a"]["own_tests"], "b_alone_own": ev["b"]["own_tests"],
            "merged_a": ev["merge"]["a_tests"], "merged_b": ev["merge"]["b_tests"],
        },
        "failure_class": res["graded"]["failure_class"],
        "stealth": {
            "flag": False,
            "why": "under the gold patches the provider's own full suite is red "
                   "(query-core 7 of 683, zod 4 of 5366), so the change was "
                   "catchable on the provider's branch; the agents' own patches "
                   "were not measured against the full suite in s04",
            "measured": False,
        },
        "claim": {"chain": claim_chain, "anchor": anchor,
                  "diff_only_verdict": res["claim_map"]["diff_only_class"]},
        "convention_graders": {"migration_ordinals": [], "route_paths": [],
                               "config_keys": [],
                               "note": "the graders did not exist when this ran"},
        "published_surface": published,
        "cost": {"usd": cost_usd, "source": "provider meter delta, per-lane ledger",
                 "path": str(S04 / pair_id / "pair_result.json")},
        "prediction": {
            "frozen": "config/seed_s04.json stated the expected outcome for the "
                      "pair shape but did not freeze a per-episode verdict",
            "observed": res["graded"]["classification"]["label"],
            "correct": None,
            "source": "config/seed_s04.json",
        },
        "patches": {"A": str(S04 / pair_id / "patches" / "agent_A.patch"),
                    "B": str(S04 / pair_id / "patches" / "agent_B.patch")},
        "merge": {"dir": str(S04 / pair_id / "merge"), "outcome": ev["merge"]["outcome"]},
        "test_logs": {"dir": str(S04 / pair_id / "results")},
        "checkpoints": {"dir": None,
                        "why": "solo runs keep no cross-agent checkpoint stream; "
                               "each lane's trajectory is its record"},
        "matched_control": {
            "kind": "matched null",
            "id": null_id,
            "runtime": "cooperbench coop: message channel and shared team git remote",
            "observed": "both_pass_merge_passes",
            "cost_usd": null_cost,
            "path": f"/home/user/farm-seed-s03/{null_id}/attempts/attempt-002",
        },
        "report": "reports/step3_isolated_pairs_and_resolved_census.md",
    }


def ce002() -> dict:
    return _s04(
        "tanstack_query_task__task1__f1_f2__s04", "CE-002",
        {"name": "cooperbench/tanstack_query_task", "task": "task1",
         "base_commit": "50680b98c4dc5ac4d97f7762014fa83f09a41d9a",
         "language": "typescript"},
        "module granularity, enforced by the image: the consumer and its 201 "
        "runtime dependents were removed from lane A's disk, and the provider "
        "was bind-mounted read-only for lane B",
        [
            {"agent": "A", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; trimmed image",
             "brief": "dataset/seeded/tanstack_query_task/task1/feature1/feature.md "
                      "-- timeUntilStale returns signed time",
             "assumptions": [
                 "\"Now let's check callers to see if any rely on the clamped behavior.\"",
                 "\"No other callers currently.\" -- true of its disk, false of the repository"]},
            {"agent": "B", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; full image, "
                        "provider mounted read-only",
             "brief": "dataset/seeded/tanstack_query_task/task1/feature2/feature.md "
                      "-- add Query#getStalenessReport",
             "assumptions": [
                 "isStaleByTime keeps answering the same question; the brief asked "
                 "it to reuse the query's own staleness determination"]},
        ],
        ["isStaleByTime", "timeUntilStale"],
        "packages/query-core/src/utils.ts:136",
        {"published": False, "symbol": "timeUntilStale", "how": None,
         "entries": ["packages/query-core/src/index.ts"]},
        0.1057, "tanstack_query_task__task1__f1_f2__seed03a", 2.5662)


def ce003() -> dict:
    return _s04(
        "zod_task__task1__f1_f2__s04", "CE-003",
        {"name": "cooperbench/zod_task", "task": "task1",
         "base_commit": "eb1c1089f7f9469078839f6e443830f7e3fdc06b",
         "language": "typescript"},
        "module granularity, enforced by the image: the consumer and its 275 "
        "runtime dependents were removed from lane A's disk, and the provider "
        "was bind-mounted read-only for lane B",
        [
            {"agent": "A", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; trimmed image",
             "brief": "dataset/seeded/zod_task/task1/feature1/feature.md "
                      "-- floatSafeRemainder returns the raw difference",
             "assumptions": [
                 "\"grep confirmed only definition, no usages elsewhere - but let's "
                 "double check where it's used, maybe imported elsewhere with "
                 "different name or via util namespace\"",
                 "checked twice; both greps returned only the definition"]},
            {"agent": "B", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; full image, "
                        "provider mounted read-only",
             "brief": "dataset/seeded/zod_task/task1/feature2/feature.md "
                      "-- add a remainder field to the not_multiple_of issue",
             "assumptions": [
                 "floatSafeRemainder(...) === 0 still means \"is a multiple\"; it "
                 "never touched that line, which the check has always had"]},
        ],
        ["$ZodCheckMultipleOf", "floatSafeRemainder"],
        "packages/zod/src/v4/core/util.ts:327",
        {"published": True, "symbol": "floatSafeRemainder", "how": "namespace util",
         "entries": ["packages/zod/src/v4/core/index.ts"]},
        1.8189, "zod_task__task1__f1_f2__seed03b", 4.1057)


def ce004() -> dict:
    res = read(C05A / "zod_seam__floatSafeRemainder" / "pair_result.json")
    ctl = read(C05A / "qc_seam__timeUntilStale" / "pair_result.json")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "CE-004",
        "split": "gold",
        "corpus": {
            "name": "zod -> zod-multipleof-hints",
            "provider": {"repo": "colinhacks/zod",
                         "base_commit": "eb1c1089f7f9469078839f6e443830f7e3fdc06b"},
            "consumer": {"repo": "dataset/seeded/seam/zod_multipleof_hints",
                         "depends_on": "zod@4.5.4 from the npm registry"},
            "language": "typescript",
        },
        "seam": {
            "kind": "published_package",
            "detail": "two repositories; the consumer installs the provider from "
                      "the registry at the provider's base-commit version. No file "
                      "removed, no path mounted, no leak check.",
        },
        "lanes": [
            {"agent": "A", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; provider "
                        "repository whole and unmodified",
             "brief": "dataset/seeded/zod_task/task1/feature1/feature.md",
             "assumptions": [
                 "repairing its own callers is enough -- it repaired both, "
                 "core/checks.ts and core/compile.ts, unprompted",
                 "zod's public multipleOf behaviour is therefore unchanged and "
                 "zod's own full suite is green"]},
            {"agent": "B", "model": "openrouter/anthropic/claude-sonnet-5",
             "runtime": "solo, own container, own branch, no channel; consumer "
                        "repository with the provider from the registry",
             "brief": "dataset/seeded/seam/zod_multipleof_hints/feature/feature.md",
             "assumptions": [
                 "core.util.floatSafeRemainder(...) === 0 still means \"is a multiple\"",
                 "uses zod's own helper deliberately so a form hint and the schema "
                 "validating the same field cannot disagree"]},
        ],
        "git_outcome": {
            "outcome": res["merge"]["outcome"],
            "conflicted_paths": res["merge"]["conflicted_paths"],
            "note": res["merge"]["why"],
            "structural": True,
        },
        "product_outcome": {
            "a_alone_own": res["a_alone"], "b_alone_own": res["b_alone"],
            "integrated": res["integrated"],
            "note": "integrated = consumer's graded tests with the provider "
                    "rebuilt from lane A's patch, packed, and installed over "
                    "the registry copy",
        },
        "failure_class": res["failure_class"],
        "stealth": {
            "flag": res["stealthy"],
            "measured": True,
            "why": "lane A's patch leaves the provider repository's own full "
                   "suite green, and lane B's branch is green against the "
                   "published provider; neither branch's CI reports anything",
            "a_full_suite": res["a_full_suite"],
        },
        "claim": {
            "chain": ["hints.ts::isMultipleOf", "core.util.floatSafeRemainder"],
            "anchor": "packages/zod/src/v4/core/util.ts:327",
            "diff_only_verdict": "independent",
        },
        "convention_graders": {"migration_ordinals": [], "route_paths": [],
                               "config_keys": [],
                               "note": "no migration, route or config surface in "
                                       "either repository"},
        "published_surface": {"published": True, "symbol": "floatSafeRemainder",
                              "how": "namespace util",
                              "entries": ["packages/zod/src/v4/core/index.ts"]},
        "cost": {"usd": 1.3143, "source": "provider meter delta, per-lane ledger",
                 "path": str(C05A / "zod_seam__floatSafeRemainder" / "pair_result.json")},
        "prediction": {
            "frozen": res["pair"]["prediction"] + " -- " + res["pair"]["why"],
            "observed": "fires, semantic, stealthy",
            "correct": True,
            "source": "config/c05_step_a.json",
        },
        "patches": {
            "A": str(C05A / "zod_seam__floatSafeRemainder" / "patches_provider" / "agent_A.patch"),
            "B": str(C05A / "zod_seam__floatSafeRemainder" / "patches_consumer" / "agent_B.patch"),
        },
        "merge": {"dir": None, "outcome": "clean",
                  "why": res["merge"]["why"]},
        "test_logs": {"dir": str(C05A / "zod_seam__floatSafeRemainder" / "results")},
        "checkpoints": {"dir": None,
                        "why": "solo runs keep no cross-agent checkpoint stream"},
        "matched_control": {
            "kind": "control",
            "id": "qc_seam__timeUntilStale",
            "corpus": "@tanstack/query-core@5.102.8 -> qc-staleness-panel",
            "differs_in": "the contract lane A changed is not exported",
            "observed": {"a_alone": ctl["a_alone"], "b_alone": ctl["b_alone"],
                         "integrated": ctl["integrated"],
                         "a_full_suite": ctl["a_full_suite"]},
            "failure_class": ctl["failure_class"],
            "published_surface": {"published": False, "symbol": "timeUntilStale"},
            "prediction": {"frozen": ctl["pair"]["prediction"],
                           "observed": "null", "correct": True},
            "cost_usd": 0.4482,
            "path": str(C05A / "qc_seam__timeUntilStale" / "pair_result.json"),
        },
        "report": "reports/c05_step_a_seam.md",
    }


def main() -> int:
    for build in (ce001, ce002, ce003, ce004):
        record = build()
        path = write_episode(record)
        print(f"wrote {path.relative_to(REPO_ROOT)}  "
              f"class={record['failure_class']} split={record['split']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
