#!/bin/bash
set -e

cleanup() {
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git reset --hard HEAD 2>/dev/null || true
        git clean -fdx 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

TEST_PATCH="$1"
FEATURE_PATCH="$2"
[[ -z "$TEST_PATCH" ]] && { echo "Usage: <test_patch> [feature_patch]"; exit 1; }

cd /workspace/repo

# git clean removes node_modules; restore both the workspace root store and the
# package's own links, or vitest cannot resolve @tanstack/query-test-utils.
[ -d /workspace/node_modules_cache ] && cp -r /workspace/node_modules_cache node_modules
[ -d /workspace/qc_node_modules_cache ] && cp -r /workspace/qc_node_modules_cache packages/query-core/node_modules

if [[ -n "$FEATURE_PATCH" ]]; then
    if [[ -f "/patches/$FEATURE_PATCH" ]]; then
        git apply --ignore-whitespace --ignore-space-change "/patches/$FEATURE_PATCH" || git apply --3way "/patches/$FEATURE_PATCH"
    else
        echo "Error: Feature patch not found at /patches/$FEATURE_PATCH"; exit 1
    fi
fi

if [[ -f "/patches/$TEST_PATCH" ]]; then
    git apply --ignore-whitespace --ignore-space-change "/patches/$TEST_PATCH" || git apply --3way "/patches/$TEST_PATCH"
else
    echo "Error: Test patch not found at /patches/$TEST_PATCH"; exit 1
fi

# Run ONLY the test files the applied test patch touches.
#
# Learned from the pair-1 gold validation: running both agents' suites meant
# that grading B also ran A's test file at BASE, which fails the moment A's
# source change lands -- so a merged run "failed" for a reason that had nothing
# to do with B consuming A. Each agent's grade must depend on its own tests
# alone, or attribution is impossible.
TARGETS=$(grep -E '^\+\+\+ b/' "/patches/$TEST_PATCH" | sed 's|^+++ b/||' | grep -E '__tests__' | sort -u)
[[ -z "$TARGETS" ]] && { echo "ERROR: test patch touches no test file"; exit 1; }
REL=$(echo "$TARGETS" | sed 's|^packages/query-core/||' | tr '\n' ' ')
cd packages/query-core
echo "GRADING_FILES: $REL"
npx --yes vitest run $REL 2>&1
