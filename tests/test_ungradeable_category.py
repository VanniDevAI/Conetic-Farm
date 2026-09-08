"""An agent that edits its own grading test is ungradeable, not broken.

Found in `c03`: 5 of 30 graded patches produced an `error` on their own tests
because the *dataset's* test patch would no longer apply --

    error: patch failed: tests/test_context.py:543
    error: tests/test_context.py: patch does not apply

-- the agent had edited the very file that grades it.  The grader could not run,
so the classifier counted the patch as individually broken.

That default is safe but it is not the same claim.  A patch that fails its tests
has been shown wrong; a patch whose tests could not be applied has been shown
nothing.  Lumping them together depresses the measured pass rate `p` with cases
that carry no evidence either way, and `p` is the quantity the whole experiment
turns on (Appendix E.2).

So `ungradeable` is recorded as its own fact about a side, with the reason,
alongside the outcome -- **not** as a new label.  Labels stay comparable across
c01/c02/c03; the corpus gains a distinction it did not have.

The 9 other `error` cases in `c03` were genuine breakage (a `SyntaxError` in the
agent's own edit stopping `conftest.py` importing), and must NOT be marked
ungradeable -- the distinction is worthless if it swallows real failures.
"""

from __future__ import annotations

from farm.classify import ungradeable_reason


def test_a_test_patch_that_would_not_apply_is_ungradeable() -> None:
    detail = {"patch_apply_failed": True,
              "reason": "patch did not apply (error: patch failed)",
              "saw_test_summary": False}
    got = ungradeable_reason(detail)
    assert got, "the grader never ran; this patch was not shown to be wrong"
    assert "test patch" in got.lower(), got


def test_a_collection_failure_is_real_breakage_not_ungradeable() -> None:
    """`SyntaxError` in the agent's own edit stops conftest importing.  The
    grader ran and rejected the patch; that is a failure, not an absence."""
    detail = {"patch_apply_failed": False, "saw_test_summary": False,
              "reason": "no test summary seen"}
    assert ungradeable_reason(detail) is None


def test_a_clean_pass_or_fail_is_never_ungradeable() -> None:
    assert ungradeable_reason({"saw_test_summary": True}) is None
    assert ungradeable_reason({}) is None


def test_a_timeout_is_not_ungradeable_either() -> None:
    """A suite that ran and never finished is a fact about the patch."""
    assert ungradeable_reason({"timed_out": True, "saw_test_summary": False}) is None


def test_the_reason_is_carried_not_just_a_boolean() -> None:
    """Whoever reads the corpus later needs to know why, without the logs."""
    got = ungradeable_reason({"patch_apply_failed": True,
                              "reason": "patch did not apply (error: patch failed)"})
    assert "did not apply" in got
