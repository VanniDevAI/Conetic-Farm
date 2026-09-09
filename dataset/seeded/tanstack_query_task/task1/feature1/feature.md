# Report staleness age, not just "stale"

`timeUntilStale(updatedAt, staleTime)` in `packages/query-core/src/utils.ts`
answers "how long until this data goes stale". It currently clamps its result at
zero, so once data *has* gone stale every answer is the same: `0`.

Devtools wants to show how long ago a query went stale — "stale for 3m" — and
that information is thrown away by the clamp.

Change `timeUntilStale` to return the **signed** remaining time: positive while
the data is still fresh, and negative once it has gone stale, by however long.
A missing `staleTime` continues to count as zero.

Scope: `packages/query-core/src/utils.ts`.
