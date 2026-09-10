"""`max_hops=k` must mean k edges, because every number in the campaign says so.

Found while grading the merge-clean census pairs. Test reachability came back
identical at one, two and three hops, which is what a saturated metric looks
like -- and it was, because `max_hops=1` was already walking two edges.

The consequence is not cosmetic. The census ran at `max_hops=3` and reported
503 of 652 pairs linked; that figure was really four edges of reachability. In
a library where everything names something that names something, one extra edge
is a large difference, and hop count is the only knob that makes "linked" mean
anything narrower than "in the same repository".

The contract, stated as the docstring always stated it:

    max_hops=1  the consumer's own body names the provider
    max_hops=2  the consumer's body names something whose body names it
    max_hops=k  a chain of at most k edges, so at most k+1 names
"""

from __future__ import annotations

from farm.identity import Definition, Index, reaches


def _chain(*names: str) -> tuple[Index, list[Definition]]:
    """A straight line: names[0] -> names[1] -> ... , one definition per file."""
    defs = [Definition(n, f"{n.lower()}.py", 1, 10) for n in names]
    refs = {d: frozenset({nxt.name}) for d, nxt in zip(defs, defs[1:])}
    refs[defs[-1]] = frozenset()
    return Index(by_name={d.name: [d] for d in defs},
                 by_path={d.path: [d] for d in defs},
                 refs=refs), defs


def test_one_hop_is_one_edge():
    idx, (a, b, c) = _chain("A", "B", "C")
    assert reaches(idx, {a}, {b}, max_hops=1) == ["A", "B"]
    assert reaches(idx, {a}, {c}, max_hops=1) is None, (
        "A reaches C in two edges; a one-hop budget must not find it")


def test_two_hops_is_two_edges():
    idx, (a, b, c) = _chain("A", "B", "C")
    assert reaches(idx, {a}, {c}, max_hops=2) == ["A", "B", "C"]


def test_the_budget_bounds_the_chain_length_at_every_k():
    idx, defs = _chain("A", "B", "C", "D", "E")
    a, e = defs[0], defs[-1]
    for k in (1, 2, 3):
        assert reaches(idx, {a}, {e}, max_hops=k) is None, k
    assert reaches(idx, {a}, {e}, max_hops=4) == ["A", "B", "C", "D", "E"]


def test_a_returned_chain_never_exceeds_its_budget():
    idx, defs = _chain("A", "B", "C", "D", "E")
    for k in (1, 2, 3, 4):
        for target in defs[1:]:
            got = reaches(idx, {defs[0]}, {target}, max_hops=k)
            if got is not None:
                assert len(got) <= k + 1, (k, got)


def test_zero_hops_finds_nothing():
    idx, (a, b, _) = _chain("A", "B", "C")
    assert reaches(idx, {a}, {b}, max_hops=0) is None


def test_a_definition_that_is_its_own_target_needs_no_edge():
    """Start and target overlapping is not a chain; it is the same node."""
    idx, (a, _, _) = _chain("A", "B", "C")
    assert reaches(idx, {a}, {a}, max_hops=1) is None
