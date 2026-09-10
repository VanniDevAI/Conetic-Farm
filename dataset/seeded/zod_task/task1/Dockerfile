# Shaped like every other CooperBench task image: `FROM node:22-slim` plus the
# apt layer. scripts/build_task_image.sh rewrites both for this environment
# (registry blobs and Debian mirrors are off the egress allowlist) and records
# the rewrite in the episode manifest, so the seed stays comparable to the
# upstream tasks instead of hard-coding a local base.
FROM node:22-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED

WORKDIR /workspace
RUN git clone https://github.com/colinhacks/zod.git repo && \
    cd repo && \
    git checkout eb1c1089f7f9469078839f6e443830f7e3fdc06b

WORKDIR /workspace/repo
# Two upstream build assumptions have to be neutralised for the duration of the
# install, and both are put back before the image is sealed.
#
# 1. `packageManager: nub@0.8.3`. zod ships a pnpm lockfile and a plain vitest
#    config, so pnpm installs it and vitest runs it directly -- nothing here
#    needs that wrapper. But two layers enforce the field: corepack refuses
#    outright ("Unsupported package manager specification: nub@0.8.3"), and
#    pnpm itself then refuses ("This project is configured to use nub").
#    Deleting the field defeats both.
#
# 2. The workspace is declared with npm's `workspaces` field. pnpm 9+ reads
#    only pnpm-workspace.yaml, and without one `pnpm install` resolves nothing
#    at all -- it exits 0 in under a second having written no node_modules.
#    Writing one limited to `packages/zod` keeps the install to what grading
#    needs.
#
# `git checkout -- .` then restores package.json and the assertion fails the
# build if anything tracked is still modified, so neither agent sees a dirty
# tree and no agent patch can pick these edits up. Neither file is touched by
# either agent's feature patch or either graded test patch.
RUN npm install -g pnpm@9 && \
    node -e "const f='package.json',p=require('./'+f);delete p.packageManager;require('fs').writeFileSync(f,JSON.stringify(p,null,2))" && \
    printf 'packages:\n  - "packages/zod"\n' > pnpm-workspace.yaml && \
    pnpm install --filter "zod..." --ignore-scripts --no-frozen-lockfile && \
    rm -f pnpm-workspace.yaml && \
    cp -r node_modules /workspace/node_modules_cache && \
    (cp -r packages/zod/node_modules /workspace/zod_node_modules_cache || true) && \
    git checkout -- . && \
    test -z "$(git status --porcelain --untracked-files=no)"

COPY runner.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/runner.sh

ENTRYPOINT ["/usr/local/bin/runner.sh"]
