# Seeded semantic pair 2 — zod `packages/zod`

One task, two features, one image. `f1` is agent A, `f2` is agent B.
Base commit `eb1c1089f7f9469078839f6e443830f7e3fdc06b`.

## Shape: the consumer is inherited, not written fresh

Same shape as pair 1. B extends a check that has called the provider since
long before either agent started, and is never told what the provider does.

| | agent A (provider) | agent B (consumer) |
|---|---|---|
| source file | `packages/zod/src/v4/core/util.ts` | `packages/zod/src/v4/core/checks.ts` |
| graded tests | `core/tests/float-safe-remainder.test.ts` (new) | `classic/tests/number.test.ts` (existing) |
| change | `floatSafeRemainder` returns the raw signed difference; the tolerance is exported as `multipleOfTolerance` for callers to apply | the `not_multiple_of` issue gains a `remainder` field |
| told about the other side | no | no |

File overlap: **none**. Verified: both feature patches apply in sequence with
no conflict.

## The inherited dependency (this is the claim map's own content)

```
provider   packages/zod/src/v4/core/util.ts   :: floatSafeRemainder(val, step)
consumer   packages/zod/src/v4/core/checks.ts :: $ZodCheckMultipleOf
edge       checks.ts:173  ->  util.floatSafeRemainder(payload.value, def.value) === 0
```

`=== 0` is only a correct multiple test while `floatSafeRemainder` snaps a
near-whole quotient to exactly zero. `2.03 / 0.07` is a whole number in decimal
and not in binary floating point, so once A hands back the raw difference the
check rejects a value zod has always accepted.

B's brief says what to add to the issue and states that values accepted today
must still be accepted. It never mentions `floatSafeRemainder`, `util.ts`, or
the tolerance. B never opens the provider.

## Gold validation (no model spend, on the harness-built image)

| run | expected | observed |
|---|---|---|
| A alone, A's tests | pass | **pass** |
| B alone, B's tests | pass | **pass** |
| merged, A's tests | pass | **pass** |
| merged, B's tests | **fail** | **fail** — 5 tests, incl. `expected false to be true` |

## Known limitation: A alone is red on the repository's own suite

Measured against the whole `zod` project, not just the graded file:

| tree | result |
|---|---|
| base | 5360 passed / 5360 |
| A's feature + A's tests | **4 failed** / 5366 |
| B's feature + B's tests | 5364 passed / 5364 |

All four are in `classic/tests/number.test.ts`, all reaching
`floatSafeRemainder` through `$ZodCheckMultipleOf`. The same limitation applies
as in pair 1, for the same structural reason: see that file's closing section.

## Two build assumptions the image has to neutralise

Both are undone before the image is sealed, and the build asserts the tracked
tree is unmodified afterwards.

1. `packageManager: nub@0.8.3`. corepack refuses the field outright, and pnpm
   then refuses it too ("This project is configured to use nub"). zod ships a
   pnpm lockfile and a plain vitest config, so nothing grading needs that
   wrapper.
2. The workspace is declared with npm's `workspaces` field. pnpm 9+ reads only
   `pnpm-workspace.yaml`; without one, `pnpm install` exits 0 in under a second
   having installed nothing at all — a silent no-op, not an error.

## One runner difference from pair 1

zod's per-package vitest config merges the root config, whose `projects` list
resolves relative to the working directory. Running vitest from
`packages/zod` therefore dies with "Projects definition references a
non-existing file". The runner starts from the repository root and narrows with
`--project zod`.
