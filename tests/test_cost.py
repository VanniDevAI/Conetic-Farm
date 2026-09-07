"""The spend cap must be a wall, not a suggestion."""

from __future__ import annotations

import json
import pytest

from farm.cost import Budget, BudgetExceeded, Price, Usage


def test_price_arithmetic() -> None:
    p = Price(prompt_per_mtok=0.30, completion_per_mtok=1.20)
    assert p.cost(1_000_000, 0) == pytest.approx(0.30)
    assert p.cost(0, 1_000_000) == pytest.approx(1.20)
    assert p.cost(400_000, 50_000) == pytest.approx(0.12 + 0.06)


def test_cached_prompt_tokens_are_discounted() -> None:
    p = Price(prompt_per_mtok=1.0, completion_per_mtok=1.0, cached_prompt_per_mtok=0.1)
    # 1M prompt tokens of which 900k cached
    assert p.cost(1_000_000, 0, cached_prompt_tokens=900_000) == pytest.approx(
        (100_000 * 1.0 + 900_000 * 0.1) / 1_000_000
    )


def test_reserve_refuses_to_cross_the_cap(tmp_path) -> None:
    b = Budget(cap_usd=10.0, ledger_path=tmp_path / "ledger.jsonl")
    b.reserve("h1", 6.0)
    with pytest.raises(BudgetExceeded):
        b.reserve("h2", 5.0)          # 6 + 5 > 10
    b.reserve("h2", 4.0)              # 6 + 4 == 10, exactly at the cap
    with pytest.raises(BudgetExceeded):
        b.reserve("h3", 0.01)


def test_holds_prevent_concurrent_overshoot(tmp_path) -> None:
    """Two agents holding budget cannot jointly exceed the cap."""
    b = Budget(cap_usd=1.0, ledger_path=tmp_path / "l.jsonl")
    b.reserve("a", 0.6)
    with pytest.raises(BudgetExceeded):
        b.reserve("b", 0.6)
    assert b.exposure_usd == pytest.approx(0.6)


def test_settle_replaces_the_hold_with_actual_cost(tmp_path) -> None:
    b = Budget(cap_usd=10.0, ledger_path=tmp_path / "l.jsonl")
    b.reserve("h1", 5.0)
    assert b.exposure_usd == pytest.approx(5.0)
    b.settle("h1", 0.42, usage=Usage(prompt_tokens=1000, completion_tokens=100))
    assert b.committed_usd == pytest.approx(0.42)
    assert b.held_usd == pytest.approx(0.0)
    assert b.remaining_usd == pytest.approx(9.58)


def test_release_drops_a_hold_without_charge(tmp_path) -> None:
    b = Budget(cap_usd=10.0, ledger_path=tmp_path / "l.jsonl")
    b.reserve("h1", 5.0)
    b.release("h1", note="agent never started")
    assert b.exposure_usd == pytest.approx(0.0)
    assert b.committed_usd == pytest.approx(0.0)


def test_settling_past_the_cap_is_recorded_and_blocks_the_next_reserve(tmp_path) -> None:
    """Real spend can overshoot an estimate.  It must not be silently absorbed."""
    b = Budget(cap_usd=1.0, ledger_path=tmp_path / "l.jsonl")
    b.reserve("h1", 0.5)
    b.settle("h1", 1.5)               # cost more than estimated
    assert b.committed_usd == pytest.approx(1.5)
    assert b.remaining_usd == 0.0
    assert b.summary()["cap_reached"] is True
    with pytest.raises(BudgetExceeded):
        b.reserve("h2", 0.01)


def test_ledger_survives_restart(tmp_path) -> None:
    """A crashed run must not lose track of money already spent."""
    path = tmp_path / "l.jsonl"
    b1 = Budget(cap_usd=10.0, ledger_path=path)
    b1.reserve("h1", 3.0)
    b1.settle("h1", 2.5)
    b1.reserve("h2", 1.0)             # still outstanding when we "crash"

    b2 = Budget(cap_usd=10.0, ledger_path=path)
    assert b2.committed_usd == pytest.approx(2.5)
    assert b2.held_usd == pytest.approx(1.0)
    assert b2.exposure_usd == pytest.approx(3.5)


def test_torn_final_line_does_not_break_replay(tmp_path) -> None:
    path = tmp_path / "l.jsonl"
    b = Budget(cap_usd=10.0, ledger_path=path)
    b.reserve("h1", 1.0)
    b.settle("h1", 1.0)
    with path.open("a") as fh:
        fh.write('{"kind": "settle", "amount_usd": 5.0')   # truncated by a kill
    b2 = Budget(cap_usd=10.0, ledger_path=path)
    assert b2.committed_usd == pytest.approx(1.0)


def test_ledger_never_contains_a_key_shaped_string(tmp_path) -> None:
    path = tmp_path / "l.jsonl"
    b = Budget(cap_usd=10.0, ledger_path=path)
    b.reserve("h1", 1.0, model="openrouter/qwen/qwen3-coder")
    b.settle("h1", 1.0, usage=Usage(prompt_tokens=10, completion_tokens=1))
    text = path.read_text()
    assert "sk-or-" not in text
    for line in text.splitlines():
        json.loads(line)              # every line is valid JSON


# --- pinned pricing -------------------------------------------------------

from farm.cost import (  # noqa: E402
    MissingPrice, ZeroCostWithUsage, cost_of, load_pricing, price_for,
)


def test_pinned_table_covers_the_campaign_model() -> None:
    table = load_pricing()
    p = price_for("openrouter/qwen/qwen3-coder", table)
    assert p.prompt_per_mtok == pytest.approx(0.30)
    assert p.completion_per_mtok == pytest.approx(1.00)


def test_missing_price_raises_rather_than_costing_zero() -> None:
    with pytest.raises(MissingPrice):
        price_for("openrouter/not/a-real-model", load_pricing())


def test_zero_cost_with_real_usage_is_refused() -> None:
    """The exact failure that recorded $0 for 400k+ billable tokens upstream."""
    free = {"free/model": Price(prompt_per_mtok=0.0, completion_per_mtok=0.0)}
    with pytest.raises(ZeroCostWithUsage):
        cost_of("free/model", Usage(prompt_tokens=400_000, completion_tokens=50_000), free)
    # Zero usage genuinely costs zero, and must not raise.
    assert cost_of("free/model", Usage(), free) == 0.0


def test_realistic_episode_cost() -> None:
    """Two agents, ~400k prompt + 50k completion each, at pinned prices."""
    table = load_pricing()
    per_agent = cost_of("openrouter/qwen/qwen3-coder",
                        Usage(prompt_tokens=400_000, completion_tokens=50_000), table)
    assert per_agent == pytest.approx(400_000 * 0.30 / 1e6 + 50_000 * 1.00 / 1e6)
    episode = 2 * per_agent
    assert 0.20 < episode < 0.60, episode        # sanity band for the estimate
