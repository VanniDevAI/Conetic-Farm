# Show the posts from a given stretch of time

An archive view needs the posts written between two dates, newest first, a page
at a time. Both bounds are optional: with neither, it is the whole history.

Expose it through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
