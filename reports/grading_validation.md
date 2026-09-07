# Grading validation — gold-patch oracle

**Question:** does the grading pipeline assign the right label, on evidence,
before any money is spent on agents?

**Method.** `scripts/oracle_dryrun.py` substitutes each feature's **gold** patch
for the agent's and runs the full triad — A alone (own tests *and* partner's),
B alone (likewise), a three-way merge, the merged suites, and classification.
The gold patches are the benchmark's reference solutions, so the expected label
follows from the dataset's own conflict label. It costs nothing: no model is
called.

Validating in **both directions** matters. A classifier that always answered
"integration failure" would pass the conflicting case and fail nothing; only the
compatible case rules that out.

## Results

| Episode | Stratum | Language | Expected | Got | |
|---|---|---|---|---|---|
| `react_hook_form_task/task153 f1+f6` | conflicting | TypeScript | `integration_failure_merge` | `integration_failure_merge` | **match** |
| `pallets_jinja_task/task1559 f7+f8` | compatible | Python | `both_pass_merge_passes` | `both_pass_merge_passes` | **match** |

Conflicting case:

```
A alone: own=pass  partner=fail
B alone: own=pass  partner=fail
merge  : conflict on src/logic/createFormControl.ts
LABEL  : integration_failure_merge
```

Compatible case:

```
A alone: own=pass  partner=fail
B alone: own=pass  partner=fail
merge  : clean  a_tests=pass  b_tests=pass
LABEL  : both_pass_merge_passes
```

In both, each gold patch passes its own suite and fails its partner's — which is
what a correctly-scoped feature patch should do, and confirms the suites
discriminate on the feature under test rather than passing regardless.

## Three bugs this caught

The first run of the compatible episode returned `integration_failure_tests` —
a **false** integration failure. Investigating it, rather than recording it,
found three defects in my grading. Each would have silently corrupted the
headline metric.

**1. The merged diff was corrupted in transit.** It came back through captured
stdout, which mangled binary hunks and trailing whitespace. `git apply` rejected
it with `error: corrupt patch at line 380`, the runner exited 128 before running
a single test, and that was graded as "the merged tests failed". A plumbing bug
was manufacturing integration failures out of nothing.
*Fix:* the merge writes its diff to a mounted file. A clean merge that produces
no diff is now an error rather than an empty patch.

**2. Alarming substrings were treated as infrastructure errors.** jinja's suite
prints `ImportError` twelve times while running perfectly well; a clean
`8 failed, 47 passed` run was labelled `error`. That turns a correct patch into
a broken one — and since a genuine integration failure requires *both* patches
to pass alone, it silently suppresses the very thing this corpus is built to
find.
*Fix:* the rule is inverted. A **test-summary line is positive evidence the
suite ran**; when one is present the exit code decides and nothing in the body
overrides it. Error signatures are consulted only when no summary exists.

**3. A non-zero exit with no test output counted as a test failure.** A patch
that will not apply says nothing about whether the code is correct.
*Fix:* that is an error, never a failure.

Eight regression tests (`tests/test_classify.py`) pin all three against the
exact jinja output and the exact git error, plus go and cargo summary formats
since the plan includes both languages. 46 tests pass.

## What this does not establish

That the *agents* work. It validates the measuring instrument, not the thing
being measured. It also cannot detect a systematic bias shared by the oracle and
the campaign — for instance, both use the same task images, so an image that
subtly misconfigures a suite would look correct here.

## Regression check after the fixes

Both episodes were re-run against the fixed grader. The compatible episode moved
from a false `integration_failure_tests` to the correct
`both_pass_merge_passes`; the conflicting episode was unchanged at
`integration_failure_merge`, confirming the fixes did not cost a true positive.

One detail from the re-run worth recording. In the TypeScript episode, agent
A's patch against **agent B's** tests is graded `error`, not `fail`:

```
reason: no test summary and exit 1
```

jest crashed inside `jestAdapterInit` and printed a raw stack trace with no
summary line, so the suite never reported. `error` is the honest label — we
did not learn whether those tests would have passed.

The likely cause is benign: feature 6's test file references APIs that feature 6
introduces, so under feature 1's patch alone it throws at load time rather than
failing an assertion. Semantically that is "the partner feature is absent",
which is the expected outcome; we simply cannot prove it from a crash, and the
grader does not guess.

This does not affect the episode's label. `partner_tests` never feeds the
classification — it drives only the warning that fires when one patch alone
already satisfies **both** suites, which would mean the two features overlap and
the pair is a weak integration signal. A crash cannot trigger that warning, so
the conservative reading costs nothing.
