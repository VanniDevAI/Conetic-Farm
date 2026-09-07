#!/usr/bin/env bash
# Build the sandbox base image WITHOUT contacting any container registry.
#
# Why: CooperBench's per-task Dockerfiles start `FROM node:22-slim`, but this
# environment's egress policy blocks Docker registry blob downloads
# (production.cloudfront.docker.com answers 403), so `docker pull` cannot work.
# The host, however, already carries everything a task image needs
# (Ubuntu 24.04 userland, git, python3, and Node 22 under /opt/node22).
#
# So we snapshot the host root filesystem into an image with `docker import`.
# Containers are still real, kernel-isolated Docker containers with their own
# filesystem, PID, and network namespaces -- only the *provenance* of the base
# layer differs from upstream.  That substitution is recorded in every episode
# manifest (`base.image.substitution`) so a replayer knows exactly what it got.
#
# Usage: scripts/build_base_image.sh [IMAGE_TAG]
set -euo pipefail

IMAGE_TAG="${1:-conetic-farm/node22-base:local}"

command -v docker >/dev/null || { echo "FATAL: docker not on PATH" >&2; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "FATAL: docker daemon unreachable. Start it with: dockerd &" >&2; exit 1; }

NODE_BIN="$(command -v node || true)"
[[ -n "$NODE_BIN" ]] || { echo "FATAL: node not found on host" >&2; exit 1; }
NODE_PREFIX="$(dirname "$(dirname "$(readlink -f "$NODE_BIN")")")"
echo "==> host node prefix: $NODE_PREFIX"

# Directories that make up a working userland.  /var, /home, /root, /mnt and the
# pseudo-filesystems are excluded: they hold host state, not runtime, and /var
# in particular contains the Docker data root (recursive, enormous).
INCLUDE=(./bin ./sbin ./lib ./lib64 ./usr ./etc)
[[ "$NODE_PREFIX" == /opt/* ]] && INCLUDE+=(./opt)

echo "==> importing rootfs as $IMAGE_TAG (this takes a few minutes)"
cd /
tar \
  --exclude=./proc --exclude=./sys --exclude=./dev --exclude=./tmp \
  --exclude=./run  --exclude=./var  --exclude=./home --exclude=./root \
  --exclude=./mnt  --exclude=./media --exclude=./srv \
  --exclude='./etc/ssh/ssh_host_*' \
  --exclude='./etc/shadow*' \
  -cf - "${INCLUDE[@]}" 2>/dev/null \
| docker import \
    -c "ENV PATH=${NODE_PREFIX}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    -c 'ENV LANG=C.UTF-8' \
    -c 'ENV DEBIAN_FRONTEND=noninteractive' \
    -c 'ENV NODE_OPTIONS=--max-old-space-size=3072' \
    -c 'ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt' \
    - "$IMAGE_TAG"

echo "==> verifying"
docker run --rm "$IMAGE_TAG" /bin/sh -lc '
  set -e
  for t in node npm npx git python3 tar bash; do
    printf "  %-8s " "$t"
    command -v "$t" >/dev/null && "$t" --version 2>&1 | head -1 || { echo MISSING; exit 1; }
  done
'
echo "==> OK: $IMAGE_TAG"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -F "${IMAGE_TAG%%:*}" || true
