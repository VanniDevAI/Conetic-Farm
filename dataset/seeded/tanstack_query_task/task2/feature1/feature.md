# Stop callers mutating cached page arrays

`addToEnd` and `addToStart` in `packages/query-core/src/utils.ts` build the
page and page-param arrays that infinite queries store in the cache. Those
arrays are handed straight to callers, so a caller that mutates one corrupts
the cached data for every other observer — a class of bug that is hard to trace
back because the mutation happens far from the cache.

Make both helpers return an **immutable** array, so accidental mutation fails
loudly at the point it happens instead of silently corrupting the cache.
Behaviour must not otherwise change: the same elements in the same order, and
`max` trimming exactly as today.

Add coverage in `packages/query-core/src/__tests__/utils.test.tsx`.

Scope: `packages/query-core/src/utils.ts` and its test file. Do not modify any
other source file.
