# Group queries by key namespace

Devtools needs to show queries grouped by their key namespace — every query
under `['todos', ...]` together, every query under `['users', ...]` together.

Add a method to `QueryCache` in `packages/query-core/src/queryCache.ts`:

```ts
findAllByKeyPrefix(prefix: QueryKey): Array<Query>
```

It returns every query in the cache whose key begins with `prefix`.

Each query carries its stored hash on `query.queryHash`. That hash is the JSON
serialization of the query key, so the namespace can be read straight back out
of it — parse the hash and compare the leading segments against `prefix`.

Add tests in `packages/query-core/src/__tests__/queryCache.test.tsx` covering a
namespace with several queries and a namespace with none.

Scope: `packages/query-core/src/queryCache.ts` and its test file. Do not modify
any other source file.
