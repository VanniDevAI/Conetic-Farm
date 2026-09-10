# Say how far off a `multipleOf` failure was

When a number fails a `multipleOf` check, the issue records the divisor and the
input but not the gap between them, so an error message can only say "not a
multiple of 0.5" — never "off by 0.2". Form libraries rendering the message have
to recompute it.

In `packages/zod/src/v4/core/checks.ts`, extend the issue raised by
`$ZodCheckMultipleOf` with a `remainder` field: the distance from the value to
the nearest multiple of the divisor, in the value's own units and always
positive. Leave it `undefined` for `bigint` values, where the existing exact
check already tells the whole story.

**Do not change when the issue is raised** — only what it carries. Values that
are accepted today must still be accepted.

Scope: `packages/zod/src/v4/core/checks.ts`.
