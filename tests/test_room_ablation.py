"""The room's closing protocol is off, and the task is what the prompt ends on.

c06 and c06b appended the room after the task brief, so the last thing a roomed
agent read was the room's own "Only then start editing. Do not skip step 1".
Roomed lanes then skipped the submit step at 5 of 12 against bare's 1 of 12
(pooled, p = 0.155): feature written, suite green, prose summary, no git.

Nothing in that closing block is wrong. It is simply last, and it is an
instruction to begin rather than to finish. So the facts move in front of the
task and the block comes out, leaving the task's own working agreement -- keep
tsc clean, keep vitest green -- as the final instruction.

Pinned here because it is a silent property: a prompt assembled the other way
round still looks perfectly reasonable, and the only symptom is lanes that do
the work and never publish it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from farm.room_brief import PROTOCOL, build

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runner", REPO / "scripts" / "run_room_episode.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

BRIEF = "dataset/field/trpc_starter/c06/pair1/lane1/feature.md"
ROOM = "\n## The room\n\n### What is already claimed\n\n* route names: `add`\n"


def test_the_default_room_has_no_closing_protocol(tmp_path):
    room = build(tmp_path, [], index=_empty_index())
    assert "Only then start editing" not in room
    assert "Do not skip step 1" not in room


def test_the_old_form_is_still_reachable(tmp_path):
    """Kept rather than deleted: c06 and c06b must stay reproducible, and a
    future arm should be able to test the facts and the protocol separately."""
    room = build(tmp_path, [], index=_empty_index(), closing_protocol=True)
    assert "Only then start editing" in room


def test_the_default_placement_puts_the_facts_before_the_task():
    cfg = runner.ROOM_DEFAULTS
    assert cfg["placement"] == "before_brief"
    assert cfg["closing_protocol"] is False
    out = runner.assemble(BRIEF, ROOM, cfg)
    assert out.index("## The room") < out.index("## Working agreement")


def test_the_prompt_ends_on_the_task_not_on_the_room():
    out = runner.assemble(BRIEF, ROOM, runner.ROOM_DEFAULTS)
    assert out.rstrip().endswith(
        (REPO / BRIEF).read_text().rstrip()[-60:])


def test_the_old_assembly_ended_on_the_protocol():
    """What c06b actually did, kept as the contrast the ablation is against."""
    as_run = {"placement": "after_brief", "closing_protocol": True}
    out = runner.assemble(BRIEF, PROTOCOL, as_run)
    assert out.rstrip().endswith(PROTOCOL.strip()[-60:])


def test_a_lane_with_no_room_is_untouched_by_placement():
    """The bare arm must assemble identically whatever the room config says."""
    plain = (REPO / BRIEF).read_text()
    for placement in ("before_brief", "after_brief"):
        cfg = {"placement": placement, "closing_protocol": False}
        assert runner.assemble(BRIEF, "", cfg) == plain


def test_the_runs_that_used_the_old_form_still_say_so():
    """A plan that ran the old way records it, or re-running it would quietly
    reproduce something else."""
    for name in ("c06_room.json", "c06b_rerun.json"):
        plan = json.loads((REPO / "config" / name).read_text())
        assert plan["room"]["placement"] == "after_brief", name
        assert plan["room"]["closing_protocol"] is True, name


def _empty_index():
    from farm.identity import Index
    return Index()
