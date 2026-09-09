#!/bin/bash
# Grade the consumer package: <test_patch> [feature_patch] [provider_tarball]
#
# With no tarball the provider stays at the registry version the package was
# built against. With one, the provider is replaced by a build of the other
# agent's patched source -- which is the whole integration question, and the
# only thing that differs between the two runs.
set -e
cleanup() {
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git reset --hard HEAD 2>/dev/null || true
        git clean -fdq -e node_modules 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

TEST_PATCH="$1"; FEATURE_PATCH="$2"; PROVIDER_TGZ="$3"
[[ -z "$TEST_PATCH" ]] && { echo "usage: <test_patch> [feature_patch] [provider_tgz]"; exit 1; }
cd /workspace/repo
[ -d node_modules ] || cp -r /workspace/node_modules_cache node_modules

if [[ -n "$PROVIDER_TGZ" ]]; then
    echo "PROVIDER: installing /provider/$PROVIDER_TGZ over the registry copy"
    npm install --no-save --no-audit --no-fund --loglevel=error "/provider/$PROVIDER_TGZ"
else
    echo "PROVIDER: registry version, as declared in package.json"
fi

if [[ -n "$FEATURE_PATCH" ]]; then
    git apply --ignore-whitespace --ignore-space-change "/patches/$FEATURE_PATCH" \
      || git apply --3way "/patches/$FEATURE_PATCH"
fi
git apply --ignore-whitespace --ignore-space-change "/patches/$TEST_PATCH" \
  || git apply --3way "/patches/$TEST_PATCH"

# Grade only what the applied test patch touches.
TARGETS=$(grep -E '^\+\+\+ b/' "/patches/$TEST_PATCH" | sed 's|^+++ b/||' | grep -E '\.test\.ts$' | sort -u | tr '\n' ' ')
[[ -z "$TARGETS" ]] && { echo "ERROR: test patch touches no test file"; exit 1; }
echo "GRADING_FILES: $TARGETS"
npx --yes vitest run $TARGETS 2>&1
