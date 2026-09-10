FROM node:22-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED

WORKDIR /workspace
RUN git clone https://github.com/TanStack/query.git repo && \
    cd repo && \
    git checkout 50680b98c4dc5ac4d97f7762014fa83f09a41d9a

WORKDIR /workspace/repo
# Only query-core and what it needs: a full monorepo install pulls every
# framework adapter and does not fit the disk this harness runs on.
RUN corepack enable && \
    pnpm install --filter "@tanstack/query-core..." --ignore-scripts && \
    cp -r node_modules /workspace/node_modules_cache && \
    cp -r packages/query-core/node_modules /workspace/qc_node_modules_cache 2>/dev/null || true

COPY runner.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/runner.sh

ENTRYPOINT ["/usr/local/bin/runner.sh"]
