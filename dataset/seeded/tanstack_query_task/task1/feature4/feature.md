# Keep infinite-query pages ordered by page param

Feeds that fetch pages out of order (a websocket backfill arriving while the
user scrolls) end up with pages in arrival order rather than page order, so the
rendered list jumps around.

Add an exported helper to `packages/query-core/src/infiniteQueryBehavior.ts`:

```ts
appendPageSorted(data, page, param, maxPages?)
```

It appends the new page and param using the module's existing page-append
helpers, then arranges the pages so they are ordered by their page param, and
returns the updated `InfiniteData`. Honour `maxPages` exactly as the append
helpers already do.

Add tests in
`packages/query-core/src/__tests__/infiniteQueryBehavior.test.tsx` covering an
out-of-order page and the `maxPages` case.

Scope: `packages/query-core/src/infiniteQueryBehavior.ts` and its test file. Do
not modify any other source file.
