# Seeded semantic pair 1 — TanStack Query `hashKey`

**Edge (derived from the code, not from an engine's claim map):**
`hashKey` is defined in `packages/query-core/src/utils.ts` and its *return
shape* is consumed in `packages/query-core/src/queryCache.ts`, which reads
`query.queryHash` and parses it. One producer, one consumer, one symbol, two
files.

| | agent A (provider) | agent B (consumer) |
|---|---|---|
| source | `src/utils.ts` | `src/queryCache.ts` |
| tests | `src/__tests__/utils.test.tsx` | `src/__tests__/queryCache.test.tsx` |
| change | prefix every hash with `v2:` | add `findAllByKeyPrefix`, parsing `queryHash` |

File overlap between the two: **none**. The merge is textually clean.

## Gold validation (no model spend)

| run | expected | observed |
|---|---|---|
| A alone, A's tests | pass | **pass** |
| B alone, B's tests | pass | **pass** |
| merged, A's tests | pass | **pass** |
| merged, B's tests | **fail** | **fail** — both of B's tests |

`JSON.parse('v2:["todos",1]')` throws once A's prefix lands, so B's namespace
grouping breaks. Nothing in the diff overlaps; no merge tool can see it.

## Two defects this positive control caught before any spend

1. **The runner graded both agents' test files.** Grading B also ran A's test
   file at *base*, which fails the moment A's source change lands — so a merged
   run "failed" for a reason that had nothing to do with B consuming A. The
   runner now derives its target from the applied test patch, so each agent's
   grade depends on its own tests alone.
2. **The pair did not break.** B's first implementation called `hashKey` to
   build its needle, so A's prefix applied to needle and haystack alike and the
   coupling stayed intact — B's tests passed after the merge. The brief was the
   cause: it told B to "use the cache's existing hashing rather than
   re-implementing serialization", which prevents the very failure the pair
   exists to produce. B now consumes the hash *format*, which is what a real
   consumer does.

Both were mine, and both would have been invisible in a live run: the first
would have manufactured a false semantic failure, the second would have
reported a false negative.
