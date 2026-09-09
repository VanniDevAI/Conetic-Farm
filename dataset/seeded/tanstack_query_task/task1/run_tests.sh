#!/bin/bash
# Host-side equivalent of runner.sh, for verifying the seed without the image.
# Grades only the test files the applied test patch touches, exactly as the
# runner does.
set -e
REPO_PATH="$1"; TEST_PATCH="$(realpath "$2")"; shift 2
cd "$REPO_PATH"
for fp in "$@"; do
  FP="$(realpath "$fp")"
  git apply --ignore-whitespace "$FP" || git apply --3way "$FP"
done
git apply --ignore-whitespace "$TEST_PATCH" || git apply --3way "$TEST_PATCH"
TARGETS=$(grep -E '^\+\+\+ b/' "$TEST_PATCH" | sed 's|^+++ b/||' | grep -E '__tests__' | sort -u)
REL=$(echo "$TARGETS" | sed 's|^packages/query-core/||' | tr '\n' ' ')
cd packages/query-core
echo "GRADING_FILES: $REL"
npx --yes vitest run $REL 2>&1
