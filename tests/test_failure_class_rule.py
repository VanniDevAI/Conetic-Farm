"""A broken lane is not an integration failure, however the merge went.

The rule this pins cost a headline number in c06b. Two episodes merged cleanly
with a failing combined suite; only one of them was two correct branches
disagreeing. The other had a lane that was already red, and counting it as
`semantic` would have doubled the campaign's rarest and most load-bearing
finding on the strength of a bug in one branch.
"""

from __future__ import annotations

from farm.failure_class import classify, stealth


def test_a_refused_merge_is_textual_whatever_the_lanes_did():
    assert classify("conflict", None, True)[0] == "textual"
    assert classify("conflict", None, False)[0] == "textual"


def test_clean_merge_all_lanes_green_and_a_broken_tree_is_semantic():
    cls, why = classify("clean", "fail", True)
    assert cls == "semantic"
    assert "every lane is green" in why


def test_clean_merge_with_a_lane_already_red_is_not_an_integration_failure():
    """c06b-pair3-bare: lane2's own author.test.ts failed on its own branch and
    went on failing after the merge. Nothing interacted."""
    cls, why = classify("clean", "fail", False)
    assert cls is None
    assert "own defect" in why


def test_a_clean_merge_that_passes_is_no_failure():
    assert classify("clean", "pass", True)[0] is None


def test_no_merge_is_no_class():
    assert classify(None, None, True)[0] is None


def test_only_the_semantic_class_is_ever_stealthy():
    assert stealth("semantic", "clean", True)["flag"] is True
    assert stealth("textual", "conflict", True)["flag"] is None
    assert stealth(None, "clean", True)["flag"] is None


def test_a_red_lane_makes_a_broken_merged_tree_explicitly_not_stealthy():
    """Not None -- False. It was catchable, and the record should say so
    rather than leave the question unasked."""
    s = stealth(None, "clean", False)
    assert s["flag"] is False
    assert "catchable" in s["why"]


def test_a_refused_merge_is_never_stealthy():
    for green in (True, False):
        assert stealth("textual", "conflict", green)["flag"] is None
