# Count the stale queries, not just list them

`src/digest.ts` builds the staleness panel's rows and can filter them down to
the stale ones. The panel header needs a number rather than a list: "4 of 17
stale".

Add to `src/digest.ts`:

```ts
countStale(client: QueryClient, staleTime?: number): number
```

It returns how many cached queries count as stale for the given `staleTime`,
which defaults to `0`.

Build it on the module's existing row computation rather than reaching into the
cache again, so the header and the table can never disagree about what is
stale.

Scope: `src/digest.ts`.
