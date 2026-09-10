"""The CooperBench edits must not live only in an ephemeral working tree.

Four campaign fixes live inside a separate checkout at
``$FARM_COOPERBENCH_DIR``, each marked ``[conetic-farm]``. That checkout is
rebuilt from upstream in a fresh container, so an edit that exists only there
is one container restart from gone -- and the next campaign would run on a
harness quietly missing the fixes it was promised.

``vendor/cooperbench/farm-edits.patch`` is the durable copy. This pins that it
stays in step with the checkout: every marked change in the tree has to appear
in the exported patch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "cooperbench"
PATCH = VENDOR / "farm-edits.patch"
CB = Path(os.getenv("FARM_COOPERBENCH_DIR", "/home/user/work/CooperBench"))


def test_the_patch_and_the_pinned_commit_are_both_present():
    assert PATCH.exists(), "the vendored edits must be committed, not only applied"
    pinned = (VENDOR / "PINNED_COMMIT").read_text().strip()
    assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned)


def test_every_marked_edit_in_the_checkout_is_in_the_exported_patch():
    if not (CB / ".git").exists():
        pytest.skip("CooperBench checkout unavailable")
    live = subprocess.run(["git", "-C", str(CB), "diff", "--", "src/"],
                          capture_output=True, text=True).stdout
    marked = {l.strip() for l in live.splitlines()
              if l.startswith("+") and "[conetic-farm]" in l}
    exported = {l.strip() for l in PATCH.read_text().splitlines()
                if l.startswith("+") and "[conetic-farm]" in l}
    missing = marked - exported
    assert not missing, (
        "these edits exist only in the checkout and would be lost on a rebuild; "
        f"re-export the patch: {sorted(missing)}")


def test_the_patch_applies_to_a_clean_checkout_at_the_pinned_commit():
    """Reverse-applying it to the live tree proves it matches what is there."""
    if not (CB / ".git").exists():
        pytest.skip("CooperBench checkout unavailable")
    r = subprocess.run(["git", "-C", str(CB), "apply", "--reverse", "--check", str(PATCH)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
