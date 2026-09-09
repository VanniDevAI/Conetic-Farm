# Count how often a post is read

Product wants to know which posts get read. Record a view each time a post is
fetched by id, and let a post be asked for its view count.

Recording views should be something an operator can turn off without a code
change.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
