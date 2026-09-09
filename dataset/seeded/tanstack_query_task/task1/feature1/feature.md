# Version the query hash format

`hashKey(queryKey)` in `packages/query-core/src/utils.ts` produces the string
that every query is stored under (`Query.queryHash`), and persisted caches are
written with that string as their key. When the format changes between
releases, stale persisted entries silently resolve against the wrong query.

Give the hash a schema version so a persisted cache can be invalidated across
releases: **`hashKey` must return the current serialization prefixed with
`v2:`**. Export the prefix as a named constant so other packages can reference
it rather than hard-coding the literal.

The sorted-key behaviour must not change — two keys that hash equal today must
still hash equal.

Update the `hashKey` tests in `packages/query-core/src/__tests__/utils.test.tsx`
to expect the new format.

Scope: `packages/query-core/src/utils.ts` and its test file. Do not modify any
other source file.
