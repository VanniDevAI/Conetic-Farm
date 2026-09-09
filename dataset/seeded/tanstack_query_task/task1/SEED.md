# Seeded semantic pairs — TanStack Query `query-core`

Two pairs, four features of **one** task so both episodes share one image.

| pair | episode | A (provider) | B (consumer) |
|---|---|---|---|
| 1 | `f1+f2` | `utils.ts` `hashKey` gains a `v2:` prefix | `queryCache.ts` `findAllByKeyPrefix` parses `queryHash` |
| 2 | `f3+f4` | `utils.ts` page helpers return frozen arrays | `infiniteQueryBehavior.ts` `appendPageSorted` reorders in place |

## Pair 1 — `hashKey`

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


## Pair 2 — frozen page arrays

**Edge:** `addToEnd`/`addToStart` are defined in `utils.ts`; their *return
value's mutability* is consumed in `infiniteQueryBehavior.ts`, which reorders
the returned pages in place.

| run | expected | observed |
|---|---|---|
| A alone, A's tests | pass | **pass** |
| B alone, B's tests | pass | **pass** |
| merged, A's tests | pass | **pass** |
| merged, B's tests | **fail** | **fail** — `TypeError: Cannot assign to read only property '0'` |

## A third defect the control caught: the disk guard reclaims the next image

The two pairs were first built as `task1` and `task2`. The guard protects only
the tags of the task about to run, so during episode 1 it reclaimed `task2`'s
tags — and because `task2`'s image was a *tag* of `task1`'s, episode 2 then
found nothing and started a 13-minute rebuild, which the guard would have
reclaimed again next time.

Making both pairs features of one task fixes it properly: one image, no
reclaim between episodes, and no reliance on tag-sharing that the guard cannot
see through.

## And a fourth: Redis

The harness starts Redis via docker when it cannot find a running one, and this
environment cannot pull the image. The first control attempt died on
`error: Failed to start Redis` after the host Redis was reclaimed by the
container. Preflight checks Redis, so this is caught before a campaign — but it
is worth restating that the host Redis must be running, not merely started once.
