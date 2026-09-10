# Let callers decide the float tolerance for `multipleOf`

`floatSafeRemainder(val, step)` in `packages/zod/src/v4/core/util.ts` divides
`val` by `step` and reports how far the quotient sits from a whole number. It
currently applies a hard-coded epsilon internally and, when the difference is
inside it, returns exactly `0` — hiding the real difference from every caller.

That is the wrong place for the decision. A caller validating user input and a
caller generating a JSON Schema want different tolerances, and neither can see
what was discarded.

Two changes:

* `floatSafeRemainder` returns the **raw signed difference** between the
  quotient and the nearest whole number, with no snapping.
* export `multipleOfTolerance(ratio)` returning the scaled epsilon that was
  previously applied internally, so a caller can apply it deliberately.

Scope: `packages/zod/src/v4/core/util.ts`.
