# Let an editor pin a post to the top

Editors want one or two posts held at the top of the list regardless of when
they were written. Give a post a way to be pinned, and make the list respect it
before falling back to newest first.

Expose the change through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
