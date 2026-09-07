#!/usr/bin/env bash
# Start Redis for CooperBench's coop-mode inter-agent messaging.
#
# Upstream says `docker run -p 6379:6379 redis:7`, which needs a registry pull.
# Registry blobs are blocked here, so we try, in order:
#   1. a redis-server already on the host
#   2. a redis-server installed in the local base image
#   3. building redis from source into a local image (source from github.com,
#      which IS on the egress allowlist)
set -euo pipefail

PORT="${FARM_REDIS_PORT:-6379}"
BASE_IMAGE="${FARM_BASE_IMAGE:-conetic-farm/node22-base:local}"
REDIS_IMAGE="conetic-farm/redis:local"
REDIS_VERSION="${FARM_REDIS_VERSION:-7.2.5}"

already_up() {
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT" && printf 'PING\r\n' >&3 && head -c7 <&3 | grep -q PONG) 2>/dev/null
}

if already_up; then echo "==> redis already answering on 127.0.0.1:$PORT"; exit 0; fi

if command -v redis-server >/dev/null 2>&1; then
  echo "==> starting host redis-server on :$PORT"
  redis-server --port "$PORT" --daemonize yes --save '' --appendonly no
  sleep 1; already_up && { echo "==> OK"; exit 0; }
fi

if docker run --rm "$BASE_IMAGE" /bin/sh -c 'command -v redis-server' >/dev/null 2>&1; then
  echo "==> starting redis from base image on :$PORT"
  docker rm -f conetic-farm-redis >/dev/null 2>&1 || true
  docker run -d --name conetic-farm-redis -p "$PORT:6379" "$BASE_IMAGE" \
    redis-server --save '' --appendonly no >/dev/null
  sleep 2; already_up && { echo "==> OK"; exit 0; }
fi

if ! docker image inspect "$REDIS_IMAGE" >/dev/null 2>&1; then
  echo "==> building redis $REDIS_VERSION from source (no registry pull)"
  BUILD_DIR="$(mktemp -d)"; trap 'rm -rf "$BUILD_DIR"' EXIT
  cat > "$BUILD_DIR/Dockerfile" <<DOCKERFILE
FROM $BASE_IMAGE
RUN set -e; \\
    git clone --depth 1 --branch $REDIS_VERSION https://github.com/redis/redis.git /tmp/redis; \\
    make -C /tmp/redis -j"\$(nproc)" MALLOC=libc redis-server redis-cli; \\
    cp /tmp/redis/src/redis-server /tmp/redis/src/redis-cli /usr/local/bin/; \\
    rm -rf /tmp/redis
EXPOSE 6379
ENTRYPOINT ["redis-server"]
DOCKERFILE
  docker build -t "$REDIS_IMAGE" "$BUILD_DIR"
fi

echo "==> starting $REDIS_IMAGE on :$PORT"
docker rm -f conetic-farm-redis >/dev/null 2>&1 || true
docker run -d --name conetic-farm-redis -p "$PORT:6379" "$REDIS_IMAGE" \
  --save '' --appendonly no >/dev/null
for _ in $(seq 1 20); do already_up && { echo "==> OK: redis on :$PORT"; exit 0; }; sleep 1; done
echo "FATAL: redis did not come up on :$PORT" >&2; exit 1
