# Tell the user how far off they are

`src/hints.ts` can say whether a value is a multiple of a step, and phrase that
as a sentence. A form needs one step more: when the value is wrong, offer the
nearest acceptable value so the field can show "did you mean 1.5?".

Add to `src/hints.ts`:

```ts
nearestMultiple(value: number, step: number): number
hintFor(value: number, step: number): { ok: boolean; nearest: number; offBy: number }
```

* `nearestMultiple` returns the multiple of `step` closest to `value`.
* `hintFor` reports whether the value is acceptable, the nearest multiple, and
  the distance to it. `offBy` is always positive, and is `0` when the value is
  acceptable.

Use the module's existing acceptability check for `ok` rather than writing a
second one, so a value the form accepts and a value the hint calls acceptable
are always the same value.

Scope: `src/hints.ts`.
