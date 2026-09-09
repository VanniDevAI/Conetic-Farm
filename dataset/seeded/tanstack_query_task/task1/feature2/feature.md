# A staleness summary for devtools

Devtools renders a per-query row and needs three facts together: whether the
query counts as stale for a given `staleTime`, when its data last arrived, and
whether it has data at all. Today it has to reach for each separately.

Add a method to `Query` in `packages/query-core/src/query.ts`:

```ts
getStalenessReport(staleTime?: StaleTime): {
  isStale: boolean
  dataUpdatedAt: number
  hasData: boolean
}
```

* `isStale` — whether this query counts as stale for the given `staleTime`.
  Use the query's own existing staleness determination rather than
  recomputing it, so the report and the query never disagree.
* `dataUpdatedAt` — from the query's state.
* `hasData` — whether the query currently holds data.

`staleTime` defaults to `0`, matching the query's other staleness methods.

Scope: `packages/query-core/src/query.ts`.
