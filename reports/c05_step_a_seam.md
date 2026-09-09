# c05 step A — the wall is real, but only for a contract that crosses it

Two arms, two predictions frozen before the run, **both correct**. $1.7625 of a
$5 stop, and $13.24 of the $15 ceiling left for step B.

| | query-core arm | zod arm |
|---|---|---|
| prediction | **null** | **fires** |
| observed | **null** | **fires**, semantic |
| A alone, provider's own tests | pass | pass |
| B alone, provider from the registry | pass | pass |
| merge | clean by construction | clean by construction |
| **integrated** | **pass** | **fail** |
| A's own full repo suite | pass | pass |
| **stealth flag** | n/a | **stealthy** |
| cost | $0.4482 | $1.3143 |

## What changed from `s04`

Everything about the isolation, and nothing about the seeds.

The consumer is now its own repository, depending on the provider as a
published package installed from the registry —
`@tanstack/query-core@5.102.8` and `zod@4.5.4`, the exact versions of the two
base commits. The provider agent works in its own monorepo, whole and
unmodified: no file removed, no path mounted, no leak check. The two agents
cannot see each other for the ordinary reason that they are in different
repositories.

Because two repositories share no path, the merge is clean by construction and
is recorded that way with the reason attached, rather than inferred from a
merge that ran. The episode is decided by the integrated run: the provider is
rebuilt from the provider agent's own patch (`tsdown`, `zshy`), packed with
`npm pack`, and installed over the registry copy before the consumer's graded
tests run.

## The zod arm: the caveat is gone

`integrated=fail` with `a_alone=pass`, `b_alone=pass`, a clean merge, and the
provider's own full suite green. No construction anywhere in the chain.

The provider agent did what it did in every previous run: it audited its own
call sites and repaired them. Its patch touches three files —
`core/util.ts` as briefed, plus `core/checks.ts` and `core/compile.ts`, the two
in-repo consumers. zod's public `z.number().multipleOf()` behaviour is
therefore unchanged, and zod's own suite passes.

What it could not repair is the function itself. `core/index.ts` carries
`export * as util`, so `core.util.floatSafeRemainder` is part of zod's published
surface, and the downstream package calls it directly to stay consistent with
zod's own float handling:

```ts
export function isMultipleOf(value: number, step: number): boolean {
  return core.util.floatSafeRemainder(value, step) === 0
}
```

Once the snap is gone, `2.03` stops being a multiple of `0.07` for that caller
and only for that caller. **Both branches are green; the product is broken.**
That is the class stated in its strongest form, and nothing about the setup was
arranged to produce it beyond choosing a contract that is exported.

## The query-core arm: a seam is not enough on its own

`integrated=pass`. The prediction was that this would null, and why.

`timeUntilStale` is not in query-core's `index.ts`. The provider agent, seeing
its whole monorepo, repaired `query.ts::isStaleByTime` alongside its briefed
change, exactly as it did in `s03`:

```diff
-    return !timeUntilStale(this.state.dataUpdatedAt, staleTime)
+    return timeUntilStale(this.state.dataUpdatedAt, staleTime) <= 0
```

`Query#isStaleByTime` is the public surface, and after the repair it answers
identically. The downstream package consumes it through
`stalenessRows`, gets the same answers it always got, and passes.

This is the useful half of the result. In `s04` the same seed fired, because
the consumer had been removed from the provider's disk and the repair was
impossible. Across a real seam the repair happens and the failure does not.
**The constructed boundary was doing the work in that episode**, and this arm
is what shows it.

## The rule the two arms give

A coordination failure crosses a package boundary only when the contract that
changed is **on the published surface**. Everything else is caught by the
provider's own call-site audit, which a capable agent performs unprompted and
performs well — four for four across `s03`, `s04` and here.

That is a sharper claim than "isolation causes integration failure", and it is
directly actionable for step B: the shared surfaces worth watching are the ones
that are *exported* — a route table, a migration sequence, a config key
namespace, a published helper — not internal call graphs, which the author
repairs.

It also reframes the `s04` result. Both `s04` episodes are real semantic
failures under their stated setup, but only the zod one survives contact with a
real package boundary. `docs/COORDINATION_EPISODES.md` now records the seam
runs as CE-003 and CE-004 with that distinction attached.

## Stealth

Both provider patches leave their own repository's full suite green, so in
neither arm would the provider's CI have caught anything. In the zod arm that
makes the failure genuinely stealthy: green on A's branch, green on B's branch,
broken when combined. The `s03` limitation — that gold A was red on the
provider's own suite — is gone, because the agents repaired what the gold
patches did not.

## One harness defect, found and fixed

CooperBench's task discovery skips any task carrying fewer than two features
(`runner/tasks.py`: `if len(feature_ids) < 2: continue`). Both consumer
packages had exactly one, so the first pass lost both consumer lanes with
"no tasks found" after the provider lanes had already been paid for. Each
consumer now carries a second, unrelated feature, and the runner reuses a
lane's patch when one is already on disk rather than paying for it twice. The
zod consumer lane picked up the fix mid-run; the query-core one was recovered
by a resumed pass costing $0.0444.

## Spend

| | |
|---|---|
| step A | **$1.7625** |
| step A stop | $5.00 |
| ceiling | $15.00 |
| left for step B | **$13.24**, capped at $10 by the plan |

## Artifacts

| what | where |
|---|---|
| per-arm results, patches, transcripts | `/home/user/farm-c05a/` |
| the plan with both frozen predictions | `config/c05_step_a.json` |
| the two consumer packages | `dataset/seeded/seam/` |
| the runner | `scripts/run_seam_pair.py` |
