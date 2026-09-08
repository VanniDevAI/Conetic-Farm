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
    def failure_class(self) -> str | None:
        """`textual`, `semantic`, or None for anything that is not a genuine
        integration failure.

        The two are different phenomena and only one is evidence for a
        claim-map engine:

        * **textual** -- the three-way merge refuses; two patches touched
          overlapping lines. Git can already see this, and the combined tests
          never run.
        * **semantic** -- the merge succeeds cleanly and the *combined* tests
          fail. Textually compatible, behaviourally incompatible. No merge tool
          can see it, which is the gap a claim map exists to close *before* the
          merge.

        Reported as one number these hide the distinction that decides whether a
        result supports the thing being built, so the class travels with the
        label rather than being assembled where it is printed.
        """
        if self is Label.INTEGRATION_FAILURE_MERGE:
            return "textual"
        if self is Label.INTEGRATION_FAILURE_TESTS:
            return "semantic"
        return None

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


def ungradeable_reason(detail: dict | None) -> str | None:
    """Why this side could not be graded at all, or None if it was graded.

    `c03` found 5 of 30 patches erroring because the *dataset's* test patch
    would no longer apply -- the agent had edited the very file that grades it::

        error: patch failed: tests/test_context.py:543
        error: tests/test_context.py: patch does not apply

    The grader never ran, so nothing was shown about the patch.  Counting that
    as "individually broken" is safe but it is a different claim from "failed
    its tests", and it depresses the measured pass rate `p` with cases carrying
    no evidence either way -- and `p` is the quantity the experiment turns on.

    Deliberately narrow.  The other 9 `error` cases in `c03` were real breakage
    (a `SyntaxError` in the agent's own edit stopping `conftest.py` importing);
    the grader ran and rejected them.  A distinction that swallowed those would
    be worse than no distinction at all.  Only a test patch that would not apply
    counts.
    """
    if not detail or not detail.get("patch_apply_failed"):
        return None
    why = str(detail.get("reason") or "the graded test patch would not apply")
    return f"ungradeable: the test patch could not be applied over the agent's edit ({why})"


@dataclass
class AgentResult:
    """One agent's patch, tested alone against a fresh base."""

    has_patch: bool
    own_tests: TestOutcome            # this agent's feature tests
    partner_tests: TestOutcome        # the *other* feature's tests, same patch
    patch_bytes: int = 0
    files_changed: int = 0
    # The grader's own detail for the "own tests" run, so `ungradeable` can be
    # decided from what actually happened rather than re-derived from a label.
    own_detail: dict | None = None

    @property
    def ungradeable(self) -> str | None:
        return ungradeable_reason(self.own_detail)

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
    # Recorded as its own fact, not as a label: an agent that edited the test
    # file grading it was never graded, which is a different claim from failing.
    # Labels stay comparable across campaigns; the corpus gains the distinction.
    for side, r in (("a", a), ("b", b)):
        ev[side]["ungradeable"] = r.ungradeable
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
            why = r.ungradeable
            warns.append(
                f"agent {name} was not gradeable: it edited the test file that grades it"
                if why else
                f"agent {name}'s own test suite errored rather than failing cleanly")
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
