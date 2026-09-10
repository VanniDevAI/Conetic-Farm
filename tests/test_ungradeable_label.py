"""An ungradeable side gets its own label; it is never called broken.

Measured in the s02 positive control: both episodes were labelled `a_broken` /
`b_broken` with the rationale *"agent A's patch fails its own tests in
isolation"* — and that statement was false. The patch was never graded, because
the dataset's test patch could not be applied over the agent's edit.

`ungradeable` already reached the classification *evidence* and the report's
`p`, but not the label, so the corpus asserted a broken patch where none had
been demonstrated. Every episode of this kind is affected, including in
`c01`-`c03`.

The distinction is not cosmetic. "Fails its own tests" is a measurement;
"could not be graded" is the absence of one. A corpus that records the second
as the first cannot be audited afterwards, because the evidence that would
correct it has already been overwritten by the label.
"""

from __future__ import annotations

from farm.classify import (
    AgentResult, Label, MergeOutcome, MergeResult, TestOutcome, classify,
)

APPLY_FAILED = {"patch_apply_failed": True, "reason": "patch did not apply"}
COLLECTION_FAILED = {"patch_apply_failed": False, "saw_test_summary": False}


def _r(own, *, detail=None, patch=True):
    return AgentResult(has_patch=patch, own_tests=own,
                       partner_tests=TestOutcome.FAIL, patch_bytes=100,
                       own_detail=detail)


CLEAN = MergeResult(MergeOutcome.CLEAN, TestOutcome.PASS, TestOutcome.PASS)


def test_an_ungradeable_a_is_labelled_ungradeable_not_broken() -> None:
    c = classify(_r(TestOutcome.ERROR, detail=APPLY_FAILED), _r(TestOutcome.PASS), CLEAN)
    assert c.label is Label.UNGRADEABLE_A
    assert "fails its own tests" not in c.rationale.lower()
    assert not c.individually_broken, (
        "an ungradeable patch was never shown to be broken")


def test_an_ungradeable_b_is_labelled_ungradeable_not_broken() -> None:
    c = classify(_r(TestOutcome.PASS), _r(TestOutcome.ERROR, detail=APPLY_FAILED), CLEAN)
    assert c.label is Label.UNGRADEABLE_B
    assert not c.individually_broken


def test_both_ungradeable_has_its_own_label() -> None:
    c = classify(_r(TestOutcome.ERROR, detail=APPLY_FAILED),
                 _r(TestOutcome.ERROR, detail=APPLY_FAILED), CLEAN)
    assert c.label is Label.UNGRADEABLE_BOTH


def test_a_real_collection_failure_is_still_broken() -> None:
    """The narrowness is the point: a suite that RAN and rejected the patch is a
    measurement, and must keep saying so."""
    c = classify(_r(TestOutcome.ERROR, detail=COLLECTION_FAILED), _r(TestOutcome.PASS), CLEAN)
    assert c.label is Label.A_BROKEN
    assert c.individually_broken


def test_ungradeable_is_never_a_genuine_integration_failure() -> None:
    for lab in (Label.UNGRADEABLE_A, Label.UNGRADEABLE_B, Label.UNGRADEABLE_BOTH):
        assert not lab.is_genuine_integration_failure
        assert lab.failure_class is None
        assert not lab.is_individually_broken


def test_a_missing_patch_still_outranks_ungradeable() -> None:
    """No patch at all is a stronger statement than an ungraded one."""
    c = classify(_r(TestOutcome.ERROR, detail=APPLY_FAILED, patch=False),
                 _r(TestOutcome.PASS), CLEAN)
    assert c.label is Label.NO_PATCH_A


def test_the_rationale_says_what_actually_happened() -> None:
    c = classify(_r(TestOutcome.ERROR, detail=APPLY_FAILED), _r(TestOutcome.PASS), CLEAN)
    assert "could not be graded" in c.rationale or "not graded" in c.rationale
