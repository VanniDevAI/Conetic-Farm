# Seeded semantic pair 1 — TanStack Query `query-core`

One task, two features, one image. `f1` is agent A, `f2` is agent B.

## Shape: the consumer is inherited, not written fresh

A semantic integration failure does not happen because someone writes a brand
new consumer of a contract that changed under them. It happens because someone
**builds on code that already depended on the old contract** and never had
reason to look at it. So B's feature is a thin extension of a method that has
called into the provider since long before either agent started.

| | agent A (provider) | agent B (consumer) |
|---|---|---|
| source file | `packages/query-core/src/utils.ts` | `packages/query-core/src/query.ts` |
| graded tests | `src/__tests__/utils.test.tsx` | `src/__tests__/query.test.tsx` |
| change | `timeUntilStale` returns the **signed** remaining time instead of clamping at `0` | add `Query#getStalenessReport(staleTime)` |
| told about the other side | no | no |

File overlap: **none**. The merge is textually clean.

## The inherited dependency (this is the claim map's own content)

```
provider   packages/query-core/src/utils.ts :: timeUntilStale(updatedAt, staleTime)
consumer   packages/query-core/src/query.ts :: Query#isStaleByTime(staleTime)
edge       query.ts:487  ->  return !timeUntilStale(this.state.dataUpdatedAt, staleTime)
```

`isStaleByTime` exists at HEAD and has read `timeUntilStale` through a boolean
negation for its whole life. That negation is only correct while the clamp
holds: `!0` is `true` for stale data, but `!(-4000)` is `false`.

B's brief asks for a report that uses "the query's own existing staleness
determination rather than recomputing it" — ordinary advice, and the reason B
inherits the edge without ever being told the edge exists. B never opens
`utils.ts` and is never told the word `timeUntilStale`.

## Gold validation (no model spend)

| run | expected | observed |
|---|---|---|
| A alone, A's tests | pass | **pass** |
| B alone, B's tests | pass | **pass** |
| merged, A's tests | pass | **pass** |
| merged, B's tests | **fail** | **fail** — `expected false to be true` |

## Known limitation: A alone is red on the repository's own suite

Measured against the whole `query-core` suite, not just the graded file:

| tree | result |
|---|---|
| base | 680 passed / 680 |
| A's feature + A's tests | **7 failed** / 683 |
| B's feature + B's tests | 682 passed / 682 |

The seven are `queryClient` (5), `queryObserver` (1) and `queryCache` (1), all
reaching `timeUntilStale` through `isStaleByTime`. So this pair reproduces the
semantic **class** — clean merge, both agents graded green, combined behaviour
broken — but not the **stealth**: running the repository's own test suite on
A's branch would also have caught it.

That is not a flaw that can be patched out of this pair; it follows from the
shape. For B's inherited dependency to break, the provider's behaviour on that
path has to change, and if existing tests cover that path then A alone goes
red. A failure invisible to *both* branches' CI needs the inherited dependency
to be **untested at HEAD** — and `query-core` has one uncovered statement in
`utils.ts` and near-total statement coverage overall (istanbul, base tree).
Well-tested repositories do not readily supply that case.
