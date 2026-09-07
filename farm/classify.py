"""Failure taxonomy for a two-agent episode.

The whole corpus turns on one distinction:

  * an **individually broken patch** — an agent's own patch fails its own
    feature tests, with no partner involved; and
  * a **genuine integration failure** — both patches pass their own tests in
    isolation, and combining them fails.

Everything here exists to keep those apart, and to refuse to guess when the
evidence does not support either.  See docs/DESIGN.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


class Label(str, Enum):
    BOTH_PASS_MERGE_PASSES = "both_pass_merge_passes"
    INTEGRATION_FAILURE_TESTS = "integration_failure_tests"
    INTEGRATION_FAILURE_MERGE = "integration_failure_merge"
    A_BROKEN = "a_broken"
    B_BROKEN = "b_broken"
    BOTH_BROKEN = "both_broken"
    NO_PATCH_A = "no_patch_a"
    NO_PATCH_B = "no_patch_b"
    NO_PATCH_BOTH = "no_patch_both"
    HARNESS_ERROR = "harness_error"

    @property
    def is_genuine_integration_failure(self) -> bool:
        return self in (
            Label.INTEGRATION_FAILURE_TESTS,
            Label.INTEGRATION_FAILURE_MERGE,
        )

    @property
    def is_individually_broken(self) -> bool:
        return self in (Label.A_BROKEN, Label.B_BROKEN, Label.BOTH_BROKEN)

    @property
    def counts_toward_rates(self) -> bool:
        """Harness faults are retained on disk but excluded from headline rates."""
        return self is not Label.HARNESS_ERROR


class TestOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"      # suite could not run (import error, build failure)
    NOT_RUN = "not_run"


class MergeOutcome(str, Enum):
    CLEAN = "clean"
    CONFLICT = "conflict"
    NOT_ATTEMPTED = "not_attempted"
    ERROR = "error"


@dataclass
class AgentResult:
    """One agent's patch, tested alone against a fresh base."""

    has_patch: bool
    own_tests: TestOutcome            # this agent's feature tests
    partner_tests: TestOutcome        # the *other* feature's tests, same patch
    patch_bytes: int = 0
    files_changed: int = 0

    @property
    def passes_alone(self) -> bool:
        return self.has_patch and self.own_tests is TestOutcome.PASS


@dataclass
class MergeResult:
    outcome: MergeOutcome
    a_tests: TestOutcome = TestOutcome.NOT_RUN
    b_tests: TestOutcome = TestOutcome.NOT_RUN
    conflicted_paths: tuple[str, ...] = ()

    @property
    def tests_pass(self) -> bool:
        return self.a_tests is TestOutcome.PASS and self.b_tests is TestOutcome.PASS


@dataclass
class Classification:
    label: Label
    genuine_integration_failure: bool
    individually_broken: bool
    rationale: str
    evidence: dict[str, Any]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label.value
        d["warnings"] = list(self.warnings)
        return d


def classify(
    a: AgentResult,
    b: AgentResult,
    merge: MergeResult,
    *,
    harness_error: str | None = None,
) -> Classification:
    """Assign exactly one label to an attempt.

    Order matters: infrastructure faults first, then missing patches, then
    individually broken patches, and only then — with both patches proven good
    alone — the integration question.
    """
    ev: dict[str, Any] = {
        "a": asdict(a), "b": asdict(b), "merge": asdict(merge),
    }
    warns: list[str] = []

    if harness_error:
        return Classification(
            Label.HARNESS_ERROR, False, False,
            f"infrastructure fault: {harness_error}", ev,
            ("excluded from headline rates",),
        )

    # 1. Missing patches.  An agent that produced nothing is an agent failure;
    #    it tells us nothing about integration.
    if not a.has_patch and not b.has_patch:
        return Classification(Label.NO_PATCH_BOTH, False, False,
                              "neither agent produced a patch", ev)
    if not a.has_patch:
        return Classification(Label.NO_PATCH_A, False, False,
                              "agent A produced no patch", ev)
    if not b.has_patch:
        return Classification(Label.NO_PATCH_B, False, False,
                              "agent B produced no patch", ev)

    # 2. A suite that could not run at all is not evidence of a working patch.
    #    Treat ERROR as "not passing alone" and say so.
    for name, r in (("A", a), ("B", b)):
        if r.own_tests is TestOutcome.ERROR:
            warns.append(f"agent {name}'s own test suite errored rather than failing cleanly")
        if r.own_tests is TestOutcome.NOT_RUN:
            warns.append(f"agent {name}'s own test suite was not run")

    # 3. Individually broken patches.  These are NOT integration failures, and
    #    the merge result is uninformative once a patch is known bad.
    a_ok, b_ok = a.passes_alone, b.passes_alone
    if not a_ok and not b_ok:
        return Classification(Label.BOTH_BROKEN, False, True,
                              "both patches fail their own tests in isolation",
                              ev, tuple(warns))
    if not a_ok:
        return Classification(Label.A_BROKEN, False, True,
                              "agent A's patch fails its own tests in isolation",
                              ev, tuple(warns))
    if not b_ok:
        return Classification(Label.B_BROKEN, False, True,
                              "agent B's patch fails its own tests in isolation",
                              ev, tuple(warns))

    # 4. Both patches are individually correct.  From here, any failure is an
    #    integration failure by construction.
    if merge.outcome is MergeOutcome.CONFLICT:
        return Classification(
            Label.INTEGRATION_FAILURE_MERGE, True, False,
            "both patches pass alone; three-way merge conflicts on "
            f"{len(merge.conflicted_paths)} path(s)", ev, tuple(warns))

    if merge.outcome is MergeOutcome.ERROR:
        return Classification(
            Label.HARNESS_ERROR, False, False,
            "merge step errored for a non-conflict reason", ev,
            tuple(warns) + ("excluded from headline rates",))

    if merge.outcome is MergeOutcome.NOT_ATTEMPTED:
        return Classification(
            Label.HARNESS_ERROR, False, False,
            "merge was never attempted despite both patches passing alone", ev,
            tuple(warns) + ("excluded from headline rates",))

    if not merge.tests_pass:
        failed = [n for n, o in (("A", merge.a_tests), ("B", merge.b_tests))
                  if o is not TestOutcome.PASS]
        # A cross-check worth recording: if a patch alone already passed the
        # partner's tests, the "features" may not be independent.
        if a.partner_tests is TestOutcome.PASS or b.partner_tests is TestOutcome.PASS:
            warns.append(
                "a single patch already passed the partner's tests alone — the "
                "two features may overlap, weakening this as an integration signal")
        return Classification(
            Label.INTEGRATION_FAILURE_TESTS, True, False,
            "both patches pass alone; merged tree fails "
            f"{', '.join(failed)} feature tests", ev, tuple(warns))

    return Classification(Label.BOTH_PASS_MERGE_PASSES, False, False,
                          "both patches pass alone and the merge passes both suites",
                          ev, tuple(warns))
