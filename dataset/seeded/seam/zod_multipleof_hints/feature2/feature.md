# Say which step a value looks like it was typed against

A form that accepts several step sizes wants to guess which one the user meant.

Add to `src/hints.ts`:

```ts
likeliestStep(value: number, steps: Array<number>): number | undefined
```

It returns the step from `steps` that `value` is a multiple of, preferring the
largest such step, or `undefined` when it is a multiple of none of them.

Scope: `src/hints.ts`.
