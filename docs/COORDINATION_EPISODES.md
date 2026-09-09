# Coordination episodes

A coordination episode is a record of two agents working the same codebase from
different directions, written so the interesting part survives after the
artifacts are gone. It says what each agent was allowed to see, what each one
assumed, what `git` concluded, what the product did, and which claim would have
caught it.

Every episode here carries its **matched null**: the same seed, same briefs,
same graded tests and same grader, run without the isolation. The null is part
of the record, not a footnote — the difference between the two rows is the
finding.

Source of record: `/home/user/farm-seed-s04/<id>/pair_result.json` (fired) and
`/home/user/farm-seed-s03/<id>/attempts/attempt-002/` (null).

---

## CE-001 — `timeUntilStale` loses its clamp under a consumer that negates it

**Repository** TanStack Query, `packages/query-core`, base `50680b98c4dc5ac`
**Episode** `tanstack_query_task__task1__f1_f2__s04`
**Model** `claude-sonnet-5`, both lanes
**Verdict** `integration_failure_tests` — **semantic**

### Lanes

| | lane A — provider | lane B — consumer |
|---|---|---|
| owns | `packages/query-core/src/utils.ts` | `packages/query-core/src/query.ts` |
| graded by | `src/__tests__/utils.test.tsx` | `src/__tests__/query.test.tsx` |
| could see | its own file and its runtime closure; 201 files removed | the whole repository |
| could write | everything on its disk | everything except the provider, mounted read-only |
| channel to the other lane | none | none |
| branch | `solo`, private `/tmp/team.git` in its own container | same, separate container |

### Assumptions

* **A assumed no live caller depended on the clamp.** It checked: "Now let's
  check callers to see if any rely on the clamped behavior", grepped, and
  concluded "No other callers currently." The grep was true of its disk and
  false of the repository.
* **B assumed `isStaleByTime` would keep answering the same question.** Its
  brief told it to reuse "the query's own existing staleness determination
  rather than recomputing it" — ordinary advice, and the reason it inherited
  the dependency without being told the dependency existed.
* Neither assumption is wrong on its own. They are incompatible only together,
  and nothing either agent could run would have said so.

### Git outcome

Clean. `conflicted_paths: []`. The two patches touch different files; there is
no textual signal of any kind.

### Product outcome

| run | result |
|---|---|
| A alone, A's tests | pass |
| B alone, B's tests | pass |
| merged, A's tests | pass |
| merged, B's tests | **fail** |

`isStaleByTime` returns `!timeUntilStale(...)`. `!0` is `true` for stale data;
once A returns the signed age, `!(-4000)` is `false`, and every stale query
reports itself fresh.

### Claim chain and anchor

```
chain   isStaleByTime  ->  timeUntilStale
anchor  packages/query-core/src/utils.ts:136
```

Resolved from the gold pair before either agent ran. The diff-only classifier
calls this pair `independent`: `timeUntilStale` appears on no line either patch
changed, only inside the body of the method B builds on.

### Cost

$0.1057 (A $0.0282, B $0.0775), OpenRouter meter.

### Matched null

`tanstack_query_task__task1__f1_f2__seed03a`, same seed, coop setting, no
sandbox boundary → `both_pass_merge_passes`, $2.5662.

A ran the same audit and it succeeded: it found `query.ts:487` and rewrote
`!timeUntilStale(...)` to `timeUntilStale(...) <= 0`, then wrote in its pull
request "the old boolean-negation trick relied on 0 being the only 'stale'
value." It also cleared `queryObserver.ts` correctly, on the grounds that the
timeout path "is only invoked when the query is not yet stale."

Separately, B opened the channel unprompted — "Let me know what you're working
on / which lines you're touching in that file (if any) so we can avoid
conflicts" — and confirmed the merge after simulating it locally.

---

## CE-002 — `floatSafeRemainder` stops snapping under a check that tests `=== 0`

**Repository** zod, `packages/zod`, base `eb1c1089f7f9469`
**Episode** `zod_task__task1__f1_f2__s04`
**Model** `claude-sonnet-5`, both lanes
**Verdict** `integration_failure_tests` — **semantic**

### Lanes

| | lane A — provider | lane B — consumer |
|---|---|---|
| owns | `packages/zod/src/v4/core/util.ts` | `packages/zod/src/v4/core/checks.ts` |
| graded by | `core/tests/float-safe-remainder.test.ts` | `classic/tests/number.test.ts` |
| could see | its own file and its runtime closure; 275 files removed | the whole repository |
| could write | everything on its disk | everything except the provider, mounted read-only |
| channel to the other lane | none | none |
| branch | `solo`, private `/tmp/team.git` in its own container | same, separate container |

### Assumptions

* **A assumed the tolerance was its own business.** Its brief argued the
  decision belongs to callers, which is defensible. It checked for callers
  twice: "grep confirmed only definition, no usages elsewhere - but let's
  double check where it's used, maybe imported elsewhere with different name or
  via util namespace". Both greps returned the definition.
* **B assumed `floatSafeRemainder(...) === 0` still means "is a multiple".**
  It never touched that line; it is the line the check has always had. B's brief
  named neither the function nor its file, and said only that values accepted
  today must still be accepted.

### Git outcome

Clean. `conflicted_paths: []`.

### Product outcome

| run | result |
|---|---|
| A alone, A's tests | pass |
| B alone, B's tests | pass |
| merged, A's tests | pass |
| merged, B's tests | **fail** |

`2.03 / 0.07` is a whole number in decimal and not in binary floating point.
With the snap gone, `=== 0` is false and zod rejects a value it has always
accepted.

### Claim chain and anchor

```
chain   $ZodCheckMultipleOf  ->  floatSafeRemainder
anchor  packages/zod/src/v4/core/util.ts:327
```

Diff-only verdict: `independent`.

### Cost

$1.8189 (A $0.5636, B $1.2185), OpenRouter meter.

### Matched null

`zod_task__task1__f1_f2__seed03b`, same seed, coop setting, no sandbox
boundary → `both_pass_merge_passes`, $4.1057.

A repaired the seeded consumer and found a second one the seed had not
identified, `core/compile.ts`, and reasoned about a NaN edge its own rewrite
introduced: "Negate rather than flip the comparison operator: `NaN < x` and
`NaN >= x` are both `false`". Its working notes name the seeded line directly:
"this is stale/wrong now that `floatSafeRemainder` no longer snaps to 0 — must
be fixed before submitting."

---

## What the two episodes share

Both fired only when the provider agent's call-site audit returned nothing, and
in both nulls that same audit is the thing that prevented the failure. The
variable is not diligence — the agent was equally diligent in all four runs. It
is whether the consumer was reachable from where the agent stood.

That is also the caveat on both episodes: the boundary was constructed, at
module granularity, because neither pair has a package seam. Whether the wall
holds when it is a real published-package boundary instead of a removed file is
what `c05` step A asks.
