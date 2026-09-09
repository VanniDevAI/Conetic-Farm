# Let readers react to a post

Add reactions: a reader picks one of a small fixed set (say a like, a celebrate
and a thinking face) and a post can be asked for its totals per reaction.

Expose it through the API the app already uses. A reader may change their
reaction but should not be able to count twice.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
