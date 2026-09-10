# Running the merge-clean census pairs: would the tests catch it?

No spend — no model was called. Cloning, pip and pytest.

The static pass (`reports/census_claim_grade.md`) bounded what the tests
*could* observe: 67 of 147 pairs have a one-edge directed chain between the two
lanes' changed definitions and a test naming a changed definition on each side.
It said explicitly that reaching is not catching. This runs them.

**PLACEHOLDER_HEADLINE**

## What "scored" means, and why most pairs are not

Three runs decide a pair: the suite at the base commit, the suite with each
lane's patch alone, and the suite on the merged tree.
`farm.failure_class.classify` then applies the campaign's own rule — `semantic`
requires a clean merge, every lane green alone, and a red merged tree.

A pair is only scoreable when **both** graded test patches apply to the merged
tree, and that turns out to be the exception rather than the rule.

PLACEHOLDER_SCORED_TABLE

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

PLACEHOLDER_COVERAGE

## Prediction against observation

PLACEHOLDER_PREDICTIONS

## What this does and does not establish

PLACEHOLDER_CONCLUSION
