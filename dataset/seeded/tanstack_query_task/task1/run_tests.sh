#!/bin/bash
# Host-side equivalent of runner.sh, for verifying the seed without the image.
set -e
REPO_PATH="$1"; TEST_PATCH="$(realpath "$2")"; FEATURE_PATCH="${3:+$(realpath "$3")}"
cd "$REPO_PATH"
[[ -n "$FEATURE_PATCH" ]] && { git apply --ignore-whitespace "$FEATURE_PATCH" || git apply --3way "$FEATURE_PATCH"; }
git apply --ignore-whitespace "$TEST_PATCH" || git apply --3way "$TEST_PATCH"
cd packages/query-core
npx --yes vitest run src/__tests__/utils.test.tsx src/__tests__/queryCache.test.tsx 2>&1
