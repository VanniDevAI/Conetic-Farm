"""An explicit flag must beat the environment.

This inverted once, and it was not a cosmetic bug: `--data-root` was ignored
whenever .env set FARM_DATA_ROOT, so a campaign told to write to a fresh
directory silently wrote into the previous campaign's, mixing two runs' data.
"""

from __future__ import annotations

from farm.run import _setting


def test_explicit_flag_beats_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("FARM_DATA_ROOT", "/home/user/farm-data")
    assert _setting("/home/user/farm-data-c02", "FARM_DATA_ROOT",
                    "/default") == "/home/user/farm-data-c02"


def test_environment_is_used_when_no_flag_given(monkeypatch) -> None:
    monkeypatch.setenv("FARM_DATA_ROOT", "/from/env")
    assert _setting(None, "FARM_DATA_ROOT", "/default") == "/from/env"


def test_default_is_used_when_neither_is_set(monkeypatch) -> None:
    monkeypatch.delenv("FARM_DATA_ROOT", raising=False)
    assert _setting(None, "FARM_DATA_ROOT", "/default") == "/default"


def test_a_falsy_but_explicit_flag_still_wins(monkeypatch) -> None:
    """`--budget 0` is a real instruction, not an absent one."""
    monkeypatch.setenv("FARM_BUDGET_USD", "50")
    assert _setting(0.0, "FARM_BUDGET_USD", 50.0) == 0.0
