import type { QueryClient } from '@tanstack/query-core'

/**
 * One row of the staleness panel: what the devtools table renders per query.
 */
export interface StalenessRow {
  queryHash: string
  isStale: boolean
  dataUpdatedAt: number
}

/**
 * Build the panel's rows from a client's cache.
 *
 * Staleness comes from the query itself rather than being recomputed here, so
 * the panel and the cache can never disagree about whether something is stale.
 */
export function stalenessRows(client: QueryClient, staleTime = 0): Array<StalenessRow> {
  return client
    .getQueryCache()
    .getAll()
    .map((query) => ({
      queryHash: query.queryHash,
      isStale: query.isStaleByTime(staleTime),
      dataUpdatedAt: query.state.dataUpdatedAt,
    }))
}

/**
 * The rows a "stale only" filter would show.
 */
export function staleRows(client: QueryClient, staleTime = 0): Array<StalenessRow> {
  return stalenessRows(client, staleTime).filter((row) => row.isStale)
}
