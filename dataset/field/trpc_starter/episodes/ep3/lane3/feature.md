# Require an API key on write operations

Reads stay open. Anything that changes data should require a shared secret sent
by the caller, and should fail with a clear error when it is missing or wrong.

The secret itself must come from the environment.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
