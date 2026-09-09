"""Every episode says whether the claim map named the mechanism, with a reason.

The field exists because of the gap CE-007 made unmissable. The claim map
always emits *a* chain between two patches that touch related code; sometimes
that chain is why the product broke and sometimes it is a true statement that
explains nothing. CE-007's chain, `postRouter -> defaultPostSelect`, is correct
about the patches and silent about two test files racing on one sqlite file.

Reading the corpus with the field in place gives the finding it was added to
expose: the map names the mechanism on every episode built around a symbol it
was designed to find, and on neither unseeded semantic failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from farm.episode_record import EpisodeSchemaError, SPLITS, validate

EPISODES = Path(__file__).resolve().parents[1] / "farm" / "episodes"
ALL = sorted(EPISODES.glob("*.json"))


def _load(name):
    return json.loads((EPISODES / f"{name}.json").read_text())


def test_every_banked_episode_carries_the_field():
    assert ALL, "no episodes to check"
    for path in ALL:
        rec = json.loads(path.read_text())
        m = rec.get("mechanism_named_by_claim_map")
        assert m, path.name
        assert m["named"] in (True, False, None), path.name
        assert m["why"], f"{path.name}: a yes or no with no reason"


def test_the_schema_refuses_a_verdict_with_no_reason():
    rec = _load("CE-007")
    rec["mechanism_named_by_claim_map"] = {"named": True, "why": ""}
    with pytest.raises(EpisodeSchemaError, match="assertion"):
        validate(rec)


def test_the_schema_refuses_a_missing_field():
    rec = _load("CE-006")
    del rec["mechanism_named_by_claim_map"]
    with pytest.raises(EpisodeSchemaError):
        validate(rec)


def test_observed_is_a_split():
    assert SPLITS == {"gold", "observed", "train"}
    assert _load("CE-007")["split"] == "observed"
    assert _load("CE-007")["split_why"]


def test_the_two_unseeded_semantic_episodes_are_the_ones_it_could_not_name():
    """The finding, pinned so a later edit cannot quietly soften it.

    CE-002, CE-003 and CE-004 were built around a symbol the map was designed
    to follow, and it named all three. CE-006 and CE-007 were not built at all,
    and it named neither.
    """
    for cid in ("CE-002", "CE-003", "CE-004"):
        assert _load(cid)["mechanism_named_by_claim_map"]["named"] is True, cid
    for cid in ("CE-006", "CE-007"):
        rec = _load(cid)
        assert rec["failure_class"] == "semantic", cid
        assert rec["corpus"].get("unseeded") is True, cid
        assert rec["mechanism_named_by_claim_map"]["named"] is False, cid


def test_a_promoted_episode_and_its_source_agree():
    """CE-006 and c06b-pair1-bare are the same episode; so are CE-007 and
    c07-ep05-roomed. A generic rule must not give one of them a different
    answer from the read one."""
    for promoted, source in (("CE-006", "c06b-pair1-bare"),
                             ("CE-007", "c07-ep05-roomed")):
        assert (_load(promoted)["mechanism_named_by_claim_map"]["named"]
                == _load(source)["mechanism_named_by_claim_map"]["named"]), promoted
