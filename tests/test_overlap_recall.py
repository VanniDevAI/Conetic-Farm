"""What the census classifier does on pairs that are *known* to be semantic.

`farm.overlap.classify_overlap` produced the census: 646 usable CooperBench
TypeScript pairs, none of them `semantic`.  A count of zero is only as good as
the classifier's recall, and until now nothing measured that, because the
corpus had no confirmed positives to measure it against.

The two seeded pairs are confirmed positives: each is gold-validated to give a
clean merge with A passing alone, B passing alone, and B failing merged.  So
they are exactly the labelled set the census figure needs.

The classifier calls both `independent`.  That is not a bug to patch here --
it follows from what a diff makes visible.  `classify_overlap` reads symbols
off *changed* lines, and in both pairs the edge is one hop away: B's changed
lines name a consumer, and only that consumer's own body names the provider A
changed.  Following that hop is claim-map work, not diff work.

The test therefore pins the measurement rather than a wished-for verdict: if
someone later teaches the classifier to resolve one hop, this fails and the
census has to be recomputed and re-reported.
"""
import os
from pathlib import Path

import pytest

from farm.identity import build_index
from farm.overlap import classify_overlap, parse_patch, semantic_link

SEEDS = Path(__file__).resolve().parents[1] / "dataset" / "seeded"

# (pair, provider file, consumer file, the hop the diff cannot see)
KNOWN_SEMANTIC = [
    ("tanstack_query_task/task1",
     "packages/query-core/src/utils.ts",
     "packages/query-core/src/query.ts",
     "query.ts::isStaleByTime -> utils.ts::timeUntilStale"),
    ("zod_task/task1",
     "packages/zod/src/v4/core/util.ts",
     "packages/zod/src/v4/core/checks.ts",
     "checks.ts::$ZodCheckMultipleOf -> util.ts::floatSafeRemainder"),
]


def _facts(pair: str, feature: str):
    return parse_patch((SEEDS / pair / feature / "feature.patch").read_text())


def test_known_semantic_pairs_touch_disjoint_files():
    """Precondition for the census claim: no textual signal at all."""
    for pair, provider, consumer, _ in KNOWN_SEMANTIC:
        a, b = _facts(pair, "feature1"), _facts(pair, "feature2")
        assert set(a.files) == {provider}, pair
        assert set(b.files) == {consumer}, pair
        assert not (set(a.files) & set(b.files)), pair


def test_census_classifier_recall_on_known_semantic_pairs_is_zero():
    """Both confirmed positives are classified `independent`, not `semantic`.

    So "646 pairs, 0 semantic" is a lower bound under a one-hop-blind
    heuristic, and must be reported as one.
    """
    verdicts = {
        pair: classify_overlap(_facts(pair, "feature1"), _facts(pair, "feature2"))
        for pair, _, _, _ in KNOWN_SEMANTIC
    }
    assert verdicts == {pair: "independent" for pair, _, _, _ in KNOWN_SEMANTIC}


def test_the_missed_hop_is_absent_from_both_diffs():
    """Names the reason: the provider symbol never appears on a changed line."""
    for pair, _, _, hop in KNOWN_SEMANTIC:
        provider_symbol = hop.rsplit("::", 1)[1]
        b = _facts(pair, "feature2")
        assert provider_symbol not in b.symbols, (pair, hop)


# The identity graph is built from a checkout of the repository at the pair's
# base commit. These live outside the repository, so the resolved tests skip
# rather than fail when a checkout is not present.
_CHECKOUTS = {
    "tanstack_query_task/task1": os.environ.get("FARM_QUERY_CHECKOUT"),
    "zod_task/task1": os.environ.get("FARM_ZOD_CHECKOUT"),
}

_EXPECTED_CHAIN = {
    "tanstack_query_task/task1": ["isStaleByTime", "timeUntilStale"],
    "zod_task/task1": ["$ZodCheckMultipleOf", "floatSafeRemainder"],
}


def _index_for(pair: str):
    root = _CHECKOUTS.get(pair)
    if not root or not Path(root).is_dir():
        pytest.skip(f"no checkout for {pair}; set the env var to enable")
    return build_index(Path(root))


@pytest.mark.parametrize("pair", list(_EXPECTED_CHAIN))
def test_resolved_classifier_finds_the_hop_the_diff_hides(pair):
    """With the identity graph, both confirmed positives come back semantic."""
    idx = _index_for(pair)
    a, b = _facts(pair, "feature1"), _facts(pair, "feature2")
    assert classify_overlap(a, b, idx) == "semantic"
    assert semantic_link(a, b, idx) == _EXPECTED_CHAIN[pair]


def test_resolution_does_not_reclassify_a_pair_that_shares_a_file():
    """Precedence is unchanged: a pair git refuses stays `textual`.

    This is why supplying the graph cannot move the census count on a corpus
    whose every pair shares a file, and the census report has to say so
    instead of implying the fix was inert.
    """
    a = parse_patch(
        "diff --git a/x.ts b/x.ts\n--- a/x.ts\n+++ b/x.ts\n"
        "@@ -1,3 +1,3 @@\n ctx\n-old\n+new\n ctx\n")
    b = parse_patch(
        "diff --git a/x.ts b/x.ts\n--- a/x.ts\n+++ b/x.ts\n"
        "@@ -1,3 +1,3 @@\n ctx\n-old2\n+new2\n ctx\n")
    assert classify_overlap(a, b) == "textual"
    assert classify_overlap(a, b, object()) == "textual"
