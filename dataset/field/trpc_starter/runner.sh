#!/bin/bash
# Run the repository's own checks against a tree built from zero or more
# branch patches. There are no per-task graded tests in step B: the work is
# unseeded, so the product outcome is what the repository's own suite says
# about the combination.
#
#   runner.sh [patch ...]
#
# Applies each patch in order, then typechecks and runs the unit suite. A patch
# that will not apply is reported and stops the run, because a tree that never
# assembled has no product outcome to report.
set -o pipefail
cleanup() {
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        git reset --hard HEAD 2>/dev/null || true
        git clean -fdq -e node_modules -e .env -e prisma/dev.db 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd /workspace/repo
[ -d node_modules ] || cp -r /workspace/node_modules_cache node_modules
[ -f .env ] || cp /workspace/env.cache .env
[ -f prisma/dev.db ] || cp /workspace/dev.db.cache prisma/dev.db

for p in "$@"; do
    if ! git apply --ignore-whitespace --ignore-space-change "/patches/$p" 2>/dev/null; then
        if ! git apply --3way "/patches/$p"; then
            echo "PATCH_FAILED: $p"
            exit 97
        fi
    fi
    echo "APPLIED: $p"
done

echo "=== typecheck ==="
npx --yes tsc --noEmit 2>&1 | tail -40
tc=${PIPESTATUS[0]}
echo "TYPECHECK_EXIT: $tc"

echo "=== unit suite ==="
npx --yes vitest run 2>&1 | tail -40
vt=${PIPESTATUS[0]}
echo "VITEST_EXIT: $vt"

[ "$tc" -eq 0 ] && [ "$vt" -eq 0 ] && echo "SUITE: pass" || echo "SUITE: fail"
[ "$tc" -eq 0 ] && [ "$vt" -eq 0 ]
