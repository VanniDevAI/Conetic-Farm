# c05 step B — three TypeScript corpus candidates, measured

Requirements: the consumer is a separate repository or a published package, and
it has real migrations, routes or config namespaces so the convention graders
have something to bite on. All three are TypeScript end to end, so the claim map
runs on both sides.

Numbers below are measured from blobless clones at HEAD, not estimated, except
where marked. Every image starts from `conetic-farm/node22-base:local` (6.61 GB),
because this environment's network policy denies Docker Hub's layer CDN — so
the figure that matters is the delta the dependency install adds.

---

## Candidate A — `documenso/documenso`

A Prisma-backed app depending on internal workspace packages.

| | |
|---|---|
| provider | `@documenso/lib` (workspace package), or `@documenso/prisma` |
| consumer | `apps/remix` |
| checkout | 152 MB |
| workspace packages | 17 `package.json` files, **383 declared dependencies** |
| image (estimate) | 6.61 GB base + **~2–3 GB** install ≈ **9–10 GB** |
| episode cost at 3 agents (estimate) | **$2.8 – 4.9** |

### Which graders bite

| grader | verdict |
|---|---|
| duplicate migration ordinals | **strong** — 165 timestamped Prisma migration directories, the densest surface of the three |
| duplicate route paths | **strong** — ~20 domain tRPC routers plus the Remix route tree |
| duplicate config keys | **strong** — `.env.example` plus `packages/lib/constants` |

### Claim map

Attaches cleanly. Internal packages are TypeScript with explicit entry points,
so `farm/identity.py` indexes both sides and `farm/surface.py` can answer the
published-surface attribute for the workspace boundary.

### The problem with it

**The stealth flag would be nearly uninformative.** The whole repository carries
11 test files, the root `package.json` declares no test script, and the real
suite is Playwright end-to-end under `packages/app-tests`, which needs a running
app and a Postgres instance. A flag that reads "stealthy" because the repository
barely tests anything is not measuring stealth.

It is also the only candidate that would need Postgres in the image for any
suite at all, which is real infrastructure work before the first episode.

---

## Candidate B — `trpc/trpc` (provider) + `trpc/examples-next-prisma-starter` (consumer)

A tRPC API and its consuming app, across a published package boundary.

| | |
|---|---|
| provider | `trpc/trpc`, published as `@trpc/server@11.18.0` |
| consumer | `trpc/examples-next-prisma-starter` |
| provider checkout | 15 MB, **182 test files** |
| consumer checkout | 788 KB, 32 declared dependencies |
| image (estimate) | provider **~7.5 GB**, consumer **~7.5 GB** |
| episode cost at 3 agents (estimate) | **$1.4 – 2.8** |

### Which graders bite

| grader | verdict |
|---|---|
| duplicate migration ordinals | **yes, thin** — 4 timestamped Prisma migration directories; the class is present but three agents adding to a 4-entry sequence is a small surface |
| duplicate route paths | **strong** — tRPC procedure paths are the route table, and they are declared, not file-derived |
| duplicate config keys | **yes** — env keys through the app's config module |

### Claim map

Attaches cleanly, and this is the only candidate where the seam is the same
shape as CE-004: a published package with a defined export surface, consumed by
a separate repository. The published-surface attribute is directly meaningful.

### Why it is the recommendation

All three graders bite, and the provider carries **182 test files**, so the
stealth flag is measured against a suite that could plausibly have caught
something. That is the flag's whole point, and it is the axis on which candidate
A fails.

Three episodes fit inside the cap with room to spare.

---

## Candidate C — `honojs/hono` (provider) + `honojs/middleware` (consumer)

The lightest option, and the densest suites.

| | |
|---|---|
| provider | `honojs/hono`, published as `hono@4.13.7` |
| consumer | `honojs/middleware` — 46 packages, **45 of which declare `hono` as a peer dependency** |
| provider checkout | 8.3 MB, **138 test files** |
| consumer checkout | 6.3 MB, **74 test files** |
| image (estimate) | **~7.1 GB** each |
| episode cost at 3 agents (estimate) | **$1.1 – 2.1** |

### Which graders bite

| grader | verdict |
|---|---|
| duplicate migration ordinals | **no** — there is no migration surface anywhere in either repository |
| duplicate route paths | **strong** — middleware registers paths and methods; this is the route-table class in its natural habitat |
| duplicate config keys | **yes** — middleware option namespaces |

### Claim map

Attaches cleanly, and the peer-dependency relation across 45 packages gives an
unusually large number of genuine provider/consumer edges to draw tasks from.

### The trade

No migration class at all, so one of the three convention graders would be
dead weight. In exchange it is the cheapest, the fastest to build, needs no
database, and has the densest suites on both sides — which would make the
stealth flag the most informative of the three.

---

## Side by side

| | A. documenso | B. tRPC pair | C. hono pair |
|---|---|---|---|
| image | 9–10 GB | ~7.5 GB ×2 | ~7.1 GB ×2 |
| episode cost, 3 agents | $2.8–4.9 | $1.4–2.8 | $1.1–2.1 |
| episodes inside $10 | 2 | **3, with room** | 4–5 |
| migration ordinals | strong (165) | thin (4) | none |
| route paths | strong | strong | strong |
| config keys | strong | yes | yes |
| provider suite | 11 files, no root script | **182 files** | **138 files** |
| stealth flag informative | **no** | **yes** | **yes** |
| needs a database | yes | for e2e only | no |
| claim map attaches | yes | yes, same shape as CE-004 | yes |

**Recommendation: B.** It is the only candidate where all three graders bite
*and* the stealth flag is measured against a suite dense enough for the flag to
mean anything, and its seam is the same shape as the one episode that has
already produced a stealthy semantic failure. Take C instead if the migration
class does not matter and more episodes do; take A only if migration ordinals
are the priority and a weak stealth flag is acceptable.

---

## Step B design, unchanged from the brief

Three agents per episode — one `claude-sonnet-5`, two `qwen3-coder` — each in
its own container, on its own branch, with no channel. A scripted orchestrator
hands out three tasks that approach one shared surface from different
directions. **No planted failures**: overlap is seeded only on exported
surfaces, routes, migrations and config, and whether anything collides is the
measurement.

Grading:

* the **claim map**, resolved through the identity graph, with the
  published-surface attribute on every claim;
* **duplicate migration ordinals** — two branches adding the same sequence
  number;
* **duplicate route paths** — the same path and method registered twice;
* **duplicate config keys** — the same env var, settings key or feature flag
  introduced twice with different defaults;
* the **stealth flag** on every episode: whether the first branch's own full
  repository suite would have failed.

## Cost plan inside the remaining $13.24

| | |
|---|---|
| spent so far, `c05` | $1.7625 (step A) |
| remaining of the $15 ceiling | **$13.24** |
| step B cap | **$10**, hard stop against the meter |
| unallocated headroom | $3.24 |

Per candidate, three episodes:

| | 3 episodes | fits $10 |
|---|---|---|
| A. documenso | $8.4 – 14.7 | **no** — two episodes at most |
| B. tRPC pair | $4.2 – 8.4 | **yes** |
| C. hono pair | $3.3 – 6.3 | yes, and a fourth would fit |

The meter is read before every agent, as in step A, and the run stops rather
than starting an agent that could take spend past the cap.
