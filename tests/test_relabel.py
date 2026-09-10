"""Relabelling an archive must correct the claim without erasing the record.

The s02 control showed the corpus asserting `a_broken` -- "fails its own tests
in isolation" -- for a patch that was never graded. That claim is in `c01`-`c03`
and the sweeps too, so it has to be corrected where it was written.

Two things a migration over finished experiments must not do:

* **lose the original.** A corrected label that overwrites its predecessor makes
  the correction itself unauditable. The prior value is kept beside the new one.
* **relabel anything it was not asked to.** Only a side whose grading could not
  run changes; a genuine collection failure is a measurement and keeps saying so.

Idempotence matters for the same reason: running the migration twice must not
rewrite `label_original` with the already-corrected label.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("relabel", REPO / "scripts" / "relabel_ungradeable.py")
relabel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relabel)

APPLY_FAILED = {"patch_apply_failed": True, "reason": "patch did not apply"}


def _attempt(label, a_err=False, b_err=False):
    return {
        "attempt_id": "attempt-001", "status": "completed", "disposition": "counted",
        "label": label,
        "classification": {"label": label, "rationale": "agent A's patch fails its own tests",
                           "genuine_integration_failure": False, "individually_broken": True,
                           "evidence": {
                               "a": {"has_patch": True, "own_tests": "error" if a_err else "pass"},
                               "b": {"has_patch": True, "own_tests": "error" if b_err else "pass"},
                               "merge": {"outcome": "clean", "conflicted_paths": []}}}}


def test_an_ungradeable_side_is_relabelled() -> None:
    att = _attempt("a_broken", a_err=True)
    ch = relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None})
    assert ch is not None
    assert att["label"] == "ungradeable_a"
    assert att["classification"]["label"] == "ungradeable_a"
    assert "could not be graded" in att["classification"]["rationale"]


def test_the_original_label_is_preserved() -> None:
    att = _attempt("a_broken", a_err=True)
    relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None})
    assert att["label_original"] == "a_broken"
    assert att["classification"]["label_original"] == "a_broken"


def test_running_twice_does_not_overwrite_the_original() -> None:
    att = _attempt("a_broken", a_err=True)
    relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None})
    second = relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None})
    assert second is None, "the second pass reported a change it did not make"
    assert att["label_original"] == "a_broken"


def test_a_collection_failure_is_left_alone() -> None:
    att = _attempt("a_broken", a_err=True)
    ch = relabel.correct_attempt(att, {"a": {"patch_apply_failed": False}, "b": None})
    assert ch is None
    assert att["label"] == "a_broken"
    assert "label_original" not in att


def test_a_healthy_episode_is_left_alone() -> None:
    att = _attempt("both_pass_merge_passes")
    assert relabel.correct_attempt(att, {"a": None, "b": None}) is None
    assert att["label"] == "both_pass_merge_passes"


def test_both_sides_ungradeable() -> None:
    att = _attempt("both_broken", a_err=True, b_err=True)
    relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": APPLY_FAILED})
    assert att["label"] == "ungradeable_both"


def test_individually_broken_is_cleared() -> None:
    """The flag drives 'these are not integration failures' counts; an
    ungradeable patch was never shown broken, so it must not be counted."""
    att = _attempt("a_broken", a_err=True)
    relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None})
    assert att["classification"]["individually_broken"] is False


def test_a_missing_patch_outranks_ungradeable_in_the_migration_too() -> None:
    """Caught by the dry run over `c02`: three episodes would have gone
    `no_patch_a` -> `ungradeable_b`.

    The classifier ranks a missing patch above an ungraded one -- "produced
    nothing" is a stronger statement than "was not measured" -- and the
    migration has to obey the same order, or it invents a correction the live
    classifier would never make and the archive stops matching the code.
    """
    att = _attempt("no_patch_a", b_err=True)
    att["classification"]["evidence"]["a"]["has_patch"] = False
    ch = relabel.correct_attempt(att, {"a": None, "b": APPLY_FAILED})
    assert ch is None, "relabelled an episode whose patch was missing entirely"
    assert att["label"] == "no_patch_a"


def test_a_missing_patch_on_the_other_side_is_also_respected() -> None:
    att = _attempt("no_patch_b", a_err=True)
    att["classification"]["evidence"]["b"]["has_patch"] = False
    assert relabel.correct_attempt(att, {"a": APPLY_FAILED, "b": None}) is None
