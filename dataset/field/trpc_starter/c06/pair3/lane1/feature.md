# Say how many posts there are

The reader-facing list has no idea how many posts exist, so it cannot show
"1-20 of 143" or decide whether another page is worth fetching. Add a way to ask
for the total.

Expose it through the API the app already uses.

## Working agreement

* Keep `npx tsc --noEmit` clean and `npx vitest run` green.
* If you add or change a table, add a migration under `prisma/migrations/`
  following the naming convention already in that directory.
* Anything a deployment might want to tune belongs in the env schema in
  `src/server/env.ts`, not hard-coded.
* You are working alone on your own branch. Do not assume anything about work
  happening elsewhere.
