#!/usr/bin/env bash
# Reapply the Farm's CooperBench edits to a fresh checkout.
#
# Refuses rather than guesses: a checkout at the wrong commit, or one that
# already carries the edits, is reported and left alone.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CB="${FARM_COOPERBENCH_DIR:-/home/user/work/CooperBench}"
PATCH="$HERE/farm-edits.patch"
PINNED="$(cat "$HERE/PINNED_COMMIT")"

[[ -d "$CB/.git" ]] || { echo "FATAL: no CooperBench checkout at $CB" >&2; exit 1; }

HEAD="$(git -C "$CB" rev-parse HEAD)"
if [[ "$HEAD" != "$PINNED" ]]; then
  echo "FATAL: $CB is at $HEAD, the patch was cut against $PINNED." >&2
  echo "       Check the checkout out at the pinned commit, or re-cut the patch." >&2
  exit 1
fi

if git -C "$CB" apply --reverse --check "$PATCH" 2>/dev/null; then
  echo "[farm] already applied; nothing to do"
  exit 0
fi

git -C "$CB" apply --check "$PATCH"
git -C "$CB" apply "$PATCH"
echo "[farm] applied $(grep -c '^diff --git' "$PATCH") file(s) of Farm edits to $CB"
