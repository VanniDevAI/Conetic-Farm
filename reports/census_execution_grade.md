# Running the merge-clean census pairs: would the tests catch it?

No spend — no model was called. Cloning, pip and pytest.

The static pass (`reports/census_claim_grade.md`) bounded what the tests
*could* observe: 67 of 147 pairs have a one-edge directed chain between the two
lanes' changed definitions and a test naming a changed definition on each side.
It said explicitly that reaching is not catching. This runs them.

**Zero semantic failures in 50 fully scored pairs.** Every merged tree that
could be assembled with both of its graded test patches, on a base commit that
was green, with both lanes green alone, passed. 86 of 86 rebuilt merges
reproduced the manifest's recorded SHA exactly.

I predicted 5 to 15. The reasoning behind that prediction was right and the
number was still too high: a CooperBench task is one pull request cut into N
features, so its features were written to coexist and were merged together
upstream. Two of them do not disagree, and now that is measured rather than
argued.

## What "scored" means, and why most pairs are not

Three runs decide a pair: the suite at the base commit, the suite with each
lane's patch alone, and the suite on the merged tree.
`farm.failure_class.classify` then applies the campaign's own rule — `semantic`
requires a clean merge, every lane green alone, and a red merged tree.

A pair is only scoreable when **both** graded test patches apply to the merged
tree, and that turns out to be the exception rather than the rule.

| | pairs |
|---|---:|
| merge-clean pairs in the census | 147 |
| executed | **86** |
| …of which fully scored | **50** |
| …of which a semantic failure | **0** |
| refused: the two graded test patches cannot coexist in the merged tree | 36 |
| merged tree red, but a lane was already red alone | 2 |
| not executed at all | 61 |

The 36 are the structural finding. For more than a third of the pairs that
were runnable, **the combined tree cannot be assembled with its own graded
tests at all** — the two features' `tests.patch` files touch the same test file
and refuse each other in both orders. There is no version of "would the tests
catch it" for those pairs, because there is no tree that has both the code and
the tests.

The 2 are go-chi's, and `farm.failure_class` already refuses to call them an
integration failure: a merged tree that fails while a lane was failing on its
own branch is that lane's defect.

## The two harness bugs this pass had to get past

Both would have produced a publishable-looking finding.

**The interpreter deleted itself.** The first jinja run reported all 64 pairs as
"a lane is red on its own branch" and zero semantic failures. The venv lived
inside the checkout; jinja's `.gitignore` covers `venv/` and not `.venv/`, so
`git add -A` staged it into the lane commit and the next
`git checkout --force base` deleted it as a file the target commit does not
have. Every run after the first lane was `/bin/sh: .venv/bin/python: not
found`, which the harness recorded as a red suite. "Gold patches do not survive
being split" is exactly what that looks like, and it is what I would have
written.

The signal was there and I read past it: 12 of 64 head SHAs failed to
reproduce, and I noted it without acting. The environment now lives outside the
repository, and a lane commit that does not match the manifest's recorded SHA
aborts the run instead of scoring it.

**Five semantic failures that were one missing test patch.** With that fixed,
click's task2800 reported five, every one involving feature 6. A feature's
`tests.patch` is the other half of its `feature.patch`: feature 6 adds
`import copy` to click's source *and* adds `"copy"` to `ALLOWED_IMPORTS` in
`tests/test_imports.py`, the test that polices click's import cost. In every
merged tree feature 6's test patch refused to apply — the other feature's had
already touched that file — so the source half landed without the test half and
`test_light_imports` failed. Five times, for a reason with nothing to do with
the other lane.

A pair whose graded test patches cannot both be applied is now not scored at
all. Both apply orders are tried first, since the patches usually collide on one
test file and order alone decides who wins.

## A third artifact, caught by the design rather than by luck

The toolchain has to be chosen per task, and the baseline is what chooses it.
jinja's base commits are green under a current pytest and red under 7.x. click's
two tasks are the exact opposite: a 2026 pytest turns their `parametrize`
deprecations into collection errors, which cost click's 20 pairs on one run.
Pinning either way silently discards a repository.

The runner now tries pytest-current, then 7, then 6, and keeps the first whose
baseline is green, recording which was used. dspy needed a fourth shape
entirely — `-c pyproject.toml`, which only a modern pytest can parse — and its
first attempt fell through to pytest 6, hit a `TomlDecodeError`, and reported
all 17 of its pairs as "base commit not green". That was the harness, not dspy.

## Coverage, and what stopped the rest

| repo | pairs | executed | why not |
|---|---:|---|---|
| jinja | 64 | yes, all scored | |
| click | 20 | yes, 0 scored | all 20 refused: test patches cannot coexist |
| go-chi | 2 | yes, both scored | |
| outlines | 18 | no | `import outlines` needs torch; the CUDA wheel stack is 3.3 GB compressed against 8 GB of free disk, and the CPU-only index is refused by the proxy |
| dspy | 17 | no | no full-suite invocation available here is green at base. CooperBench's own `run_tests.sh` grades a single test file per task, not the suite |
| llama-index | 11 | no | baseline red at base: 170 failed, 22 errors |
| datasets | 9 | no | same shape as dspy: graded per single test file |
| pillow | 6 | no | C extensions are built in-tree, and this runner cleans the tree between runs |

**86 of 147 executed, 50 scored.** The honest summary of the rest is not "they
would have failed" — it is that this corpus is reachable through its Docker
images and only partly reachable without them.

One thing the coverage table records that is worth more than the coverage: for
dspy and datasets, **CooperBench itself grades one test file per task**, not the
repository's suite. Where that is true, "the combined tree's tests" means a
single file chosen for one feature, and a semantic failure anywhere else in the
repository is invisible by construction.

## Prediction against observation

| | predicted | observed | |
|---|---|---|---|
| executable | 84 to 120 of 147 | **86** | right |
| baselines green | at least 6 of 8 repos | **3 of 8** | **wrong** |
| lanes green alone | above 90% | 48 of 50 scored pairs had both green | right |
| **semantic failures** | **5 to 15** | **0** | **wrong** |
| artifacts, not coordination | at least half of any hits | no hits to classify | n/a |
| genuine coordination failures | 0 to 5 | **0** | right, at the floor |
| merged red with a red lane | 5 to 20 | 2 | low but in range |

The baseline prediction is the instructive miss. I assumed a pinned base commit
would be green under a current toolchain, and three of eight were not — click's
under a 2026 pytest, dspy's under any full-suite invocation, llama-index's under
anything. A pinned commit is not a reproducible environment.

## The corpus verdict

**CooperBench is closed for this purpose.** Its pairs are patches from a single
pull request, co-authored to fit together, and they cannot produce the semantic
class.

The number is **67 CE-006-shaped pairs and zero failures**: 67 of 147 carry a
one-edge directed provider-to-consumer chain with a test naming a changed
definition on each side, 24 of those were fully scoreable, and not one of them
has a combined tree that fails. Extended to every pair that could be scored at
all, 50 of 50 pass.

This is not a power problem and more grading will not fix it. The condition the
semantic class requires — two changes authored independently, neither author
having seen the other's — does not exist anywhere in this corpus by
construction. Every task is one PR cut into N features that shipped together.

Further census grading is retired. The class has to be sourced from history
where the condition really occurred, or created, which is what the Farm's own
episodes do.

## What this does and does not establish

**Established.** Of the 50 pairs where a merged tree could be built on a green
base with both graded test patches and both lanes green alone, none has a
combined tree that fails. The static pass called 67 pairs CE-006-shaped; 24 of
those were among the 50 scored, and none of them failed.

**Established, and more useful.** 36 of 86 runnable pairs cannot be assembled
with their own tests, and 5 of 8 repositories cannot be run at all without their
Docker images. The corpus's ability to demonstrate the semantic class is far
smaller than 147, and smaller than the 67 the static pass bounded.

**Not established.** That merge-clean gold pairs are safe. A passing merged tree
means the tests present did not catch anything, and for these pairs the tests
present are frequently one file.

**What it says about the campaign.** Four campaigns spent money constructing the
semantic class, and one honest reading of a zero here is that the money was
wasted on something already in the corpus. This says the opposite. Gold patches
from a single pull request do not disagree with each other, because they were
authored together to fit together. CE-006 and CE-007 are failures between
*independently authored* changes that never saw one another, and that condition
does not exist anywhere in this corpus. It has to be created, which is what the
Farm does.

The right next step is therefore not more census grading. It is the pair design
in step 3: briefs whose claim-map footprints are disjoint by construction, so
that textual conflicts stop consuming the episodes and each one reaches the
endpoint that matters.
