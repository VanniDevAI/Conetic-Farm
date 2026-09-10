# Positive control `s03` — neither pair fired, and the reason is the finding

Two seeded episodes, `claude-sonnet-5` on both agents, **$6.67** by the
OpenRouter meter, against a $10 ceiling. Per the standing instruction, the
remaining pairs are **not** being run.

Both pairs were rebuilt in the shape the last round specified: A changes a
provider's contract and ships its own tests; B extends a module that has
depended on that contract since before either agent started, is never told the
contract exists, and never opens the provider's file. Both are gold-validated
on the same images the episodes ran on.

## Required result versus observed

| | pair 1 — `timeUntilStale` | pair 2 — `floatSafeRemainder` |
|---|---|---|
| repo | TanStack Query `query-core` | zod `packages/zod` |
| A passes alone | **pass** | **pass** |
| B passes alone | **pass** | **pass** |
| merge clean | **yes**, no conflicted paths | **yes**, no conflicted paths |
| combined tests fail | **no** — both merged runs passed | **no** — both merged runs passed |
| label | `both_pass_merge_passes` | `both_pass_merge_passes` |
| cost | $2.57 | $4.11 |

Integration failures this run, by class:

| class | count |
|---|---|
| textual (merge refuses) | 0 |
| semantic (merge clean, combined tests fail) | 0 |

Under **gold** patches, on these same images, both pairs produce the semantic
failure every time. Under **live agents**, neither did.

## Why: the provider agent repairs the consumer it breaks

The seeded failure needs A to change a contract and leave the in-repo consumer
stale. Sonnet does not leave it stale. In both episodes A audited the call
sites and fixed them, unprompted, outside the scope line its brief gave it.

### Pair 1

A's brief said `Scope: packages/query-core/src/utils.ts`. A grepped for
`timeUntilStale`, found both call sites, and edited `query.ts` as well:

```diff
-    return !timeUntilStale(this.state.dataUpdatedAt, staleTime)
+    return timeUntilStale(this.state.dataUpdatedAt, staleTime) <= 0
```

From A's own PR body:

> `packages/query-core/src/query.ts`: updated `isStaleByTime`'s single return
> line to use `timeUntilStale(...) <= 0` instead of `!timeUntilStale(...)`,
> since the old boolean-negation trick relied on 0 being the only "stale"
> value.
>
> No other call sites needed changes (`queryObserver.ts`'s usage of
> `timeUntilStale` for scheduling a timeout is only invoked when the query is
> not yet stale, so the value there remains positive).

That second paragraph is the same call-site analysis this seed was designed
around, reached independently and correctly, including the reason the second
call site is safe.

### Pair 2

Same behaviour, further. A fixed the seeded consumer **and** a second one the
seed had not touched:

```
 packages/zod/src/v4/core/checks.ts  |  5 ++++-      <- the seeded consumer
 packages/zod/src/v4/core/compile.ts | 12 +++++++++---  <- found by A, not seeded
 packages/zod/src/v4/core/util.ts    |  8 +++++---   <- the briefed file
```

A's working notes name the staleness explicitly, of the exact line the seed
depends on:

> `packages/zod/src/v4/core/checks.ts` ... Current state at line 173 is the
> original/broken line: `: util.floatSafeRemainder(payload.value, def.value as
> number) === 0;` (this is stale/wrong now that `floatSafeRemainder` no longer
> snaps to 0 — must be fixed before submitting).

In `compile.ts` it also reasoned about a NaN edge the rewrite introduces:

> Negate rather than flip the comparison operator: `NaN < x` and `NaN >= x` are
> both `false`, so flipping would treat a zero-divisor's NaN remainder as "in
> tolerance".

Note what this means for the pair: A edited `checks.ts`, which is B's file, and
the merge was **still** clean — A replaced the `isMultiple` expression, B
inserted after `if (isMultiple) return;`. Merged, the code carries A's
tolerance-aware check and B's `remainder` field, and everything passes.

## A second suppressor: the agents negotiated the overlap

Coop mode gives the agents a message channel, and in pair 1 they used it
without being asked. B opened with:

> I only touched `packages/query-core/src/query.ts`, and only added a new
> method (`getStalenessReport`) right after the existing `isStaleByTime` method
> — no changes to existing code. Should merge cleanly as long as you're not
> editing that exact spot. Let me know what you're working on / which lines
> you're touching in that file (if any) so we can avoid conflicts.

A answered with its diff, and B confirmed:

> Since your change only replaces the content of the `return
> !timeUntilStale(...)` line (line ~487) without adding/removing lines, and my
> change is a pure insertion after the following `}` line, git's 3-way merge
> should apply both without conflict. I simulated it locally and confirmed no
> overlap.

So even the textual risk was coordinated away before it could exist.

## The instrument was not the problem

Everything the harness is responsible for worked, in both episodes:

* the merge was computed and recorded clean, with `conflicted_paths: []`;
* each agent was graded against its own test file only, so neither grade
  depended on the other's patch;
* nothing was `ungradeable`; both agents produced applying patches;
* both episodes were classified `both_pass_merge_passes`, which is what in fact
  happened.

This is not a detection gap. The class did not occur.

## What bounds the claim

### These pairs reproduce the class, not its stealth

Measured against each repository's **whole** suite rather than the graded file:

| tree | query-core | zod |
|---|---|---|
| base | 680 / 680 pass | 5360 / 5360 pass |
| A's feature + A's tests | **7 fail** of 683 | **4 fail** of 5366 |
| B's feature + B's tests | 682 / 682 pass | 5364 / 5364 pass |

So the gold version of A is caught by the repo's own suite on A's branch alone.
A claim map is not the only instrument that would find these.

That is not a fixable mistake in the seeds; it follows from the shape. For B's
inherited dependency to break, the provider's behaviour on that path has to
change, and if existing tests cover that path then A alone goes red. A failure
invisible to *both* branches' CI needs the inherited dependency to be untested
at HEAD — and `query-core` has one uncovered statement in `utils.ts` under
istanbul, with near-total statement coverage overall. Well-tested repositories
do not readily supply that case.

### The census figure is a lower bound

The 646-pair census (0 semantic) came from `farm.overlap.classify_overlap`, and
nothing had measured that classifier's recall, because the corpus held no
confirmed positives. These two pairs are confirmed positives. The classifier
calls **both** `independent`:

| pair | verdict | the hop it cannot see |
|---|---|---|
| 1 | `independent` | `query.ts::isStaleByTime` → `utils.ts::timeUntilStale` |
| 2 | `independent` | `checks.ts::$ZodCheckMultipleOf` → `util.ts::floatSafeRemainder` |

Recall on the known positives: **0 of 2**. It reads symbols off changed lines,
and in both pairs the provider symbol appears only in the consumer's own body,
never on a line either diff touches. Following that hop is claim-map work, not
diff work — which is the argument for the engine, stated as a measurement
rather than a claim. `tests/test_overlap_recall.py` pins it: teach the
classifier to resolve one hop and the test fails, which is the signal to
recompute the census.

## Cost

| | |
|---|---|
| episodes | 2 |
| spend (OpenRouter meter) | **$6.6718** |
| ceiling | $10 |
| pair 1 | $2.5662 |
| pair 2 | $4.1057 |

Pair 2's token-side estimate was $1.8838 against $4.1057 actually billed, a
factor of **2.18**. The provider delta remains the number of record; the token
estimate is not usable as a cap.

One harness note on the cap itself: the pre-run hold for a Sonnet episode is
$13.60 (worst-case 2.4M prompt + 200K completion tokens for two agents), so a
$10 *harness* cap refuses to start any Sonnet episode at all. The $10 here was
enforced as a spend ceiling against the meter, with the harness cap raised only
enough to admit one hold at a time.

## What this changes

The pair shape is sound and the harness detects it end to end under gold
patches. What it does not survive is a competent provider agent: the failure
mode requires A to be careless about its own call sites, and Sonnet is not. Two
runs, two repositories, the same behaviour both times — and in pair 2 it
repaired a consumer the seed had not even identified.

Three routes remain, and the choice is yours:

1. **Accept that this class needs a weaker A.** Run the same pairs against the
   open-weight arm (`qwen3-coder`), where the s01 sweep already showed a much
   lower per-agent pass rate. The question becomes empirical: does a weaker
   provider agent leave consumers stale often enough to produce the class?
2. **Remove A's ability to see the consumer.** A repository split across
   packages where the consumer is a separate published artefact would make the
   call-site audit impossible rather than merely unprompted. That is a
   different corpus, not a different brief.
3. **Stop seeding and mine for the untested-consumer case.** The one shape that
   is invisible to both branches' CI is a consumer path no existing test
   covers. That is findable statically — uncovered lines that call a symbol a
   provider patch changes — and it is the same query a claim map answers.
   Coverage data for `query-core` is already collected.
