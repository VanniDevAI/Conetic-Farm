# Let the caller choose how posts are sorted

The post list is always newest first. Let a caller ask for oldest first or
alphabetically by title instead, defaulting to what it does today.

Expose it through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
