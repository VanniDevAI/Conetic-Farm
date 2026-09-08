#!/usr/bin/env bash
# Build a CooperBench task image against the locally-imported base.
#
# Two edits are made to the dataset's own Dockerfile, both recorded in the
# generated Dockerfile and in the episode manifest so a replayer sees exactly
# what changed:
#
#   1. `FROM node:22-slim`  ->  `FROM $FARM_BASE_IMAGE`
#      Registry blob downloads are blocked here (403 from the egress gateway),
#      so the base layer is imported from the host rootfs instead.  It carries
#      the same Node 22 the upstream image would.
#
#   2. The `apt-get update && apt-get install ...` layer is replaced by an
#      assertion that the tools it would have installed are already present.
#      Debian package mirrors are not on the egress allowlist; the local base
#      already ships git, python3 and pip.  The assertion fails the build loudly
#      rather than letting a missing tool surface as a mysterious test failure.
#
# Everything else -- the upstream clone, the pinned base commit, the dependency
# install, the entrypoint -- runs verbatim.
#
# Usage: scripts/build_task_image.sh <repo_name> <task_id> [image_tag]
set -euo pipefail

REPO_NAME="${1:?usage: build_task_image.sh <repo_name> <task_id> [image_tag]}"
TASK_ID="${2:?usage: build_task_image.sh <repo_name> <task_id> [image_tag]}"

FARM_BASE_IMAGE="${FARM_BASE_IMAGE:-conetic-farm/node22-base:local}"
COOPERBENCH_DIR="${FARM_COOPERBENCH_DIR:-/home/user/work/CooperBench}"
TASK_DIR="$COOPERBENCH_DIR/dataset/$REPO_NAME/task$TASK_ID"
# CooperBench resolves a task's image via `cooperbench.utils.get_image_name`,
# which points at Docker Hub (akhatua/cooperbench-<repo>:task<id>).  That pull
# fails here.  Docker prefers a locally-present image over pulling, so tagging
# the local build with the exact name the harness expects makes the harness work
# unmodified -- no fork, no config override.
HARNESS_TAG="$(
  "${FARM_PYTHON:-$COOPERBENCH_DIR/.venv/bin/python}" -c "
from cooperbench.utils import get_image_name
print(get_image_name('$REPO_NAME', $TASK_ID))" 2>/dev/null || true
)"
IMAGE_TAG="${3:-conetic-farm/task-${REPO_NAME}-${TASK_ID}:local}"

[[ -d "$TASK_DIR" ]] || { echo "FATAL: no task dir at $TASK_DIR" >&2; exit 1; }
[[ -f "$TASK_DIR/Dockerfile" ]] || { echo "FATAL: no Dockerfile in $TASK_DIR" >&2; exit 1; }
docker image inspect "$FARM_BASE_IMAGE" >/dev/null 2>&1 || {
  echo "FATAL: base image $FARM_BASE_IMAGE missing; run scripts/build_base_image.sh" >&2
  exit 1; }

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
cp -r "$TASK_DIR/." "$BUILD_DIR/"

python3 - "$BUILD_DIR/Dockerfile" "$FARM_BASE_IMAGE" <<'PY'
import re, sys, pathlib
path, base = pathlib.Path(sys.argv[1]), sys.argv[2]
src = path.read_text()

# 1. rewrite FROM
src, n_from = re.subn(r'(?m)^FROM\s+\S+', f'FROM {base}', src, count=1)
if not n_from:
    sys.exit("FATAL: no FROM line in task Dockerfile")

# 2. neutralise the apt-get layer, asserting the tools exist instead
apt = re.compile(r'(?ms)^RUN\s+apt-get\s+update.*?(?=^\s*$|^[A-Z]{2,}\s)')
assertion = (
    "# [conetic-farm] apt-get layer replaced: Debian mirrors are not reachable\n"
    "# from this environment, and the local base image already ships these tools.\n"
    "RUN set -e; for t in git python3; do \\\n"
    "      command -v \"$t\" >/dev/null || { echo \"FATAL: $t missing from base image\" >&2; exit 1; }; \\\n"
    "    done; \\\n"
    "    ln -sf \"$(command -v python3)\" /usr/local/bin/python 2>/dev/null || true; \\\n"
    "    rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED\n\n"
)
src, n_apt = apt.subn(assertion, src, count=1)

# 2b. `pip install --upgrade pip` cannot work on a distro-managed pip.  The
#     upstream images are python:3.x-slim, where pip is pip-installed and
#     carries a RECORD file; our base is Ubuntu, whose pip comes from apt and
#     has none, so the upgrade dies with
#         Cannot uninstall pip 24.0, RECORD file not found.
#     It took out both dspy episodes and both pillow episodes in c02 -- 4 of 20.
#     --ignore-installed sidesteps the uninstall entirely and installs the new
#     pip alongside, which is what the upstream image effectively has.
src, n_pip = re.subn(
    r'pip\s+install\s+--upgrade\s+pip\b',
    'pip install --upgrade --ignore-installed pip',
    src)

# 3. Node ships its own CA bundle and ignores the system trust store, so npm
#    fails with SELF_SIGNED_CERT_IN_CHAIN behind this environment's
#    TLS-intercepting egress gateway.  Point Node at the system store, which
#    already carries the gateway CA.
ca_env = (
    "ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt\n"
    # 4. Several packages fetch a prebuilt binary from their own CDN during
    #    postinstall (cypress -> download.cypress.io, puppeteer, playwright).
    #    Those hosts are not on the egress allowlist, so the postinstall fails
    #    and takes the whole dependency install with it.  None of them are used
    #    by the unit-test suites these tasks grade against -- react_hook_form's
    #    run_tests.sh runs a single jest file -- so their downloads are skipped.
    #    Recorded here so a replayer knows the image lacks those binaries.
    "ENV CYPRESS_INSTALL_BINARY=0 \\\n"
    "    PUPPETEER_SKIP_DOWNLOAD=1 \\\n"
    "    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \\\n"
    "    HUSKY=0 \\\n"
    "    ADBLOCK=1 \\\n"
    "    DISABLE_OPENCOLLECTIVE=1\n"
    # 5. Python tasks expect `python:3.x-slim`, which ships vanilla setuptools.
    #    Our base is Ubuntu, whose setuptools carries Debian's distutils patch;
    #    an editable install then dies with
    #    `AttributeError: install_layout`, which names nothing useful.
    #    Forcing the stdlib distutils avoids the patched/vanilla mismatch.
    #    PIP_BREAK_SYSTEM_PACKAGES is PEP 668: Ubuntu marks its interpreter
    #    externally-managed, the upstream python images do not.
    "ENV SETUPTOOLS_USE_DISTUTILS=stdlib \\\n"
    "    PIP_BREAK_SYSTEM_PACKAGES=1 \\\n"
    "    PIP_ROOT_USER_ACTION=ignore \\\n"
    "    PIP_DISABLE_PIP_VERSION_CHECK=1 \\\n"
    #    Retries and a real timeout: c03 episode 5 lost its whole image to one
    #    slow `.metadata` fetch from files.pythonhosted.org.  A transient must
    #    not be recorded as a fact about a task.
    "    PIP_RETRIES=5 \\\n"
    "    PIP_TIMEOUT=120\n"
    # 6. `uv` does not use the system trust store: it links its own webpki root
    #    bundle, so behind this environment's TLS-intercepting gateway every
    #    HTTPS fetch fails with `invalid peer certificate: UnknownIssuer` --
    #    which reads like a broken index, not like interception.  It killed the
    #    llama_index image in c01.  Node needed the same treatment above; this is
    #    the uv-shaped version of it.  The gateway CA is already in the image's
    #    system store (verified: all 152 certs), so pointing uv at it is enough.
    "ENV UV_NATIVE_TLS=1 \\\n"
    #    uv's default HTTP timeout is 30s.  Metadata fetches through this
    #    environment's intercepting gateway exceed it often enough to have cost
    #    a whole episode, so give it room rather than treating the index as
    #    broken.
    "    UV_HTTP_TIMEOUT=180 \\\n"
    "    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \\\n"
    "    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt\n"
)
lines = src.splitlines(keepends=True)
for i, line in enumerate(lines):
    if line.startswith("FROM "):
        lines.insert(i + 1, ca_env)
        break
src = "".join(lines)

header = (
    "# GENERATED by scripts/build_task_image.sh -- do not edit.\n"
    f"# base image substituted: node:22-slim -> {base}\n"
    f"# apt-get layer replaced: {'yes' if n_apt else 'no apt-get layer found'}\n"
)
path.write_text(header + src)
print(f"  FROM -> {base}")
print(f"  apt-get layer replaced: {'yes' if n_apt else 'no (none present)'}")
print("  NODE_EXTRA_CA_CERTS + UV_NATIVE_TLS + UV_HTTP_TIMEOUT + pip retries "
      "+ skip-binary-download env injected")
if n_pip:
    print(f"  rewrote {n_pip} `pip install --upgrade pip` to --ignore-installed "
          f"(distro pip has no RECORD file)")
PY

echo "==> building $IMAGE_TAG from $TASK_DIR"
DOCKER_BUILDKIT=1 docker build --network=default -t "$IMAGE_TAG" "$BUILD_DIR"

if [[ -n "$HARNESS_TAG" ]]; then
  echo "==> tagging as $HARNESS_TAG so CooperBench resolves it locally"
  docker tag "$IMAGE_TAG" "$HARNESS_TAG"
fi

echo "==> recording provenance"
docker image inspect "$IMAGE_TAG" --format '{{.Id}}' | sed 's/^/  image id: /'
cp "$BUILD_DIR/Dockerfile" "${FARM_DATA_ROOT:-/tmp}/last_task_dockerfile.txt" 2>/dev/null || true
echo "==> OK: $IMAGE_TAG"
