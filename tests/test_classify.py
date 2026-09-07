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
