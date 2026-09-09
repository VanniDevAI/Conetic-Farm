"""Billed-cost ceilings, salvage, and the reserve that stops an overrun.

`c05b` overran a $10 cap by $0.47 and got one measurable episode from three.
Every mechanism here exists because of a specific thing that went wrong in it.
"""
from __future__ import annotations

from pathlib import Path

from farm.lane_budget import Reserve


def test_a_lane_is_refused_when_the_remainder_cannot_cover_the_worst_lane():
    """Checking for a positive balance is what put c05b over its cap.

    A lane started at $4.92 under a $5.05 ceiling and finished at $5.45.
    """
    r = Reserve(cap_usd=5.05, floor_usd=0.5)
    r.observe(0.52)
    ok, why = r.may_start(spent=4.92)
    assert ok is False
    assert "could overrun" in why


def test_the_reserve_grows_to_the_worst_lane_actually_seen():
    r = Reserve(cap_usd=10.0, floor_usd=0.5)
    assert r.required == 0.5
    r.observe(0.52)
    r.observe(4.3948)          # the sonnet lane that billed 1.75x its ceiling
    r.observe(0.02)
    assert r.required == 4.3948


def test_a_lane_may_start_while_the_remainder_covers_the_worst():
    r = Reserve(cap_usd=10.0, floor_usd=1.0)
    r.observe(2.0)
    assert r.may_start(spent=7.0)[0] is True
    assert r.may_start(spent=8.5)[0] is False


def test_the_floor_applies_before_any_lane_has_been_observed():
    """The first lane of a campaign has no history to reserve against."""
    r = Reserve(cap_usd=1.2, floor_usd=1.0)
    assert r.may_start(spent=0.0)[0] is True
    assert r.may_start(spent=0.5)[0] is False


def test_salvage_writes_nothing_when_the_container_has_nothing(tmp_path: Path):
    """A container that cannot be reached must not leave an empty patch behind.

    An empty file would read as "the lane produced nothing", which is a
    different claim from "the lane could not be salvaged".
    """
    from farm.lane_budget import salvage
    dest = tmp_path / "lane.patch"
    lines = salvage("no-such-container", "deadbeef", dest)
    assert lines == 0
    assert not dest.exists()
