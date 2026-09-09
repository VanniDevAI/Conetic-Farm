# The step B consumer: trpc/examples-next-prisma-starter, a real app that
# depends on @trpc/server as a published package. Nothing here is seeded; the
# adaptations below exist only so the repository can build and test in this
# environment, and each is committed so agents start on a clean tree.
FROM conetic-farm/node22-base:local

WORKDIR /workspace
RUN git clone https://github.com/trpc/examples-next-prisma-starter.git repo && \
    cd repo && git checkout 2ce20676b3e80143713820b19277e87824be074c

WORKDIR /workspace/repo

# 1. The repository floats its tRPC dependencies on the `canary` tag, so two
#    builds a day apart do not install the same provider. They are pinned to
#    the published version the claim map indexes, 11.18.0.
# 2. Tests run against SQLite. The declared datasource is Postgres, and Debian
#    mirrors are off this environment's egress allowlist so no Postgres can be
#    installed. The migration files under prisma/migrations are left exactly as
#    they are -- they are Postgres SQL, they are never executed here, and they
#    are the surface the migration-ordinal grader reads.
RUN node -e "const f='package.json',p=require('./'+f); \
      for (const k of Object.keys(p.dependencies||{})) \
        if (k.startsWith('@trpc/')) p.dependencies[k]='11.18.0'; \
      require('fs').writeFileSync(f, JSON.stringify(p,null,2)+'\n')" && \
    sed -i 's/provider = \"postgres\"/provider = \"sqlite\"/' prisma/schema.prisma && \
    git -c user.email=farm@local -c user.name=farm commit -qam \
      "build: pin tRPC to 11.18.0 and point the test datasource at sqlite"

RUN npm install -g pnpm@9 --loglevel=error && \
    pnpm install --no-frozen-lockfile --loglevel=error && \
    printf 'DATABASE_URL="file:/workspace/repo/prisma/dev.db"\nNODE_ENV="test"\n' > .env && \
    npx prisma db push --skip-generate && \
    npx prisma generate && \
    cp -r node_modules /workspace/node_modules_cache && \
    cp .env /workspace/env.cache && \
    cp prisma/dev.db /workspace/dev.db.cache && \
    test -z "$(git status --porcelain --untracked-files=no)"

COPY runner.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/runner.sh
ENTRYPOINT ["/usr/local/bin/runner.sh"]
