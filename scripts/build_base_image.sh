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

# Staged into the build context: verifies that a package we just made
# pip-owned still imports.  --no-deps installs a PyPI wheel over the apt copy
# WITHOUT its dependencies, so a package with a compiled extension can end up
# shadowing a working install with one whose ABI dependency is absent.  That is
# not hypothetical: it left `import jwt` raising ModuleNotFoundError for
# _cffi_backend and then a pyo3 PanicException, while the RECORD check, the
# version-drift check and the build assertion all passed -- none of them ever
# imported anything.
cat > "$BUILD_DIR/farm-verify-import.py" <<'VERIFY'
"""Import-check a distribution's top-level modules (or every substituted one)."""
import importlib, importlib.metadata as m, subprocess, sys


def tops(dist):
    out = set()
    tl = dist.read_text("top_level.txt")
    if tl:
        out |= {l.strip() for l in tl.splitlines() if l.strip()}
    for f in (dist.files or []):
        p = str(f)
        if p.endswith("/__init__.py"):
            out.add(p.split("/")[0])
    return {t for t in out if t and not t.startswith("_") and "-" not in t}


def check(dist) -> list:
    bad = []
    for mod in sorted(tops(dist)):
        try:
            importlib.import_module(mod)
        except BaseException as exc:        # PanicException is not an Exception
            bad.append((dist.metadata["Name"], mod, type(exc).__name__))
            break
    return bad


BASELINE = "/etc/conetic-farm/import-baseline.txt"
PREEXISTING = "/etc/conetic-farm/import-broken.txt"


def failing_now() -> set:
    """Names of distributions whose top-level import fails right now."""
    return {b[0] for d in m.distributions() for b in check(d)}


if __name__ == "__main__":
    if "--baseline" in sys.argv:
        # Some packages never imported in this image at all: python-apt and
        # dbus-python are apt-only wrappers whose C extensions are not in the
        # rootfs slice we import.  They are not ours to fix and must not fail
        # the build -- but a package that imported BEFORE the substitution and
        # not after is a regression we caused, and must.
        bad = sorted(failing_now())
        open(PREEXISTING, "w").write("\n".join(bad) + ("\n" if bad else ""))
        print("  already unimportable before substitution: %s" % (bad or "none"))
        raise SystemExit(0)
    if "--rollback-regressions" in sys.argv:
        # Verify only AFTER every install.  Verifying inside the loop judged a
        # package against a half-substituted image: `sorted()` puts PyJWT before
        # cryptography, so `import jwt` was checked while cryptography was still
        # the unusable apt copy, PyJWT was demoted for someone else's breakage,
        # and it stayed demoted after cryptography was fixed -- leaving pip
        # unable to upgrade it, which is the whole defect this layer exists for.
        try:
            pre = set(open(PREEXISTING).read().split())
        except OSError:
            pre = set()
        regressed = sorted(failing_now() - pre)
        for name in regressed:
            subprocess.run(["pip3", "uninstall", "-y", "-q",
                            "--break-system-packages", name],
                           capture_output=True)
            with open("/etc/conetic-farm/pip-unmanaged.txt", "a") as fh:
                fh.write(name + "\n")
            print("  rolled back:       %s  (pip copy did not import; apt copy restored)" % name)
        if not regressed:
            print("  no rollbacks needed: every substitution imports")
        raise SystemExit(0)
    if "--sweep" in sys.argv:
        try:
            pre = set(open(PREEXISTING).read().split())
        except OSError:
            pre = set()
        regressed = sorted(failing_now() - pre)
        if regressed:
            print("FATAL: these imported before the substitution and do not now: %s"
                  % regressed, file=sys.stderr)
            raise SystemExit(1)
        print("  import sweep: no package regressed (pre-existing: %s)"
              % (sorted(pre) or "none"))
        raise SystemExit(0)
    try:
        d = m.distribution(sys.argv[1])
    except Exception:
        raise SystemExit(1)
    raise SystemExit(1 if check(d) else 0)
VERIFY

cat > "$BUILD_DIR/Dockerfile" <<DOCKERFILE
FROM ${IMAGE_TAG}-raw
RUN mkdir -p /tmp /var/tmp /var/log /var/cache /var/lib /run /home /root /mnt /srv \
 && chmod 1777 /tmp /var/tmp \
 && mkdir -p /root/.cache
${RUST_COPY}
${RUST_ENV}
# pip cannot replace an apt-managed package: apt writes no RECORD file, so the
# uninstall step dies with "Cannot uninstall <pkg>, RECORD file not found".
# It killed both dspy episodes in c02 -- first on PyYAML, then, once PyYAML
# alone was fixed, on PyJWT.  The base carries 24 such distributions, several
# of which tasks routinely upgrade (cryptography, packaging, setuptools, six,
# PyJWT, pip), so this is a property of the image, not of one package.
#
# For every distribution pip would resolve FIRST that lacks a RECORD, install
# a pip-owned copy of the SAME version into /usr/local, which precedes
# dist-packages on sys.path.  The version is pinned to what apt shipped, so
# the image's behaviour is unchanged; only pip's ability to manage it is.
# Dependencies are resolved, but CONSTRAINED.  Two wrong versions preceded this.
# Without --no-deps pip re-resolved each closure at the newest versions and six
# packages drifted off apt's pins.  With --no-deps nothing drifted, but the
# PyPI wheel for `cryptography` landed without its `cffi` ABI dependency, so
# `import jwt` died with a pyo3 PanicException -- and the build "passed" by
# quietly demoting PyJWT, which hid the real breakage.  Neither is acceptable:
# one silently changes what the tasks run against, the other silently breaks it.
#
# So pip may install what a package needs, against a constraints file pinning
# every apt-installed distribution to the version apt shipped.  Missing
# dependencies (cffi) get installed; nothing already present can move.  If a
# package genuinely cannot be satisfied under those pins, the install fails and
# it is declared apt-managed -- which is then a true statement, not a guess.
#
# Ubuntu-only packages with no PyPI release at that version (python-apt,
# PyGObject, dbus-python ...) cannot be reinstalled and are DECLARED in
# /etc/conetic-farm/pip-unmanaged.txt, which the test suite reads: anything
# RECORD-less and undeclared fails the build here, not an episode later.
# The build also asserts no version drifted, so the substitution stays
# invisible to the tasks under test.
COPY farm-verify-import.py /opt/farm-verify-import.py
RUN set -e; mkdir -p /etc/conetic-farm; : > /etc/conetic-farm/pip-unmanaged.txt; \
 python3 -c "import importlib.metadata as m; print('\\n'.join(sorted(f'{d.metadata[\"Name\"]}=={d.version}' for d in m.distributions())))" > /etc/conetic-farm/apt-constraints.txt; \
 python3 /opt/farm-verify-import.py --baseline; \
 for spec in \$(python3 -c "import importlib.metadata as m; print(' '.join(f'{n}=={m.distribution(n).version}' for n in sorted({d.metadata['Name'] for d in m.distributions()}) if m.distribution(n).read_text('RECORD') is None))"); do \
   if PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip3 install -q --ignore-installed -c /etc/conetic-farm/apt-constraints.txt --break-system-packages --no-cache-dir "\$spec" >/dev/null 2>&1; then \
     echo "  pip-owned:         \$spec"; \
   else \
     echo "\${spec%%==*}" >> /etc/conetic-farm/pip-unmanaged.txt; \
     echo "  left apt-managed:  \$spec  (pip install failed)"; \
   fi; \
 done; \
 python3 /opt/farm-verify-import.py --rollback-regressions; \
 python3 /opt/farm-verify-import.py --sweep; \
 python3 -c "import importlib.metadata as m, pathlib; un=set(pathlib.Path('/etc/conetic-farm/pip-unmanaged.txt').read_text().split()); bad=[n for n in sorted({d.metadata['Name'] for d in m.distributions()}) if m.distribution(n).read_text('RECORD') is None and n not in un]; assert not bad, f'RECORD-less and undeclared: {bad}'; apt={d.metadata['Name'].lower(): d.version for d in m.distributions() if '/usr/lib/python3/dist-packages' in str(d.locate_file(''))}; drift=[(n,v,m.distribution(n).version) for n,v in sorted(apt.items()) if m.distribution(n).version != v and '/usr/local/' in str(m.distribution(n).locate_file(''))]; assert not drift, f'version drift: {drift}'; print('declared apt-only:', sorted(un))"
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
