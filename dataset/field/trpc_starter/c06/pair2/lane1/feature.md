# Keep drafts out of the public list

Everything written is immediately public. Give a post a way to be a draft, keep
drafts out of the list readers see, and let a draft be published.

Expose the change through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
