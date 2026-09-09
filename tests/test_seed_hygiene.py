"""A seeded brief must never ask an agent to edit the file that grades it.

Both `s02` control episodes died on this. `feature.md` said "update the `hashKey`
tests in `utils.test.tsx`" and "add tests in `infiniteQueryBehavior.test.tsx`" —
which are exactly the files the graded `tests.patch` patches. The graded patch
then cannot apply, the agent is **ungradeable by construction**, and the episode
measures nothing. Two episodes, $4.85, no measurement.

CooperBench's own tasks keep the separation: the agent writes the feature, the
graded tests arrive from `tests.patch` at grading time. An agent is free to write
its own tests wherever it likes; what a brief must not do is *direct* it into the
graded file.

This walks every seeded task and fails if a brief names a path its own
`tests.patch` touches.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEEDS = REPO / "dataset" / "seeded"


def _features():
    if not SEEDS.exists():
        return []
    return sorted(p for p in SEEDS.glob("*/task*/feature*") if (p / "feature.md").exists())


@pytest.mark.parametrize("feature", _features(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_brief_does_not_name_its_own_graded_test_file(feature: Path) -> None:
    tests_patch = feature / "tests.patch"
    if not tests_patch.exists() or not tests_patch.read_text().strip():
        pytest.skip("no graded tests for this feature")
    graded = set(re.findall(r"^\+\+\+ b/(\S+)", tests_patch.read_text(), re.M))
    brief = (feature / "feature.md").read_text()
    named = [g for g in graded if g in brief or Path(g).name in brief]
    assert not named, (
        f"{feature.parent.name}/{feature.name}'s brief names the file that grades it: "
        f"{named}. The graded test patch will not apply over the agent's edit and the "
        f"agent will be ungradeable by construction.")


def test_there_is_at_least_one_seeded_feature_to_check() -> None:
    """A vacuous guard is worse than none: it reads as enforcement."""
    assert _features(), "no seeded features found; this guard is checking nothing"
