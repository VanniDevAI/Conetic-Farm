# c05 — plan and cost, before any spend

Total ceiling **$15**, enforced against the OpenRouter meter, read before every
agent. Step A stops at $5 of its own; step B stops at whatever the ceiling
leaves.

## Step A — the same two seeds across a real package seam

The claim under test is narrow: `s04` produced two semantic integration
failures, but the ownership boundary was constructed at module granularity,
because neither pair has a package seam. Step A asks whether a real one — a
published package installed from the registry — does the same work.

### Setup

| | lane A (provider) | lane B (consumer) |
|---|---|---|
| repository | the provider monorepo, **unmodified**, full tree | a separate consumer package |
| sees the other side | no, it is a different repository | only as built JavaScript in `node_modules` |
| provider version | its own source | from the registry, pinned to the provider's base commit |
| cuts, mounts | **none** | **none** |

`@tanstack/query-core@5.102.8` and `zod@4.5.4` are both published and are the
exact versions of the two base commits, so the consumer's dependency is the
real artifact rather than a stand-in.

Grading changes shape, because two repositories cannot conflict:

* **A alone** — provider repo, A's patch, the provider's own graded tests.
* **B alone** — consumer repo, B's patch, provider installed from the registry.
* **merge** — clean by construction; there is no shared path. Recorded as
  `clean` with that reason attached, not inferred from a merge that ran.
* **integrated** — consumer repo, B's patch, with the provider rebuilt from A's
  patch (`tsdown` / `zshy`), packed with `npm pack`, and installed over the
  registry copy. This is the run that decides the episode.
* **stealth flag** — whether A's patch leaves the provider repository's own
  full suite green. If it does not, the failure was catchable on A's branch and
  the episode is not stealthy.

### Two arms, two predictions, frozen here

The two seeds are not symmetric, and the asymmetry is the point.

| | contract A changes | exported? | prediction |
|---|---|---|---|
| pair 1, query-core | `timeUntilStale` | **no** — not in `index.ts` | **null** |
| pair 2, zod | `floatSafeRemainder` | **yes** — `export * as util` from `core` | **fires** |

Pair 1's contract is internal. A working in the full monorepo can see
`query.ts::isStaleByTime`, and in `s03` it repaired exactly that. Once repaired,
the public API behaves identically and no downstream consumer can break. If
that is what happens, the finding is that a package seam is *not* sufficient on
its own: the contract has to cross it.

Pair 2's contract is public — `core.util.floatSafeRemainder` is reachable by any
consumer of `zod/v4/core`. A can repair every in-repo caller it likes; a
downstream caller of the function itself still breaks. If pair 2 fires, the
constructed-boundary caveat is gone for that episode.

### Cost

| | agents | basis | estimate |
|---|---|---|---|
| lane A × 2 | Sonnet, full monorepo, no coop protocol | between s04's trimmed tree ($0.03–$0.56) and s03's monorepo with the peer-merge protocol ($1.3–$2.1) | $0.8–1.5 each |
| lane B × 2 | Sonnet, small consumer package | s04's B lanes, $0.08–$1.22 | $0.3–0.8 each |
| **total** | 4 | | **$2.2–4.6** |

Hard stop at **$5**. Provider builds, packing and grading cost nothing.

## Step B — unseeded, field-shaped

Three agents per episode, one `claude-sonnet-5` and two `qwen3-coder`, each in
its own container and its own branch, no channel. A scripted orchestrator hands
out three tasks that approach one shared surface from different directions. No
planted failure.

Graded by the claim map plus three convention graders, each of which catches a
class of collision that no test suite reports and no merge tool sees:

* **duplicate migration ordinals** — two branches add `0042_*`.
* **duplicate route paths** — two branches register the same path on the same
  method.
* **duplicate config keys** — two branches introduce the same env var, settings
  key or feature flag with different defaults.

For anything that fires, the episode records the **stealth flag**: whether the
first branch's own full repository suite would have failed. That is the number
that separates "a claim map found it" from "CI would have found it anyway".

### Cost

| | count | basis | estimate |
|---|---|---|---|
| Sonnet lane | 1 per episode | $1.0–2.0 on a real repository | $1.0–2.0 |
| qwen3-coder lanes | 2 per episode | s01 sweep, ~$0.15–0.5 each | $0.3–1.0 |
| **per episode** | 3 agents | | **$1.3–3.0** |
| **three episodes** | 9 agents | | **$4–9** |

Hard stop at **$10**, or at whatever $15 minus step A's actual spend leaves,
whichever is smaller.

### Corpus — three candidates, one to be picked before B starts

All three are provider/consumer pairs where the consumer is a real application
with real work to do, so the tasks can be ordinary feature requests rather than
planted ones.

**1. Django (provider) + `django-oscar` (consumer)**
Best coverage: per-app `migrations/` with numbered ordinals, URL route tables in
`apps/*/apps.py`, and a large settings surface. Long-lived project, dense test
suite, three tasks can easily touch one checkout flow from different sides.
Cost: the heaviest image of the three, and the slowest suite.

**2. Flask (provider) + `flask-appbuilder` (consumer)**
Alembic migration ordinals, an explicit `add_view` route table, and a
`config.py` key surface — all three graders bite, on a much lighter image than
option 1. Smaller test suite, so the stealth flag is less informative: fewer
collisions would have been caught by CI either way.

**3. FastAPI (provider) + `fastapi-users` (consumer)**
Lightest and fastest. Route tables are first-class (`APIRouter` prefixes and
paths), config keys are Pydantic settings. Migrations only appear in the
consumer's own alembic setup, so the migration-ordinal grader has the least to
work with. Best choice if the priority is more episodes rather than richer
surfaces.

Recommendation: **option 2**, on the grounds that all three graders bite and the
image cost leaves room for three episodes rather than two. Option 1 if the
migration-ordinal class is the one that matters most.
