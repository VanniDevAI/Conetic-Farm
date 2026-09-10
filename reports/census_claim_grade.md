# Grading the 147 merge-clean census pairs with the claim map

No spend. The prediction was frozen and pushed in
`config/census_claim_grade.json` before any of this ran.

**Headline: 67 of 147 pairs are CE-006-shaped** — a directed one-edge chain
between the two lanes' changed definitions, and a test in the merged tree that
names a changed definition on each side. That is an upper bound on how many of
these pairs could demonstrate a semantic failure without anyone writing a new
test. I predicted under 37 and it is 67.

**And the pass found a bug in the claim map that inflated every hop number the
campaign has published.** More on that below; the figures here are corrected.

## Reproducibility first

Every one of the 147 pairs was rebuilt from nothing: a fresh blobless clone,
the base commit checked out, each gold patch applied and committed with a fixed
identity and date, and the two lane commits merged.

| | |
|---|---:|
| lane commits reproducing the manifest's sha | **147 of 147** |
| merges reproducing the manifest's `head_sha` | **147 of 147** |

The manifest is not a record of what happened once. It is a recipe.

## The directed chain

`semantic_link` tries both directions and returns the first hit, which answers
"are these two related" and not "which one provides". Provider and consumer are
different roles, so each direction was asked separately.

| budget | linked | mutual | one-way |
|---|---:|---:|---:|
| 1 edge | 74 of 147 (0.50) | 23 | **51** |
| 2 edges | 92 of 147 (0.63) | 48 | 44 |
| 3 edges | 96 of 147 (0.65) | 57 | 39 |

The interesting row is the first. **At one edge, 69% of linked pairs have a
single direction** — the claim map can name which lane provides and which
consumes. That collapses as the budget grows: at three edges only 41% are
one-way, because in a library almost everything eventually names everything.

I predicted the opposite. The frozen text says "most links will be mutual, not
one-way… at most 40% carry a single clean provider→consumer direction", and at
three edges that is right (41%). At one edge it is backwards, and one edge is
the budget that means something.

## Would the combined tree notice?

Of the 96 pairs linked at three edges:

| a test body names… | 1 edge | 2 edges | 3 edges |
|---|---:|---:|---:|
| a changed definition on **both** sides | 87 (0.91) | 89 (0.93) | 89 (0.93) |
| a changed definition on either side | 96 (1.00) | 96 (1.00) | 96 (1.00) |

I predicted under 25% for both-sides. It is 91%.

**This number is weaker than it looks and the weakness is the point.** "A test
names the changed definition" is not "a test would catch these two lanes
disagreeing". These are mature libraries with large suites; a test naming a
changed public function is close to automatic. What CE-006 had was much
narrower — lane2's *own new test* called lane1's *changed* procedure with the
old signature — and nothing static distinguishes that from an old test that
happens to mention both names.

So the 67 is a **candidate set**, not a finding. It says: here are 67 pairs
where a provider/consumer relationship exists and tests exist on both sides of
it, so grading the merged tree is worth doing. Whether any of them actually
breaks is a question this pass did not ask.

## The 67, broken down

| | |
|---|---:|
| CE-006-shaped, strict | **67 of 147 (0.46)** |
| …with a single nameable provider | 44 |
| …with both graded `tests.patch` applying to the merged tree | 30 |
| …relying on the repository's own tests only | 37 |

By repository: jinja 31, click 15, dspy 11, datasets 7, llama-index 2,
outlines 1. By class: 37 `same_file`, 30 `textual`-but-merges.

The 30 with both graded test patches applied are the strongest candidates —
the merged tree runs the tests CooperBench itself would grade with. For the
other 37 the graded patches refuse to apply on the merged tree (82 of 147
overall), so "the combined tree's tests" means the repository's own.

## The bug this pass found

Test reachability came back **identical at one, two and three hops**. That is
what a saturated metric looks like, and it was: `reaches(..., max_hops=1)` was
walking two edges.

Two guards, both off by one. The target check ran unguarded, so a node already
at the budget could still return one more edge, and expansion was permitted
from that node too. `max_hops=k` meant k+1 edges, at every k.

Fixed in `farm/identity.py`, pinned by `tests/test_reaches_hop_budget.py`,
which asserts the contract the docstring always claimed: k edges, k+1 names.

What it cost, measured on these 147 pairs:

| budget | as published | corrected | inflation |
|---|---:|---:|---:|
| 1 | 92 | 74 | **+24%** |
| 2 | 96 | 92 | +4% |
| 3 | 113 | 96 | **+18%** |

**`results/census_resolved.json` carries the same inflation.** Its
`link_found: 503 of 652` was computed at a nominal three hops, which was really
four edges. It has not been recomputed; re-running the census would take about
fifteen minutes of cloning and no money, and it is the obvious next no-spend
job. `farm/census/manifest.jsonl`'s `has_link` and `link` fields come from that
file and are stale in the same direction.

One consequence worth stating plainly: **my frozen prediction of "about 112
linked" matched the buggy number almost exactly (113), because I derived it
from the census figure the same bug produced.** A prediction inherited from a
measurement cannot check that measurement. The corrected figure is 96, still
inside the band I said would not surprise me (95 to 130), but only just, and
for the wrong reason.

## Prediction against observation

| | predicted | observed | |
|---|---|---|---|
| linked, undirected | ~112 of 147 | 96 (113 uncorrected) | right for the wrong reason |
| mutual share at 3 edges | ≥ 60% | 59% | right, marginally |
| one-way share at 3 edges | ≤ 40% | 41% | right, marginally |
| directed chain at 1 hop | fewer than 40 | **74** | **wrong**, ~2× |
| tests reach either side | > 70% of linked | 100% | right, at the ceiling |
| tests reach both sides | **under 25%** | **91%** | **wrong**, badly |
| CE-006-shaped pairs | under 37 | **67** | **wrong** |

Three of seven wrong, and all three in the same direction: I badly
underestimated how close this corpus already is to demonstrating the semantic
class. The thing I was most confident about — that a test exercising both sides
would be rare — was the thing most wrong.

The one I would defend: it was wrong because the measure is loose, not because
the corpus is rich. A tighter measure of "a test that would catch this" would
land somewhere between 91% and the truth, and nothing here says where.

## What to do with the 67

1. **Grade the 30 with both graded test patches applying.** The merged tree, the
   graded tests, the same runner c06b used. No agents, no spend, and it is the
   only way to turn a candidate set into a count.
2. **Re-run the census with corrected hops** so the published link figures stop
   being 18% high.
3. **Do not read 67 as a rate of semantic failure.** It is the number of pairs
   where looking is worthwhile.
