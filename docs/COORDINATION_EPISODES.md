# Coordination episodes

A coordination episode is a record of two agents working the same codebase from
different directions, written so the interesting part survives after the
artifacts are gone. It says what each agent was allowed to see, what each one
assumed, what `git` concluded, what the product did, and which claim would have
caught it.

Every episode carries a **matched null or control**: the same seed, same briefs,
same graded tests and same grader, differing in one attribute. The control is
part of the record, not a footnote — the difference between the two rows is the
finding, and in CE-004 the control is the more informative half.

Every claim also carries the **published surface** attribute: whether the
contract at the end of its chain is exported from the package. That attribute
is what separates CE-004 from its control.

Sources of record: `/home/user/farm-sweep-s01/qwen3-coder/episodes/` (CE-001),
`/home/user/farm-seed-s04/<id>/pair_result.json` with its null under
`/home/user/farm-seed-s03/<id>/attempts/attempt-002/` (CE-002, CE-003), and
`/home/user/farm-c05a/<id>/pair_result.json` (CE-004 and its control).

### Predictions ledger

`c05a` was run with a prediction frozen per arm in `config/c05_step_a.json`
before any agent started. Both were correct.

| arm | predicted | observed |
|---|---|---|
| query-core, contract not exported | null | **null** |
| zod, contract exported | fires | **fires**, semantic, stealthy |

---

## CE-001 — two branches rewrite `handleSubmit`'s formState handling

**Repository** react-hook-form, `task153`, base `cec3267e12aaee0`
**Episode** `react_hook_form_task__task153__f1_f2__ae72500f` (`s01`, qwen3-coder arm)
**Verdict** `integration_failure_merge` — **textual**

The first genuine both-pass integration failure the Farm produced, and the only
one `git` catches on its own. It is here because the series is not only about
the semantic class: it is the baseline the other three are measured against.

### Lanes

| | lane A | lane B |
|---|---|---|
| task | leave `formState` consistent when `onValid` throws | add an `onFinally` callback to `handleSubmit` |
| edited | `src/logic/createFormControl.ts`, `src/__tests__/useForm/handleSubmit.test.tsx` | `src/logic/createFormControl.ts`, `src/types/form.ts` |
| setting | coop, shared repository, channel available | same |

### Assumptions

Both agents assumed they owned the submission path. Neither is wrong: the two
briefs are ordinary, independent pull requests that happen to land in the same
twenty lines of `createFormControl.ts`.

### Git outcome

**Conflict**, on `src/logic/createFormControl.ts`. A's hunk starts at line 1122;
B's hunks cover 1097, 1118 and 1131.

### Product outcome

Not reached. Both patches pass their own tests alone; the merge never produced a
tree to test.

### Claim chain and anchor

None required. The two patches overlap textually, so no claim map is needed to
see it — which is exactly the point of recording this episode: it is the class
that costs nothing to detect.

### Published surface

Not applicable. The collision is inside one file in one repository, not across a
contract.

### Cost

$0.2608.

---

## CE-002 — `timeUntilStale` loses its clamp under a consumer that negates it

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

## CE-003 — `floatSafeRemainder` stops snapping under a check that tests `=== 0`

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

## CE-004 — `floatSafeRemainder` crosses a published package boundary

**Repositories** zod `packages/zod` (provider) → `zod-multipleof-hints` (consumer)
**Episode** `zod_seam__floatSafeRemainder` (`c05a`)
**Model** `claude-sonnet-5`, both lanes
**Verdict** **semantic**, **stealth flag set**

The first episode with no construction anywhere in it. The consumer is a
separate repository depending on `zod@4.5.4` from the registry — the exact
version of the provider's base commit. No file was removed from anyone's disk,
no path was mounted read-only, and no leak check was needed, because the two
agents are in different repositories.

### Lanes

| | lane A — provider | lane B — consumer |
|---|---|---|
| repository | zod, whole and unmodified | `zod-multipleof-hints` |
| owns | `packages/zod/src/v4/core/util.ts` | `src/hints.ts` |
| sees the provider as | its own source | built JavaScript in `node_modules` |
| branch | `solo`, private bare repo in its own container | same, separate container |
| channel | none | none |

### Assumptions

* **A assumed repairing its own callers was enough**, and repaired both of them
  unprompted — `core/checks.ts` and `core/compile.ts` — on top of the briefed
  change to `util.ts`. zod's public `z.number().multipleOf()` behaviour is
  unchanged as a result, and zod's own full suite is green.
* **B assumed `core.util.floatSafeRemainder(...) === 0` still means "is a
  multiple".** It reaches for zod's own helper deliberately, so that a form
  hint and the schema validating the same field can never disagree:

  ```ts
  export function isMultipleOf(value: number, step: number): boolean {
    return core.util.floatSafeRemainder(value, step) === 0
  }
  ```

  That is the right instinct, and it is the reason the helper is exported.
* Neither agent could have discovered the other. Different repositories, and
  the provider arrives as a tarball.

### Git outcome

**Clean by construction.** Two repositories share no path, so there is nothing
for `git` to conflict on. Recorded with that reason attached rather than
inferred from a merge that ran.

### Product outcome

| run | result |
|---|---|
| A alone, provider's own graded tests | pass |
| A alone, provider's **full** suite | **pass** |
| B alone, provider from the registry | pass |
| **integrated** — provider rebuilt from A's patch, packed, installed | **fail** |

`2.03 / 0.07` is whole in decimal and not in binary floating point. With the
snap gone it stops being a multiple for that caller, and only for that caller.

### Claim chain, anchor, and published surface

```
chain              hints.ts::isMultipleOf  ->  core.util.floatSafeRemainder
anchor             packages/zod/src/v4/core/util.ts:327
published surface  yes -- namespace `util`, from packages/zod/src/v4/core/index.ts
```

### Stealth flag

**Set.** A's patch leaves the provider repository's own full suite green, and
B's branch is green against the published provider. Neither branch's CI reports
anything. The failure exists only in the combination.

### Cost

$1.3143.

### Matched control — the same change that does *not* cross

`qc_seam__timeUntilStale`, run in the same pass, same model, same topology:
TanStack Query `packages/query-core` as provider, `qc-staleness-panel`
depending on `@tanstack/query-core@5.102.8` as consumer.

| run | result |
|---|---|
| A alone, provider's own graded tests | pass |
| A alone, provider's **full** suite | pass |
| B alone, provider from the registry | pass |
| **integrated** | **pass** |

```
chain              digest.ts::stalenessRows -> Query#isStaleByTime -> timeUntilStale
published surface  no -- timeUntilStale is absent from packages/query-core/src/index.ts
```

The provider agent repaired `query.ts::isStaleByTime` alongside its briefed
change, exactly as in CE-002:

```diff
-    return !timeUntilStale(this.state.dataUpdatedAt, staleTime)
+    return timeUntilStale(this.state.dataUpdatedAt, staleTime) <= 0
```

`Query#isStaleByTime` is the published surface, and after the repair it answers
identically, so the downstream package sees nothing. Cost $0.4482.

The control is the load-bearing half of the pair. CE-002 is this same seed
firing, and it fired only because the consumer had been removed from the
provider's disk so the repair was impossible. Across a real boundary the repair
happens and the failure does not.

---

## `published surface` — a claim attribute

Every claim now carries whether the contract at the end of its chain is on the
package's published surface, computed by `farm/surface.py` from the package's
entry points by following `export` statements and relative re-exports:

| episode | contract | published | how |
|---|---|---|---|
| CE-002 | `timeUntilStale` | no | — |
| CE-003 | `floatSafeRemainder` | yes | namespace `util` |
| CE-004 | `floatSafeRemainder` | yes | namespace `util` |
| CE-004 control | `timeUntilStale` | no | — |

One nuance worth stating: the attribute is about the **contract that changed**,
not the path the consumer took to reach it. In CE-004's control the consumer
reaches `isStaleByTime` through the published `Query` class, so its own access
is public; what is internal is `timeUntilStale`, and that is what decides
whether the change can escape.

## The rule the four episodes give

1. **CE-001** — same file, overlapping hunks. `git` refuses. Costs nothing to
   detect and needs no engine.
2. **CE-002** — disjoint files, one repository, consumer hidden from the
   provider. Fires, but the boundary was built for the experiment.
3. **CE-003** — same, in a second repository. Fires, same caveat.
4. **CE-004** — disjoint repositories, real published package, nothing hidden.
   Fires, and neither branch's CI sees it.

Set against CE-004's control, which differs from CE-004 in exactly one
attribute:

> **A coordination failure crosses a package boundary only when the contract
> that changed is on the published surface.**

Internal contracts are repaired by the provider's own call-site audit, which the
agent performed unprompted and correctly in all four episodes — it is not a
question of diligence. What survives that audit is what the package exports.

The consequence for what to watch: exported surfaces. A route table, a migration
sequence, a config-key namespace, a published helper. Internal call graphs are
the author's own problem and the author solves them.
