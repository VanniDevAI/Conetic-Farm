"""The taxonomy's whole job is keeping a broken patch apart from a broken merge."""

from __future__ import annotations

import pytest

from farm.classify import (
    AgentResult, Label, MergeOutcome, MergeResult, TestOutcome, classify,
)

P, F, E, N = (TestOutcome.PASS, TestOutcome.FAIL, TestOutcome.ERROR,
              TestOutcome.NOT_RUN)


def agent(own=P, partner=F, has_patch=True) -> AgentResult:
    return AgentResult(has_patch=has_patch, own_tests=own, partner_tests=partner)


def test_clean_cooperation() -> None:
    c = classify(agent(), agent(), MergeResult(MergeOutcome.CLEAN, P, P))
    assert c.label is Label.BOTH_PASS_MERGE_PASSES
    assert not c.genuine_integration_failure


def test_merge_conflict_with_both_patches_good_is_a_genuine_integration_failure() -> None:
    c = classify(agent(), agent(),
                 MergeResult(MergeOutcome.CONFLICT, conflicted_paths=("src/a.ts",)))
    assert c.label is Label.INTEGRATION_FAILURE_MERGE
    assert c.genuine_integration_failure
    assert not c.individually_broken


def test_merged_tests_failing_with_both_patches_good_is_a_genuine_integration_failure() -> None:
    c = classify(agent(), agent(), MergeResult(MergeOutcome.CLEAN, P, F))
    assert c.label is Label.INTEGRATION_FAILURE_TESTS
    assert c.genuine_integration_failure


@pytest.mark.parametrize(
    "a_own,b_own,expected",
    [(F, P, Label.A_BROKEN), (P, F, Label.B_BROKEN), (F, F, Label.BOTH_BROKEN)],
)
def test_individually_broken_patches_are_never_integration_failures(
    a_own, b_own, expected
) -> None:
    """This is the distinction the whole corpus turns on.

    A conflicting merge on top of a broken patch is still a broken patch.
    """
    c = classify(agent(own=a_own), agent(own=b_own),
                 MergeResult(MergeOutcome.CONFLICT, conflicted_paths=("x",)))
    assert c.label is expected
    assert c.individually_broken
    assert not c.genuine_integration_failure


def test_a_suite_that_errored_does_not_count_as_passing_alone() -> None:
    """A build failure is not evidence the patch works."""
    c = classify(agent(own=E), agent(), MergeResult(MergeOutcome.CLEAN, P, P))
    assert c.label is Label.A_BROKEN
    assert not c.genuine_integration_failure
    assert any("errored" in w for w in c.warnings)


@pytest.mark.parametrize(
    "a_patch,b_patch,expected",
    [(False, True, Label.NO_PATCH_A), (True, False, Label.NO_PATCH_B),
     (False, False, Label.NO_PATCH_BOTH)],
)
def test_missing_patches_are_agent_failures(a_patch, b_patch, expected) -> None:
    c = classify(agent(has_patch=a_patch), agent(has_patch=b_patch),
                 MergeResult(MergeOutcome.NOT_ATTEMPTED))
    assert c.label is expected
    assert not c.genuine_integration_failure
    assert not c.individually_broken


def test_harness_error_short_circuits_and_is_excluded_from_rates() -> None:
    c = classify(agent(), agent(), MergeResult(MergeOutcome.CLEAN, P, P),
                 harness_error="container died")
    assert c.label is Label.HARNESS_ERROR
    assert not c.label.counts_toward_rates


def test_merge_never_attempted_despite_good_patches_is_a_harness_error() -> None:
    """Not an integration failure: we simply failed to run the experiment."""
    c = classify(agent(), agent(), MergeResult(MergeOutcome.NOT_ATTEMPTED))
    assert c.label is Label.HARNESS_ERROR


def test_overlapping_features_are_flagged_not_silently_counted() -> None:
    """If one patch alone already satisfies both suites, the pair is suspect."""
    c = classify(agent(partner=P), agent(partner=F),
                 MergeResult(MergeOutcome.CLEAN, P, F))
    assert c.label is Label.INTEGRATION_FAILURE_TESTS
    assert any("overlap" in w for w in c.warnings), c.warnings


# --- test-output interpretation -------------------------------------------
#
# These pin the three bugs the gold-patch oracle caught before any money was
# spent.  Each would have silently corrupted the corpus's headline metric.

from farm.grade import CommandRun, interpret_tests  # noqa: E402


def _run(stdout: str = "", stderr: str = "", code: int | None = 0,
         timed_out: bool = False) -> CommandRun:
    return CommandRun(argv=["x"], cwd=".", exit_code=code, duration_s=1.0,
                      timed_out=timed_out, stdout=stdout, stderr=stderr,
                      started_at="t0", finished_at="t1")


def test_importerror_inside_real_test_output_is_still_a_failure() -> None:
    """jinja's suite prints ImportError a dozen times while running fine.

    Treating that as an infrastructure error turned a correct patch into a
    broken one, and would have suppressed a genuine integration failure.
    """
    out = (
        "FAILED tests/test_ext.py::TestConditionalInternationalization::test_x\n"
        "E   ImportError: cannot import name 'foo'\n" * 12 +
        "========================= 8 failed, 47 passed in 0.26s ========================="
    )
    outcome, detail = interpret_tests(_run(out, code=1))
    assert outcome is TestOutcome.FAIL, detail
    assert detail["saw_test_summary"]


def test_patch_that_would_not_apply_is_an_error_not_a_failure() -> None:
    """git exits 128 before any test runs; blaming the code would be wrong."""
    out = "Applying feature patch: merged.patch\nCleaning up repository...\n"
    err = "error: corrupt patch at line 380\n"
    outcome, detail = interpret_tests(_run(out, err, code=128))
    assert outcome is TestOutcome.ERROR, detail
    assert detail.get("patch_apply_failed")
    assert "did not apply" in detail["reason"]


def test_nonzero_exit_with_no_summary_is_an_error() -> None:
    outcome, detail = interpret_tests(_run("Cleaning up repository...\n", code=128))
    assert outcome is TestOutcome.ERROR
    assert not detail["saw_test_summary"]


def test_clean_pass_is_a_pass() -> None:
    out = "Tests:       17 passed, 17 total\nTest Suites: 1 passed, 1 total\n"
    assert interpret_tests(_run(out, code=0))[0] is TestOutcome.PASS


def test_exit_zero_without_a_summary_is_not_a_pass() -> None:
    """A runner that silently did nothing must not read as success."""
    assert interpret_tests(_run("Repository cleaned.\n", code=0))[0] is TestOutcome.ERROR


def test_zero_collected_is_not_a_pass() -> None:
    out = "collected 0 items\n\n===== no tests ran in 0.01s =====\n0 passed\n"
    assert interpret_tests(_run(out, code=0))[0] is TestOutcome.ERROR


def test_timeout_is_an_error() -> None:
    assert interpret_tests(_run("", code=None, timed_out=True))[0] is TestOutcome.ERROR


def test_go_and_cargo_summaries_are_recognised() -> None:
    assert interpret_tests(_run("ok  \tgithub.com/go-chi/chi\t0.1s\n", code=0))[0] is TestOutcome.PASS
    assert interpret_tests(_run("test result: ok. 5 passed; 0 failed\n", code=0))[0] is TestOutcome.PASS
    assert interpret_tests(_run("--- FAIL: TestX\nFAIL\tpkg\t0.2s\n", code=1))[0] is TestOutcome.FAIL
