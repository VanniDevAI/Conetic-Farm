# Render a row as a line of text

The panel needs a plain-text form of a row for its copy-to-clipboard button and
for snapshot tests.

Add to `src/digest.ts`:

```ts
formatRow(row: StalenessRow): string
```

It returns `"<queryHash> stale"` for a stale row and `"<queryHash> fresh"` for a
fresh one.

Scope: `src/digest.ts`.
