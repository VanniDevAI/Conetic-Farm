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

# Rust, for the Rust tasks in the plan (typst).  The toolchain lives under /root,
# which the rootfs tar deliberately excludes as host state -- and an explicit
# include does NOT survive that exclude, so it is COPYed in by the Dockerfile
# stage below instead.  c01 episode 1 died as `cargo: not found`.
CARGO_SRC="${CARGO_HOME:-/root/.cargo}"
RUSTUP_SRC="${RUSTUP_HOME:-/root/.rustup}"
HAVE_RUST=0
if [[ -x "$CARGO_SRC/bin/cargo" && -d "$RUSTUP_SRC" ]]; then
  HAVE_RUST=1
  echo "==> host rust: $("$CARGO_SRC/bin/cargo" --version 2>/dev/null || echo unknown)"
else
  echo "==> WARNING: no host Rust toolchain; Rust tasks will fail to build" >&2
fi

# Directories that make up a working userland.  /var, /home, /root, /mnt and the
# pseudo-filesystems are excluded: they hold host state, not runtime, and /var
# in particular contains the Docker data root (recursive, enormous).
INCLUDE=(./bin ./sbin ./lib ./lib64 ./usr ./etc)
# Only the Node prefix from /opt, never all of it.  A host /opt can hold browser
# bundles, extra language runtimes and editor tooling worth gigabytes that no
# task image needs; carrying them makes every build slower and eats the disk
# allowance for nothing.
[[ "$NODE_PREFIX" == /opt/* ]] && INCLUDE+=(".${NODE_PREFIX}")

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
    - "${IMAGE_TAG}-raw"

# `docker import` cannot run commands, and the tar above deliberately omits the
# host's /tmp, /var, /run and /home (host state, and /var contains the Docker
# data root).  Those directories still have to EXIST in the image: pip, apt,
# build backends and most test runners write to /tmp, and a missing /tmp fails
# with a bare "can't cd to /tmp" that looks nothing like its cause.
echo "==> adding the runtime directories the import could not carry"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
RUST_COPY=""
RUST_ENV=""
if [[ "$HAVE_RUST" == "1" ]]; then
  echo "==> staging the Rust toolchain into the image context"
  cp -a "$CARGO_SRC"  "$BUILD_DIR/cargo"
  cp -a "$RUSTUP_SRC" "$BUILD_DIR/rustup"
  RUST_COPY="COPY cargo /opt/cargo
COPY rustup /opt/rustup"
  # cargo/rustc in .cargo/bin are rustup *proxies*: they resolve a toolchain via
  # RUSTUP_HOME, so both variables must point at the relocated directories or the
  # proxies abort with "no default toolchain".
  RUST_ENV="ENV CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup
ENV PATH=/opt/cargo/bin:${NODE_PREFIX}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

cat > "$BUILD_DIR/Dockerfile" <<DOCKERFILE
FROM ${IMAGE_TAG}-raw
RUN mkdir -p /tmp /var/tmp /var/log /var/cache /var/lib /run /home /root /mnt /srv \
 && chmod 1777 /tmp /var/tmp \
 && mkdir -p /root/.cache
${RUST_COPY}
${RUST_ENV}
WORKDIR /
DOCKERFILE
docker build -q -t "$IMAGE_TAG" "$BUILD_DIR" >/dev/null
docker rmi "${IMAGE_TAG}-raw" >/dev/null 2>&1 || true

echo "==> verifying"
docker run --rm "$IMAGE_TAG" /bin/sh -lc '
  set -e
  for t in node npm npx git python3 pip3 tar bash; do
    printf "  %-8s " "$t"
    command -v "$t" >/dev/null && "$t" --version 2>&1 | head -1 || { echo MISSING; exit 1; }
  done
  for d in /tmp /var/tmp /run /home /root; do
    [ -d "$d" ] || { echo "MISSING DIR $d"; exit 1; }
  done
  printf "  %-8s " "writable /tmp"; touch /tmp/.probe && echo ok || exit 1
  if command -v cargo >/dev/null; then printf "  %-8s " "cargo"; cargo --version; fi
'
echo "==> OK: $IMAGE_TAG"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -F "${IMAGE_TAG%%:*}" || true
