# Campaign `c03` — report

Generated 2026-09-08T11:04:38.442998Z from `/home/user/farm-data-c03/manifest.json`. Labels are read from the corpus, never recomputed.

## Headline

| | |
|---|---:|
| Episodes attempted | 20 |
| …of which harness errors (no measurement) | 4 |
| **Episodes that produced a measurement** | **16** |
| **…of which retained BOTH patches** | **15** |
| Total cost | $8.35 |
| Cost per episode (mean) | $0.418 |
| Cost per episode (median) | $0.404 |
| Cost per episode (max) | $1.560 |
| **Genuine integration failures** | **0** |
| Cost per verified integration failure | undefined (none found) |
| Ledger settled total | $8.37 |

## Expected versus actual

Frozen prediction (`docs/EXPECTATIONS.md`, written before any run): **2** genuine integration failures from the first 20 episodes, 80% interval 0–5.

Actual: **0**.

**Against the right denominator.** The prediction is stated for 20 episodes. This campaign produced a measurement in **16** of them, and only **15** retained a patch from both agents. A genuine integration failure is impossible without both, so the effective sample is 15, not 20. Zero found in 15 episodes neither confirms nor refutes a prediction made for 20.

Difference: -2 against a point estimate of 2. Within the frozen 80% interval.

## Eligibility, integration failures, and conflicts

An episode is *eligible* when it retained a non-empty patch from both agents; only an eligible episode can show a genuine integration failure. Conflicted paths are classified from the corpus: **source** if the patch modifies a file that existed at the task base, **scratch** if either agent's patch introduces the path as a new file (Appendix B.2).

| | |
|---|---:|
| **Eligible episodes** (both patches retained) | **15** |
| **Genuine integration failures** | **0** |
| Merge conflicts among eligible episodes | 6 |
| …touching at least one real source file | 5 |
| …confined to agent scratch files | 1 |
| Spend as settled in the ledger | $8.37 |
| **Cost per eligible episode** | **$0.56** |

| Episode | Stratum | Label | Merge | Conflicted paths |
|---|---|---|---|---|
| `dspy_task__task8563__f1_f5__302b58c5` | compatible | `both_broken` | clean | — |
| `dspy_task__task8563__f1_f6__9fa5a29d` | compatible | `both_broken` | conflict | `test_toolcalls_validation.py` (scratch) |
| `pallets_click_task__task2800__f2_f5__b379680e` | conflicting | `both_broken` | clean | — |
| `pallets_click_task__task2800__f5_f6__0dc3050e` | control | `both_broken` | clean | — |
| `pallets_jinja_task__task1465__f8_f10__8f9d8be9` | conflicting | `both_broken` | clean | — |
| `pallets_jinja_task__task1559__f6_f8__23102621` | control | `both_broken` | conflict | `src/jinja2/ext.py` (source) |
| `pallets_jinja_task__task1559__f7_f8__89523f79` | compatible | `both_broken` | clean | — |
| `pallets_jinja_task__task1621__f2_f3__530ffd11` | control | `a_broken` | clean | — |
| `pallets_jinja_task__task1621__f3_f5__639b8b7f` | control | `both_pass_merge_passes` | clean | — |
| `pillow_task__task25__f2_f4__1bdb0381` | conflicting | `a_broken` | clean | — |
| `pillow_task__task25__f3_f4__2f9d0143` | conflicting | `a_broken` | conflict | `src/PIL/Image.py` (source), `src/PIL/Image.py.backup` (scratch) |
| `react_hook_form_task__task153__f1_f6__d342ffda` | conflicting | `both_broken` | conflict | `src/logic/createFormControl.ts` (source) |
| `react_hook_form_task__task153__f2_f6__dea7cc8d` | conflicting | `both_broken` | conflict | `src/logic/createFormControl.ts` (source) |
| `react_hook_form_task__task85__f1_f4__6f6cce73` | conflicting | `both_broken` | error | — |
| `typst_task__task6554__f1_f7__d4a98a24` | conflicting | `both_broken` | conflict | `crates/typst/src/foundations/str.rs` (source) |

## Outcome breakdown

| Label | Count | Meaning |
|---|---:|---|
| `both_broken` | 11 | individually broken patches (both) |
| `harness_error` | 4 | infrastructure fault (excluded from rates) |
| `a_broken` | 3 | individually broken patch (A) |
| `both_pass_merge_passes` | 1 | clean cooperation |
| `no_patch_b` | 1 | agent B produced nothing |

Individually broken patches: **14** — these are *not* integration failures, whatever the merge did.
Episodes with a missing patch: **1**.
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
| 1 | `dottxt_ai_outlines_task__task1655__f1_f8__36b79d53` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c03/episodes/dottxt_ai_outlines_task__task1655__f1_f8__36b79d53` |
| 2 | `dottxt_ai_outlines_task__task1655__f1_f9__481926cf` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c03/episodes/dottxt_ai_outlines_task__task1655__f1_f9__481926cf` |
| 3 | `dottxt_ai_outlines_task__task1706__f4_f6__52e9b985` | conflicting | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c03/episodes/dottxt_ai_outlines_task__task1706__f4_f6__52e9b985` |
| 4 | `dspy_task__task8563__f1_f5__302b58c5` | compatible | python | `both_broken` | 1 | $0.440 | `/home/user/farm-data-c03/episodes/dspy_task__task8563__f1_f5__302b58c5` |
| 5 | `dspy_task__task8563__f1_f6__9fa5a29d` | compatible | python | `both_broken` | 1 | $0.200 | `/home/user/farm-data-c03/episodes/dspy_task__task8563__f1_f6__9fa5a29d` |
| 6 | `llama_index_task__task18813__f2_f3__419886b8` | compatible | python | `harness_error` | 1 | $0.000 | `/home/user/farm-data-c03/episodes/llama_index_task__task18813__f2_f3__419886b8` |
| 7 | `pallets_click_task__task2800__f2_f5__b379680e` | conflicting | python | `both_broken` | 1 | $0.440 | `/home/user/farm-data-c03/episodes/pallets_click_task__task2800__f2_f5__b379680e` |
| 8 | `pallets_click_task__task2800__f5_f6__0dc3050e` | control | python | `both_broken` | 1 | $1.353 | `/home/user/farm-data-c03/episodes/pallets_click_task__task2800__f5_f6__0dc3050e` |
| 9 | `pallets_jinja_task__task1465__f8_f10__8f9d8be9` | conflicting | python | `both_broken` | 1 | $0.367 | `/home/user/farm-data-c03/episodes/pallets_jinja_task__task1465__f8_f10__8f9d8be9` |
| 10 | `pallets_jinja_task__task1559__f6_f8__23102621` | control | python | `both_broken` | 1 | $0.437 | `/home/user/farm-data-c03/episodes/pallets_jinja_task__task1559__f6_f8__23102621` |
| 11 | `pallets_jinja_task__task1559__f7_f8__89523f79` | compatible | python | `both_broken` | 1 | $0.444 | `/home/user/farm-data-c03/episodes/pallets_jinja_task__task1559__f7_f8__89523f79` |
| 12 | `pallets_jinja_task__task1621__f2_f3__530ffd11` | control | python | `a_broken` | 1 | $0.170 | `/home/user/farm-data-c03/episodes/pallets_jinja_task__task1621__f2_f3__530ffd11` |
| 13 | `pallets_jinja_task__task1621__f3_f5__639b8b7f` | control | python | `both_pass_merge_passes` | 1 | $0.276 | `/home/user/farm-data-c03/episodes/pallets_jinja_task__task1621__f3_f5__639b8b7f` |
| 14 | `pillow_task__task25__f2_f4__1bdb0381` | conflicting | python | `a_broken` | 1 | $0.474 | `/home/user/farm-data-c03/episodes/pillow_task__task25__f2_f4__1bdb0381` |
| 15 | `pillow_task__task25__f3_f4__2f9d0143` | conflicting | python | `a_broken` | 1 | $0.464 | `/home/user/farm-data-c03/episodes/pillow_task__task25__f3_f4__2f9d0143` |
| 16 | `react_hook_form_task__task153__f1_f6__d342ffda` | conflicting | typescript | `both_broken` | 1 | $0.414 | `/home/user/farm-data-c03/episodes/react_hook_form_task__task153__f1_f6__d342ffda` |
| 17 | `react_hook_form_task__task153__f2_f5__c7c7d41f` | conflicting | typescript | `no_patch_b` | 1 | $0.545 | `/home/user/farm-data-c03/episodes/react_hook_form_task__task153__f2_f5__c7c7d41f` |
| 18 | `react_hook_form_task__task153__f2_f6__dea7cc8d` | conflicting | typescript | `both_broken` | 1 | $0.394 | `/home/user/farm-data-c03/episodes/react_hook_form_task__task153__f2_f6__dea7cc8d` |
| 19 | `react_hook_form_task__task85__f1_f4__6f6cce73` | conflicting | typescript | `both_broken` | 1 | $0.375 | `/home/user/farm-data-c03/episodes/react_hook_form_task__task85__f1_f4__6f6cce73` |
| 20 | `typst_task__task6554__f1_f7__d4a98a24` | conflicting | rust | `both_broken` | 1 | $1.560 | `/home/user/farm-data-c03/episodes/typst_task__task6554__f1_f7__d4a98a24` |

Attempts retained but not counted: **0**.


## Grading integrity: what the `error` outcomes actually were

Half the graded patches (14 of 30) produced an `error` rather than a clean pass
or fail, so the classifier counted them as individually broken. That is the
right default — an unrunnable patch is not a passing one — but the category is
not homogeneous, and the difference matters for reading `p`:

| Cause | Count | Is "broken" fair? |
|---|---:|---|
| No test summary: collection or import failure | 9 | **Yes.** These include genuine breakage in the agent's own edit, e.g. `SyntaxError: invalid syntax` at `src/click/core.py:603`, which stops `conftest.py` importing at all. |
| The dataset's test patch would not apply | 5 | **No.** The agent edited the same test file the graded patch touches (`error: tests/test_context.py: patch does not apply`), so the episode could not be graded. Ungradeable is not the same as wrong. |

Excluding the 5 ungradeable patches raises the observed pass rate from
`p = 5/30 = 0.167` to `p = 5/25 = 0.200`. Both are far below the frozen
estimate of `p ≈ 0.45` (§2.2, range 0.25–0.60), so the conclusion does not turn
on which number is used — but the honest range is stated rather than the
flattering one.

This is the mirror image of §4.1's recorded bias. That warned CooperBench's own
eval would *inflate* the pass rate; this deflates it, because an agent that
edits the tests it will be graded by makes itself ungradeable. Neither was
predicted in the direction it appeared.
