"""The report must count ungradeable patches as their own category.

`p` is the number the experiment turns on (Appendix E.2), and it is a ratio of
*graded* patches.  A patch whose grader never ran belongs in neither numerator
nor an undifferentiated "broken" pile: it carries no evidence.

Two sources, because the corpus spans campaigns.  `c03` and earlier were graded
before `ungradeable` existed as a field, so the reason has to come from the
grader's own detail file; from `c04` on it is in the classification evidence.
The report must read either and report the same number, or the correction
stops applying the moment the field lands.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("report", REPO / "scripts" / "report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def _ep(a_ungradeable=None, b_ungradeable=None, a_own="fail", b_own="fail"):
    """One attempt record, the shape `_last_counted_detail` returns."""
    return {
        "status": "completed", "attempt_id": "attempt-001",
        "classification": {"label": "both_broken", "evidence": {
            "a": {"own_tests": a_own, "has_patch": True, "ungradeable": a_ungradeable},
            "b": {"own_tests": b_own, "has_patch": True, "ungradeable": b_ungradeable},
            "merge": {"outcome": "clean", "conflicted_paths": []}}}}


def test_an_ungradeable_side_is_counted() -> None:
    got = report.gradeability([_ep(a_ungradeable="ungradeable: the test patch ...", a_own="error")])
    assert got["ungradeable"] == 1
    assert got["graded"] == 1, "the other side was graded and still counts"


def test_a_plain_error_is_graded_not_ungradeable() -> None:
    """A collection failure means the grader ran and rejected the patch."""
    got = report.gradeability([_ep(a_own="error")])
    assert got["ungradeable"] == 0
    assert got["graded"] == 2


def test_p_is_computed_over_graded_patches_only() -> None:
    eps = [_ep(a_own="pass", b_own="fail"),
           _ep(a_own="error", a_ungradeable="ungradeable: ...", b_own="fail")]
    got = report.gradeability(eps)
    assert got["graded"] == 3 and got["passed"] == 1
    assert abs(got["p_graded"] - 1 / 3) < 1e-9
    assert abs(got["p_all"] - 1 / 4) < 1e-9, (
        "both figures are reported; neither is chosen silently")


def test_a_side_with_no_patch_is_not_a_graded_patch() -> None:
    ep = _ep()
    ep["classification"]["evidence"]["b"]["has_patch"] = False
    got = report.gradeability([ep])
    assert got["graded"] == 1
