# Show a single author's posts

Readers who like a writer have no way to see the rest of their work. Posts do
not record who wrote them yet, so start there, then add a way to ask for one
author's posts, newest first, a page at a time.

Expose it through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
