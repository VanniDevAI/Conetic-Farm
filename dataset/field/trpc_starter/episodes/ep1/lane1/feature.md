# Let readers comment on a post

Readers can only read. Add comments: a reader supplies a body and an optional
display name, and a post can be asked for its comments newest first, a page at
a time.

Expose it through the API the app already uses, so the web client can call it
the same way it calls everything else.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
