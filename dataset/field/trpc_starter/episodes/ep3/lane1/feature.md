# Log every API call

Operators have no idea what the API is doing. Log each call with its procedure
path, whether it succeeded, and how long it took.

The amount of detail should be something an operator can turn down in
production without a code change.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
