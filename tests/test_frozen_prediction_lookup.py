"""A plan that names its prediction keys clearly must not crash the runner.

c07's first episode ran both lanes and both repair lanes, was graded twice, and
then died on the last statement that assembles its record, because the plan
keyed its predictions `bare_semantic`/`roomed_semantic` -- its endpoint is a
count, not a rate -- and the runner looked up `plan["predictions"][arm]`.

$0.5459 of billed work reached the disk with no record written. The lookup is
now tolerant, and this pins it, because the failure mode is the worst shape
there is: it costs money before it fails, and it fails after the money is gone.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runner", REPO / "scripts" / "run_room_episode.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def test_the_plain_arm_key_is_used_when_present():
    plan = {"predictions": {"bare": "b", "roomed": "r"}}
    assert runner.frozen_for(plan, "bare") == "b"
    assert runner.frozen_for(plan, "roomed") == "r"


def test_an_endpoint_suffixed_key_is_found_too():
    plan = {"predictions": {"bare_semantic": "b", "roomed_semantic": "r"}}
    assert runner.frozen_for(plan, "bare") == "b"
    assert runner.frozen_for(plan, "roomed") == "r"


def test_an_unrecognised_shape_records_everything_rather_than_raising():
    """Recording too much beats losing an episode that has already been paid
    for. The record is meant to be readable, not minimal."""
    plan = {"predictions": {"something_else": "x"}}
    got = runner.frozen_for(plan, "bare")
    assert "something_else" in got
    assert json.loads(got) == {"something_else": "x"}


def test_a_plan_with_no_predictions_does_not_raise():
    assert runner.frozen_for({}, "bare") == "{}"


def test_every_shipped_plan_resolves_for_both_arms():
    for name in ("c06_room.json", "c06b_rerun.json", "c07_semantic_rate.json"):
        plan = json.loads((REPO / "config" / name).read_text())
        for arm in {e["arm"] for e in plan["episodes"]}:
            frozen = runner.frozen_for(plan, arm)
            assert frozen and frozen != "{}", (name, arm)
