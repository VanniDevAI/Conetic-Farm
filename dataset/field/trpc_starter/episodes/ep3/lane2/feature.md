# Stop one caller from flooding the API

Add rate limiting: a single caller gets a bounded number of calls in a window,
and gets a clear error once over it.

Both the bound and the window should be something an operator can change
without a code change.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
