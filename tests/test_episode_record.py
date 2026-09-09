"""The episode record is the artifact of record, so its shape is tested.

Four campaigns produced their findings as prose plus four differently-shaped
artifact trees, and there was no way to ask "how many semantic episodes were
stealthy" without re-reading four documents. These tests pin the schema that
replaces that, and the two properties the index depends on: it is append-only,
and a re-grade wins.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from farm.episode_record import (SCHEMA_VERSION, EpisodeSchemaError, index_line,
                                 load_episode, load_index, validate, write_episode)

REPO_ROOT = Path(__file__).resolve().parents[1]


def minimal(**over) -> dict:
    rec = {
        "schema_version": SCHEMA_VERSION,
        "id": "CE-TEST", "split": "train",
        "corpus": {"name": "x"}, "seam": {"kind": "none"},
        "lanes": [{"agent": "A", "model": "m", "runtime": "r",
                   "brief": "b", "assumptions": []}],
        "git_outcome": {"outcome": "clean"},
        "product_outcome": {},
        "failure_class": None,
        "stealth": {"flag": None},
        "claim": {"chain": None, "anchor": None},
        "convention_graders": {"migration_ordinals": [], "route_paths": [],
                               "config_keys": []},
        "published_surface": {"published": None},
        "cost": {"usd": 0.0},
        "prediction": {"frozen": "f", "observed": "o", "correct": None, "source": "s"},
        "patches": {}, "merge": {}, "test_logs": {}, "checkpoints": {},
        "mechanism_named_by_claim_map": {"named": None, "why": "no failure"},
    }
    rec.update(over)
    return rec


def test_a_record_missing_a_required_key_is_refused():
    rec = minimal()
    del rec["stealth"]
    with pytest.raises(EpisodeSchemaError, match="stealth"):
        validate(rec)


def test_a_lane_missing_its_own_keys_is_refused():
    with pytest.raises(EpisodeSchemaError, match="lane 0"):
        validate(minimal(lanes=[{"agent": "A", "model": "m"}]))


def test_an_unknown_split_is_refused():
    with pytest.raises(EpisodeSchemaError, match="split"):
        validate(minimal(split="published"))


def test_an_unknown_failure_class_is_refused():
    with pytest.raises(EpisodeSchemaError, match="failure_class"):
        validate(minimal(failure_class="merge_conflict"))


def test_a_prediction_without_its_four_parts_is_refused():
    with pytest.raises(EpisodeSchemaError, match="correct"):
        validate(minimal(prediction={"frozen": "f", "observed": "o", "source": "s"}))


def test_null_is_a_legal_failure_class():
    """An episode where nothing fired is still an episode, and must be storable."""
    validate(minimal(failure_class=None))


def test_writing_appends_to_the_index_and_a_regrade_wins(tmp_path: Path):
    write_episode(minimal(), episodes_dir=tmp_path)
    write_episode(minimal(failure_class="semantic"), episodes_dir=tmp_path)
    lines = (tmp_path / "index.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2, "the index is append-only; a rewrite adds a line"
    assert json.loads(lines[0])["failure_class"] is None
    view = load_index(episodes_dir=tmp_path)
    assert view["CE-TEST"]["failure_class"] == "semantic", "last line wins"
    assert load_episode("CE-TEST", episodes_dir=tmp_path)["failure_class"] == "semantic"


def test_the_index_line_counts_convention_hits(tmp_path: Path):
    rec = minimal(convention_graders={
        "migration_ordinals": [{"ordinal": "0042"}],
        "route_paths": [{"path": "post.add"}, {"path": "post.list"}],
        "config_keys": [],
        "note": "a note is not a hit",
    })
    assert index_line(rec)["convention_hits"] == 3


def test_the_four_backfilled_episodes_are_valid_and_gold():
    directory = REPO_ROOT / "farm" / "episodes"
    ids = ["CE-001", "CE-002", "CE-003", "CE-004"]
    for episode_id in ids:
        rec = load_episode(episode_id)
        validate(rec)
        assert rec["split"] == "gold"
    view = load_index()
    assert set(ids) <= set(view)
    # The finding these four carry, asserted rather than described: exactly one
    # is stealthy, and it is the one whose contract is published.
    stealthy = [i for i in ids if load_episode(i)["stealth"]["flag"]]
    assert stealthy == ["CE-004"]
    assert load_episode("CE-004")["published_surface"]["published"] is True


def test_stealth_is_meaningless_for_a_textual_conflict():
    """Only a semantic failure can be stealthy.

    The first step B episode came back textual with its first lane green, and
    the flag read True -- which says a refused merge escaped notice. It is the
    loudest signal git has. Read the other way the number would have looked
    like evidence for an engine that catches what CI misses, from an episode
    where CI was never the thing that caught it.
    """
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "rfe", Path(__file__).resolve().parents[1] / "scripts" / "run_field_episode.py")
    rfe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rfe)

    green = {"lane1": "pass", "lane2": "pass", "lane3": "pass"}
    # A conflict is the loudest signal git has, whatever the branches look like.
    assert rfe._stealth("textual", "conflict", green, None)["flag"] is None
    # Nothing fired: nothing was missed.
    assert rfe._stealth(None, "clean", green, "pass")["flag"] is None
    # All three conditions together, and only then.
    assert rfe._stealth("semantic", "clean", green, "fail")["flag"] is True
    # One red branch means somebody's CI already had it -- and it is the whole
    # set that matters, not only the first lane.
    mixed = {"lane1": "pass", "lane2": "fail", "lane3": "pass"}
    assert rfe._stealth("semantic", "clean", mixed, "fail")["flag"] is False
