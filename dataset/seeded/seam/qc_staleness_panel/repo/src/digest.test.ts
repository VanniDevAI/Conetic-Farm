import { QueryClient } from '@tanstack/query-core'
import { describe, expect, it } from 'vitest'

import { staleRows, stalenessRows } from './digest.js'

function clientWithOneQuery(ageMs: number): QueryClient {
  const client = new QueryClient()
  const cache = client.getQueryCache()
  const query = cache.build(client, { queryKey: ['todos'], queryFn: async () => 1 })
  query.setData(1, { updatedAt: Date.now() - ageMs })
  return client
}

describe('stalenessRows', () => {
  it('reports one row per cached query', () => {
    const rows = stalenessRows(clientWithOneQuery(0))
    expect(rows).toHaveLength(1)
    expect(rows[0]!.queryHash).toBe('["todos"]')
  })

  it('marks data older than staleTime as stale', () => {
    const rows = stalenessRows(clientWithOneQuery(60_000), 1_000)
    expect(rows[0]!.isStale).toBe(true)
  })

  it('leaves fresh data unmarked', () => {
    const rows = stalenessRows(clientWithOneQuery(0), 60_000)
    expect(rows[0]!.isStale).toBe(false)
  })
})

describe('staleRows', () => {
  it('keeps only the stale ones', () => {
    expect(staleRows(clientWithOneQuery(60_000), 1_000)).toHaveLength(1)
    expect(staleRows(clientWithOneQuery(0), 60_000)).toHaveLength(0)
  })
})
