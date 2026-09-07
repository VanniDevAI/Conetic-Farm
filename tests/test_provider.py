"""Pin the provider reconciliation: the cap must bind on real spend, not on a
figure derived from an incomplete transcript."""

from __future__ import annotations

import pytest

from farm import provider


def test_billed_prefers_the_provider_and_exposes_the_gap() -> None:
    """The c01 numbers: a 5x gap must be billed at the provider's figure and the
    ratio must be visible, not averaged away."""
    r = provider.Reconciliation(provider_usd=1.2228, tokens_usd=0.2301,
                                source="provider_delta")
    assert r.billed_usd == 1.2228
    assert r.ratio == 5.314
    d = r.to_dict()
    assert d["provider_usd"] == 1.2228 and d["tokens_usd"] == 0.2301
    assert d["provider_over_tokens"] == 5.314


def test_falls_back_to_tokens_when_provider_unreachable() -> None:
    r = provider.Reconciliation(None, 0.2301, "tokens_only", "unreachable")
    assert r.billed_usd == 0.2301
    assert r.ratio is None
    # Degraded, and it says so, rather than silently reporting zero.
    assert r.to_dict()["source"] == "tokens_only"
    assert r.to_dict()["note"]


def test_settled_usage_waits_for_the_figure_to_stop_climbing(monkeypatch) -> None:
    """OpenRouter settles asynchronously; a read taken the instant an agent stops
    is still rising."""
    reads = iter([1.00, 1.15, 1.22, 1.22])
    monkeypatch.setattr(provider, "account_usage", lambda *a, **k: next(reads))
    got = provider.settled_usage("k", tries=6, interval=0, sleep=lambda _: None)
    assert got == 1.22


def test_settled_usage_returns_last_value_if_it_never_settles(monkeypatch) -> None:
    reads = iter([1.0, 2.0, 3.0, 4.0])
    monkeypatch.setattr(provider, "account_usage", lambda *a, **k: next(reads))
    got = provider.settled_usage("k", tries=4, interval=0, sleep=lambda _: None)
    assert got == 4.0


def test_reconcile_bills_the_delta(monkeypatch) -> None:
    monkeypatch.setattr(provider, "account_usage", lambda *a, **k: 1.5585)
    r = provider.reconcile(before=0.3357, tokens_usd=0.2301, api_key="k",
                           tries=1, sleep=lambda _: None)
    assert r.source == "provider_delta"
    assert r.billed_usd == pytest.approx(1.2228, abs=1e-6)


def test_reconcile_refuses_a_negative_delta(monkeypatch) -> None:
    """Usage is monotonic; a decrease means the readings are not comparable (key
    rotated, account reset).  Never bill a negative."""
    monkeypatch.setattr(provider, "account_usage", lambda *a, **k: 0.5)
    r = provider.reconcile(before=2.0, tokens_usd=0.23, api_key="k",
                           tries=1, sleep=lambda _: None)
    assert r.source == "tokens_only"
    assert r.billed_usd == 0.23
    assert "backwards" in r.note


def test_reconcile_without_a_before_reading_falls_back() -> None:
    r = provider.reconcile(before=None, tokens_usd=0.42)
    assert r.source == "tokens_only" and r.billed_usd == 0.42


def test_account_usage_without_a_key_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert provider.account_usage("") is None


def test_credits_remaining_is_the_binding_fact(monkeypatch) -> None:
    """The campaign cap is a policy; the prepaid balance is a fact.  A run can sit
    well inside its cap and still be unable to pay for the next episode."""
    c = provider.Credits(total_credits=20.0, total_usage=2.00541421)
    assert c.remaining == 17.994586
    # 20 episodes at c01's measured $1.22 would need ~$24.40 -- more than the
    # balance -- so the balance, not the $50 cap, is what actually stops the run.
    assert c.remaining < 20 * 1.2228


def test_credits_unreadable_fields_do_not_fake_a_balance() -> None:
    assert provider.Credits().remaining is None
    assert provider.Credits(total_credits=20.0).remaining is None
    assert provider.Credits(total_usage=1.0).remaining is None


def test_credits_returns_empty_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert provider.credits("").remaining is None
