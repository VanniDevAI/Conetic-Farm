# Sandbox-enforced ownership, and what the repository's layout allows

Step 3 asks that the ownership boundary be enforced by the sandbox rather than
by the brief. Neither seeded pair has a package seam to enforce: in both, the
provider and the consumer are peers inside one tightly coupled core package,
and the provider's own file *type*-imports the consumer. So the boundary is cut
at module granularity, by two different mechanisms, because the two sides need
opposite things.

## Agent A — the consumer is removed from the image

`scripts/workspace/trim_workspace.py` deletes the consumer and every file that
reaches it through a **runtime** import, then commits, so A starts on a clean
tree. `import type` edges are not followed: they vanish at compile time, and
following them would delete the provider itself.

Verified in the built image, not asserted:

| pair | A keeps | removed | forbidden name found outside A's own file |
|---|---|---|---|
| query-core | `src/utils.ts` | 201 files incl. `query.ts` | `isStaleByTime`: **none** |
| zod | `core/util.ts` | 275 files incl. `checks.ts` | `floatSafeRemainder`: **none** |

`timeUntilStale` survives only at its own definition in `utils.ts`. In both
images a scratch vitest run importing the provider passes, so A can still test
what it changes — it simply has no repository suite to run, because that suite
lives on the other side of the boundary. That is what working inside one
package of a split repository feels like, and it is the cost of the cut.

## Agent B — the provider is mounted read-only at the old version

B must still *use* the provider: the whole design has B building on the old
contract. What has to be prevented is B editing it. So B runs on the untrimmed
image with the provider's source bind-mounted read-only from the host at the
base commit. A read-only bind mount is enforced by the kernel and holds against
root inside the container, which `chmod` and `chattr` do not.

This needed a three-line change to the vendored CooperBench adapter, recorded
here and marked `[conetic-farm]` in the source: `DockerEnvironment` has always
accepted `run_args`, but the adapter only ever populated it in team mode, so an
`environment.run_args` key in the agent config was silently dropped.

## What is not enforced, and why

A can still read the provider's own *dependents' type declarations* where a
type-only edge kept a file alive. None of them names the consumer's method or
the provider's call site; that is what the leak check above tests. Beyond that,
nothing about the consumer's body is on A's disk.
