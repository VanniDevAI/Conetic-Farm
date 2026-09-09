# Positive control `s02` — STOPPED, not detected end to end

Two seeded episodes, `claude-sonnet-5`, **$4.85**. Per the standing instruction,
the remaining pairs are **not** being run.

## Required result versus observed

| | pair 1 (`hashKey`) | pair 2 (frozen arrays) |
|---|---|---|
| A passes alone | ungradeable | **pass** |
| B passes alone | **pass** | ungradeable |
| merge clean | **yes** | **yes** |
| combined tests fail | no — B passed merged | not gradeable |
| label | `a_broken` | `b_broken` |
| cost | $2.96 | $1.89 |

Neither episode reproduced the semantic failure that the **gold patches produce
reliably** on the same tasks in the same image.

## Why — and the distinction that matters

**This is not a detection gap in the harness.** The merge was correctly computed
as clean in both episodes, `ungradeable` was correctly identified in both, and
A's patches were correct in both (pair 1's added the `v2:` prefix; pair 2's
froze the arrays and passed its own tests). The instrument saw what happened.

Three defects, and the first two are mine, in the seeds.

### 1. The briefs told each agent to edit the file that grades it

Both episodes died on the same thing. `feature.md` said "Update the `hashKey`
tests in `utils.test.tsx`" and "Add tests in `infiniteQueryBehavior.test.tsx`" —
which are exactly the files the graded `tests.patch` patches. The graded patch
then cannot apply, and the agent is **ungradeable**, every time, by construction.

CooperBench's own tasks do not do this: the agent writes the feature, and the
graded tests arrive from `tests.patch` at grading time. My briefs broke that
separation.

*Fix:* briefs must describe the behaviour and say nothing about writing tests in
the graded file. This is mechanical and cheap.

### 2. A capable agent routes around a fragile coupling — the deeper finding

Pair 1's B was told the hash "is the JSON serialization of the query key, so the
namespace can be read straight back out of it". Sonnet ignored that and used the
structured key instead:

```ts
findAllByKeyPrefix(prefix: QueryKey): Array<Query> {
  return this.getAll().filter((query) => {
    const queryKey = query.queryKey
    return prefix.length <= queryKey.length &&
      prefix.every((segment, index) => segment === queryKey[index])
  })
}
```

That is a **better** implementation than the gold one, and it is completely
immune to A's change. The seeded coupling simply did not exist in the code the
agent wrote.

This is the result worth keeping. A seeded semantic pair depends on the consumer
adopting a fragile contract, and **a competent agent declines to adopt it**. The
gold patch produced the failure only because the gold author — me — wrote the
fragile consumer deliberately.

That has a direct consequence for `c04`: seeding semantic failures against a
strong model is not merely fiddly, it is in tension with the model being strong.
Any seeded corpus must either force the coupling structurally (the consumer is
handed only the serialized form, with no structured alternative in scope) or
accept that the strongest agents will produce the safe version and the pair will
not fire.

### 3. A real reporting defect in the harness

The classifier labelled these `a_broken` and `b_broken`, with the rationale
*"agent A's patch fails its own tests in isolation"*. **That statement is
false.** A's patch was never graded — the graded tests could not be applied.

`ungradeable` is recorded correctly in the evidence, and the report's
gradeability section counts it correctly, but it does not reach the **label**,
so the corpus asserts a broken patch where none was demonstrated. Every episode
of this kind is currently mislabelled, including in `c01`–`c03`, where the
report's `p` is computed correctly but the labels are not.

This one is a genuine harness defect and worth fixing before any further run.

## What did work

* the `ungradeable` category, added earlier today, identified the cause in both
  episodes — without it this would have read as two broken agents;
* the merge was computed and reported as clean in both;
* the disk guard kept the in-use image across both episodes after the one-task
  restructure, and no rebuild occurred;
* no infrastructure failure: Redis held, no ENOSPC, both episodes published.

## Recommendation

Fix defect 1 (mechanical), fix defect 3 (label must reflect ungradeable), and
**decide what to do about defect 2 before spending again** — it is a question
about the experiment, not a bug. Re-run these same two episodes as the control
afterwards; the gold validation still holds, so the tasks themselves are sound.
