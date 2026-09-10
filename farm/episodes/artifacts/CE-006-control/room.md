
## The room

This section is generated from the repository, not written for you. It says
what the code you are about to touch already relies on, what names are already
taken, and who is relying on you.

### What this code assumes

* `prisma` — defined at `prisma/seed.ts:8`
* `publicProcedure` — defined at `src/server/trpc.ts:38`
* `trpc` — defined at `src/utils/trpc.ts:48`

### Who looks at it — check these before you change a shape

* `src/server/routers/_app.ts:7` — uses postRouter

### What is already claimed

Other work lands in the same namespaces. These are taken; picking one of them
again is a collision nobody's tests will report.

* migrations already present: `20211019164222_init`, `20220307124425_non_unique_timestamps`, `20220918091608_pagination`, `20220918134120_revert`
* route names already registered: `add`, `byId`, `healthcheck`, `list`, `post`
* config keys already defined: `DATABASE_URL`, `NODE_ENV`

### Before you write anything

1. Write down, in one short list, what your change assumes about the code above
   — the shapes it reads, the names it adds, the tables it touches.
2. Check each assumption against the two lists above. Say explicitly which of
   your assumptions the room confirms and which it does not cover.
3. Only then start editing.

Do not skip step 1 because the task looks small. The failures this exists to
prevent all look small from inside one branch.
