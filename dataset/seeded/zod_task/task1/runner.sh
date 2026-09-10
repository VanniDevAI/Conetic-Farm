#!/bin/bash
set -e
cleanup() {
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git reset --hard HEAD 2>/dev/null || true
        git clean -fdx -e node_modules -e packages/zod/node_modules 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

TEST_PATCH="$1"; FEATURE_PATCH="$2"
[[ -z "$TEST_PATCH" ]] && { echo "Usage: <test_patch> [feature_patch]"; exit 1; }
cd /workspace/repo
[ -d /workspace/node_modules_cache ] && [ ! -d node_modules ] && cp -r /workspace/node_modules_cache node_modules

if [[ -n "$FEATURE_PATCH" ]]; then
    git apply --ignore-whitespace --ignore-space-change "/patches/$FEATURE_PATCH" || git apply --3way "/patches/$FEATURE_PATCH"
fi
git apply --ignore-whitespace --ignore-space-change "/patches/$TEST_PATCH" || git apply --3way "/patches/$TEST_PATCH"

# Grade only the test files the applied test patch touches, so neither agent's
# grade depends on the other's file.
TARGETS=$(grep -E '^\+\+\+ b/' "/patches/$TEST_PATCH" | sed 's|^+++ b/||' | grep -E '\.test\.ts$' | sort -u | tr '\n' ' ')
[[ -z "$TARGETS" ]] && { echo "ERROR: test patch touches no test file"; exit 1; }
# zod's per-package vitest config merges the root config, whose `projects` list
# is resolved relative to the cwd -- so vitest only starts from the repo root.
# `--project zod` then narrows it to the one package these tests live in.
echo "GRADING_FILES: $TARGETS"
npx --yes vitest run --project zod $TARGETS 2>&1
