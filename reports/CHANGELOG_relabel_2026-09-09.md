# Changelog — `ungradeable` becomes its own label (2026-09-09)

## Why

The `s02` positive control found the corpus asserting

> agent A's patch fails its own tests in isolation

for a patch that was **never graded**: the dataset's test patch could not be
applied over the agent's edit. `ungradeable` was already recorded in the
classification evidence and already excluded from `p`, but it did not reach the
**label**, so the archive stated a measurement that had not been made.

"Fails its own tests" is a measurement. "The grader never ran" is the absence of
one. A corpus that writes the second as the first cannot be audited later,
because the label has already overwritten the evidence that would correct it.

## What changed in the code

* `farm/classify.py` gains `ungradeable_a`, `ungradeable_b`, `ungradeable_both`,
  ranked **after** harness errors and missing patches and **before** individually
  broken. `is_individually_broken` and `is_genuine_integration_failure` are false
  for all three, and `failure_class` is `None`.
* The rule stays deliberately narrow, unchanged from `ungradeable_reason`: only a
  *test patch that would not apply* counts. A collection or import failure is a
  grader that ran and rejected the patch, and keeps its `*_broken` label.
* `scripts/report.py` gained meanings for the three labels.

## What changed in the archives

`scripts/relabel_ungradeable.py`, applied to every data root. The prior value is
kept as `label_original` on both the episode manifest and the campaign index —
a correction that erases what it corrected cannot itself be audited. The
migration is idempotent; a second pass reports zero changes.

| archive | attempts relabelled |
|---|---:|
| `c01` | 0 |
| `c02` | 0 |
| `c03` | **5** |
| `s01-qwen3-coder` | 1 |
| `s01-sonnet-5` | 1 |
| `s02-seed-control` | 2 |

Every change:

| episode | from | to |
|---|---|---|
| `dspy/8563 f1+f5` (c03) | `both_broken` | `ungradeable_a` |
| `pallets_click/2800 f2+f5` (c03) | `both_broken` | `ungradeable_a` |
| `pallets_jinja/1621 f2+f3` (c03) | `a_broken` | `ungradeable_a` |
| `pillow/25 f2+f4` (c03) | `a_broken` | `ungradeable_a` |
| `react_hook_form/85 f1+f4` (c03) | `both_broken` | `ungradeable_both` |
| `react_hook_form/85 f1+f5` (s01-qwen) | `both_broken` | `ungradeable_both` |
| `react_hook_form/153 f1+f3` (s01-sonnet) | `a_broken` | `ungradeable_a` |
| `tanstack_query/task1 f1+f2` (s02) | `a_broken` | `ungradeable_a` |
| `tanstack_query/task1 f3+f4` (s02) | `b_broken` | `ungradeable_b` |

## A bug the dry run caught

The first version relabelled three `c02` episodes from `no_patch_a`/`no_patch_b`
to `ungradeable_*`. That is wrong: the classifier ranks a missing patch **above**
an ungraded one — "produced nothing" is a stronger statement than "was not
measured" — and a migration that does not obey the live classifier's order
invents corrections the code would never make, leaving the archive and the code
disagreeing. Fixed, with a test, before anything was written; `c02` ends at zero
changes.

## What did NOT change

* **No headline number moves.** `c03` is still 20 attempted, 4 harness errors,
  16 measured, 15 eligible, 0 genuine integration failures.
* **`p` is unchanged** — the gradeability split already excluded ungradeable
  patches, which is how the defect was noticed at all. `c03` stays at
  `p = 0.200` over 25 graded patches.
* **Eligibility is unchanged.** An episode with an ungradeable side still counts
  as having retained both patches, because it did. Whether eligibility *should*
  additionally require both sides to be gradeable is a separate question, not
  settled here, and flagged rather than quietly decided.

What does move is the count of individually broken patches in `c03`: **14 → 9**.
Five of them were never shown to be broken.
