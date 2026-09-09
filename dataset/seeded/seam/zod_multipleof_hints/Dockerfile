# A consumer package, in its own image, depending on the provider as a published
# artifact from the registry. Nothing of the provider's source is present: only
# the built JavaScript npm installs into node_modules, which is exactly what a
# downstream maintainer has.
#
# The Farm's own Node 22 base, because this environment's network policy denies
# Docker Hub's layer CDN. It carries node 22, npm and git.
FROM conetic-farm/node22-base:local

WORKDIR /workspace
COPY repo /workspace/repo
WORKDIR /workspace/repo

RUN git init -q \
    && git config user.email farm@local && git config user.name farm \
    && git add -A && git commit -qm "base: the consumer package at the provider's old version"

RUN npm install --no-audit --no-fund --loglevel=error \
    && cp -r node_modules /workspace/node_modules_cache \
    && test -z "$(git status --porcelain --untracked-files=no)"

COPY runner.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/runner.sh

ENTRYPOINT ["/usr/local/bin/runner.sh"]
