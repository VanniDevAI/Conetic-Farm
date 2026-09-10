"""Integration failures split into two classes, and the split is load-bearing.

Both labels already existed; what did not exist was the distinction being
*named* and carried into every report. It matters because the two are different
phenomena and only one of them is what a claim-map engine is for:

* **textual** — the three-way merge refuses. Two patches touched overlapping
  lines. Git can see this; so can any merge tool. The combined tests never run.
* **semantic** — the merge succeeds cleanly and the *combined* tests fail. The
  patches are textually compatible and behaviourally incompatible. Nothing in
  the merge machinery can see it, which is exactly the gap a claim map is meant
  to close before the merge happens.

Reporting one number over both hides the distinction that decides whether a
result is evidence for the thing being built. So `failure_class` is a property
of the label, not a string assembled at the point of printing.
"""

from __future__ import annotations

from farm.classify import Label


def test_a_refused_merge_is_textual() -> None:
    assert Label.INTEGRATION_FAILURE_MERGE.failure_class == "textual"


def test_a_clean_merge_whose_tests_fail_is_semantic() -> None:
    assert Label.INTEGRATION_FAILURE_TESTS.failure_class == "semantic"


def test_every_other_label_has_no_failure_class() -> None:
    """Only a genuine integration failure has a class; nothing else may claim
    one, or the counts stop meaning what they say."""
    for label in Label:
        if label.is_genuine_integration_failure:
            assert label.failure_class in ("textual", "semantic"), label
        else:
            assert label.failure_class is None, label


def test_the_two_classes_partition_the_genuine_failures() -> None:
    classes = {l.failure_class for l in Label if l.is_genuine_integration_failure}
    assert classes == {"textual", "semantic"}, (
        "a new integration-failure label was added without giving it a class; "
        "it would be counted in the total and in neither class")


# --- and it has to reach the report, in every campaign ----------------------

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("report", REPO / "scripts" / "report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def _labels(*names):
    """Campaign-index episodes, the shape `report.load` returns: the attempt
    carries `label` and `disposition` at the top level."""
    return [{"attempts": [{"attempt_id": "attempt-001", "status": "completed",
                           "disposition": "counted", "label": n}]}
            for n in names]


def test_the_report_splits_the_two_classes() -> None:
    got = report.failure_classes(_labels(
        "integration_failure_merge", "integration_failure_merge",
        "integration_failure_tests", "both_broken", "a_broken"))
    assert got == {"textual": 2, "semantic": 1, "total": 3}


def test_zero_of_a_class_is_still_reported() -> None:
    """A campaign with only textual failures must say `semantic: 0`, not omit
    it. An absent row reads as 'not measured'; a zero reads as 'looked for and
    not found', and only the second is true."""
    got = report.failure_classes(_labels("integration_failure_merge"))
    assert got == {"textual": 1, "semantic": 0, "total": 1}


def test_no_failures_at_all_still_reports_both_classes() -> None:
    assert report.failure_classes(_labels("both_broken")) == {
        "textual": 0, "semantic": 0, "total": 0}
