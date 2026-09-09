# Campaign `c02` — report

Generated 2026-09-09T01:42:08.517529Z from `/home/user/farm-data-c02/manifest.json`. Labels are read from the corpus, never recomputed.

## Headline

| | |
|---|---:|
| Episodes attempted | 20 |
| …of which harness errors (no measurement) | 4 |
| **Episodes that produced a measurement** | **16** |
| **…of which retained BOTH patches** | **5** |
| Total cost | $11.11 |
| Cost per episode (mean) | $0.556 |
| Cost per episode (median) | $0.416 |
| Cost per episode (max) | $1.619 |
| **Genuine integration failures** | **0** |
| Cost per verified integration failure | undefined (none found) |
| Ledger settled total | $11.11 |

## Expected versus actual

Frozen prediction (`docs/EXPECTATIONS.md`, written before any run): **2** genuine integration failures from the first 20 episodes, 80% interval 0–5.

Actual: **0**.

**Against the right denominator.** The prediction is stated for 20 episodes. This campaign produced a measurement in **16** of them, and only **5** retained a patch from both agents. A genuine integration failure is impossible without both, so the effective sample is 5, not 20. Zero found in 5 episodes neither confirms nor refutes a prediction made for 20.

Difference: -2 against a point estimate of 2. Within the frozen 80% interval.

## Integration failures by class

A genuine integration failure comes in two kinds, and they are different phenomena:

| Class | Count | What it means |
|---|---:|---|
| **textual** | 0 | the three-way merge refused — two patches touched overlapping lines. `git merge` surfaces this on its own, and the combined tests never run. |
| **semantic** | 0 | the merge was clean and the *combined* tests failed — textually compatible, behaviourally incompatible. No merge tool can see it. |
| total | 0 | |

**Semantic is the class a claim map is built to catch.** A textual conflict is already visible to any merge tool, so finding one is not evidence that reconciling claims before the merge would have helped. A semantic failure is invisible until the combined tests run, and that is the gap it closes.

## Gradeability, and the pass rate `p`

`p` -- the share of patches that pass their own tests alone -- is the quantity this design turns on: a genuine integration failure needs both patches to pass first, so the reachable rate scales with `p`&sup2;. It is a ratio of *graded* patches, and not every patch gets graded: an agent that edits the test file grading it makes the dataset's test patch unappliable, so the grader never runs and the patch is shown nothing either way.

| | |
|---|---:|
| Patches with content | 21 |
| **…graded** | **18** |
| …ungradeable (agent edited its own grading test) | 3 |
| …that passed alone | 7 |
| **`p` over graded patches** | **0.389** |
| `p` counting ungradeable as failures | 0.333 |
| implied `p`&sup2; | 0.151 |

Both figures are given. The classifier's labels use the second — an unrunnable patch is not a passing one — but the first is what the evidence supports, and reporting only one of them would be a choice about which number flatters.

## Eligibility, integration failures, and conflicts

An episode is *eligible* when it retained a non-empty patch from both agents; only an eligible episode can show a genuine integration failure. Conflicted paths are classified from the corpus: **source** if the patch modifies a file that existed at the task base, **scratch** if either agent's patch introduces the path as a new file (Appendix B.2).

| | |
|---|---:|
| **Eligible episodes** (both patches retained) | **5** |
| **Genuine integration failures** | **0** |
| Merge conflicts among eligible episodes | 2 |
| …touching at least one real source file | 2 |
| …confined to agent scratch files | 0 |
| Spend as settled in the ledger | $11.11 |
| **Cost per eligible episode** | **$2.22** |

| Episode | Stratum | Label | Merge | Conflicted paths |
|---|---|---|---|---|
| `dottxt_ai_outlines_task__task1655__f1_f8__36b79d53` | compatible | `both_broken` | clean | — |
| `pallets_jinja_task__task1621__f2_f3__530ffd11` | control | `b_broken` | clean | — |
| `pallets_jinja_task__task1621__f3_f5__639b8b7f` | control | `b_broken` | clean | — |
| `react_hook_form_task__task153__f2_f5__c7c7d41f` | conflicting | `a_broken` | conflict | `src/logic/createFormControl.ts` (source) |
| `typst_task__task6554__f1_f7__d4a98a24` | conflicting | `b_broken` | conflict | `crates/typst/src/foundations/str.rs` (source) |

## Outcome breakdown

| Label | Count | Meaning |
|---|---:|---|
| `no_patch_b` | 6 | agent B produced nothing |
| `no_patch_a` | 5 | agent A produced nothing |
| `harness_error` | 4 | infrastructure fault (excluded from rates) |
| `b_broken` | 3 | individually broken patch (B) |
| `both_broken` | 1 | individually broken patches (both) |
| `a_broken` | 1 | individually broken patch (A) |

Individually broken patches: **5** — these are *not* integration failures, whatever the merge did.
Episodes with a missing patch: **11**.
Harness errors excluded from rates: **4** (of 20); rates below are over 16 episodes.

## By stratum

| Stratum | Episodes | Genuine integration failures | Rate |
|---|---:|---:|---:|
| conflicting | 9 | 0 | 0% |
| compatible | 3 | 0 | 0% |
| control | 4 | 0 | 0% |

## By language

| Language | Episodes | Genuine integration failures |
|---|---:|---:|
| python | 11 | 0 |
| rust | 1 | 0 |
| typescript | 4 | 0 |

Language counts are descriptive. The plan was not designed to support attributing a difference to language.

## Manifest of episode folders

| # | Episode | Stratum | Lang | Label | Attempts | Cost | Directory |
|---:|---|---|---|---|---:|---:|---|
| 1 | `dottxt_ai_outlines_task__task1655__f1_f8__36b79d53` | compatible | python | `both_broken` | 1 | $0.349 | `/home/user/farm-data-c02/episodes/dottxt_ai_outlines_task__task1655__f1_f8__36b79d53` |
| 2 | `dottxt_ai_outlines_task__task1655__f1_f9__481926cf` | compatible | python | `no_patch_a` | 1 | $0.222 | `/home/user/farm-data-c02/episodes/dottxt_ai_outlines_task__task1655__f1_f9__481926cf` |
| 3 | `dottxt_ai_outlines_task__task1706__f4_f6__52e9b985` | conflicting | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c02/episodes/dottxt_ai_outlines_task__task1706__f4_f6__52e9b985` |
| 4 | `dspy_task__task8563__f1_f5__302b58c5` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c02/episodes/dspy_task__task8563__f1_f5__302b58c5` |
| 5 | `dspy_task__task8563__f1_f6__9fa5a29d` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c02/episodes/dspy_task__task8563__f1_f6__9fa5a29d` |
| 6 | `llama_index_task__task18813__f2_f3__419886b8` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c02/episodes/llama_index_task__task18813__f2_f3__419886b8` |
| 7 | `pallets_click_task__task2800__f2_f5__b379680e` | conflicting | python | `no_patch_b` | 1 | $0.290 | `/home/user/farm-data-c02/episodes/pallets_click_task__task2800__f2_f5__b379680e` |
| 8 | `pallets_click_task__task2800__f5_f6__0dc3050e` | control | python | `no_patch_b` | 1 | $1.327 | `/home/user/farm-data-c02/episodes/pallets_click_task__task2800__f5_f6__0dc3050e` |
| 9 | `pallets_jinja_task__task1465__f8_f10__8f9d8be9` | conflicting | python | `no_patch_a` | 1 | $1.619 | `/home/user/farm-data-c02/episodes/pallets_jinja_task__task1465__f8_f10__8f9d8be9` |
| 10 | `pallets_jinja_task__task1559__f6_f8__23102621` | control | python | `no_patch_b` | 1 | $0.757 | `/home/user/farm-data-c02/episodes/pallets_jinja_task__task1559__f6_f8__23102621` |
| 11 | `pallets_jinja_task__task1559__f7_f8__89523f79` | compatible | python | `no_patch_a` | 1 | $1.106 | `/home/user/farm-data-c02/episodes/pallets_jinja_task__task1559__f7_f8__89523f79` |
| 12 | `pallets_jinja_task__task1621__f2_f3__530ffd11` | control | python | `b_broken` | 1 | $1.065 | `/home/user/farm-data-c02/episodes/pallets_jinja_task__task1621__f2_f3__530ffd11` |
| 13 | `pallets_jinja_task__task1621__f3_f5__639b8b7f` | control | python | `b_broken` | 1 | $0.334 | `/home/user/farm-data-c02/episodes/pallets_jinja_task__task1621__f3_f5__639b8b7f` |
| 14 | `pillow_task__task25__f2_f4__1bdb0381` | conflicting | python | `no_patch_b` | 1 | $0.513 | `/home/user/farm-data-c02/episodes/pillow_task__task25__f2_f4__1bdb0381` |
| 15 | `pillow_task__task25__f3_f4__2f9d0143` | conflicting | python | `no_patch_a` | 1 | $0.366 | `/home/user/farm-data-c02/episodes/pillow_task__task25__f3_f4__2f9d0143` |
| 16 | `react_hook_form_task__task153__f1_f6__d342ffda` | conflicting | typescript | `no_patch_b` | 1 | $1.201 | `/home/user/farm-data-c02/episodes/react_hook_form_task__task153__f1_f6__d342ffda` |
| 17 | `react_hook_form_task__task153__f2_f5__c7c7d41f` | conflicting | typescript | `a_broken` | 1 | $0.630 | `/home/user/farm-data-c02/episodes/react_hook_form_task__task153__f2_f5__c7c7d41f` |
| 18 | `react_hook_form_task__task153__f2_f6__dea7cc8d` | conflicting | typescript | `no_patch_a` | 1 | $0.466 | `/home/user/farm-data-c02/episodes/react_hook_form_task__task153__f2_f6__dea7cc8d` |
| 19 | `react_hook_form_task__task85__f1_f4__6f6cce73` | conflicting | typescript | `no_patch_b` | 1 | $0.292 | `/home/user/farm-data-c02/episodes/react_hook_form_task__task85__f1_f4__6f6cce73` |
| 20 | `typst_task__task6554__f1_f7__d4a98a24` | conflicting | rust | `b_broken` | 1 | $0.576 | `/home/user/farm-data-c02/episodes/typst_task__task6554__f1_f7__d4a98a24` |

Attempts retained but not counted: **0**.

