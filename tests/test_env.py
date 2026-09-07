"""Pin the .env behaviour, because getting it wrong fails silently."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from farm import env as farm_env

COOPERBENCH = Path("/home/user/work/CooperBench")


def test_parse_handles_quotes_comments_and_export(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# a comment\n"
        "\n"
        "PLAIN=value\n"
        'QUOTED="quoted value"\n'
        "SINGLE='single'\n"
        "export EXPORTED=exp\n"
        "EMPTY=\n"
        "NOT_A_PAIR\n"
    )
    got = farm_env.parse_env_file(p)
    assert got == {"PLAIN": "value", "QUOTED": "quoted value",
                   "SINGLE": "single", "EXPORTED": "exp", "EMPTY": ""}


def test_load_returns_names_not_values(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / ".env"
    p.write_text("FARM_TEST_SECRET=sk-or-v1-abcdefghijklmnopqrstuvwxyz\n")
    monkeypatch.delenv("FARM_TEST_SECRET", raising=False)
    applied = farm_env.load(p)
    assert applied == ["FARM_TEST_SECRET"]
    assert "sk-or" not in " ".join(applied)
    assert os.environ["FARM_TEST_SECRET"].startswith("sk-or-v1-")


def test_load_does_not_clobber_an_existing_value(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / ".env"
    p.write_text("FARM_TEST_X=from-file\n")
    monkeypatch.setenv("FARM_TEST_X", "from-environment")
    farm_env.load(p)
    assert os.environ["FARM_TEST_X"] == "from-environment"
    farm_env.load(p, override=True)
    assert os.environ["FARM_TEST_X"] == "from-file"


def test_child_env_carries_our_values(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("FARM_TEST_CHILD=hello\n")
    assert farm_env.child_env(path=p)["FARM_TEST_CHILD"] == "hello"


def test_redact_strips_credential_shapes() -> None:
    s = "key=sk-or-v1-0123456789abcdefghijklmnop and sk-ant-0123456789abcdefghij done"
    out = farm_env.redact(s)
    assert "sk-or-v1-" not in out and "sk-ant-" not in out
    assert out.count("<redacted>") == 2


def test_require_names_the_variable_never_the_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FARM_TEST_MISSING", raising=False)
    p = tmp_path / ".env"
    p.write_text("")
    with pytest.raises(farm_env.EnvError) as exc:
        farm_env.require("FARM_TEST_MISSING", path=p)
    assert "FARM_TEST_MISSING" in str(exc.value)


@pytest.mark.skipif(not (COOPERBENCH / "src" / "cooperbench" / "cli.py").exists(),
                    reason="CooperBench checkout unavailable")
def test_cooperbench_ignores_a_dotenv_in_this_repo(tmp_path: Path) -> None:
    """Regression guard for the trap this module exists to close.

    CooperBench's `load_dotenv()` walks up from *its own* cli.py, so a .env in
    this repository is never read.  If upstream ever changes to honour cwd, this
    test fails and the docs need updating -- better than finding out from an
    auth error mid-campaign.
    """
    py = COOPERBENCH / ".venv" / "bin" / "python"
    if not py.exists():
        pytest.skip("CooperBench venv unavailable")

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, cooperbench.cli\n"
        "print(os.environ.get('FARM_DOTENV_PROBE'))\n"
    )
    local_env = tmp_path / ".env"
    local_env.write_text("FARM_DOTENV_PROBE=should-not-be-seen\n")

    clean = {k: v for k, v in os.environ.items() if k != "FARM_DOTENV_PROBE"}
    out = subprocess.run([str(py), str(probe)], cwd=tmp_path, env=clean,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == "None", (
        f"cooperbench read a .env from cwd (got {out!r}); farm/env.py's premise "
        "and docs/ENVIRONMENT.md need revisiting"
    )

    # And the fix: exporting into the child environment does reach it.
    out2 = subprocess.run(
        [str(py), str(probe)], cwd=tmp_path,
        env=farm_env.child_env({"FARM_DOTENV_PROBE": "injected"}, path=tmp_path / "nonexistent"),
        capture_output=True, text=True, check=True).stdout.strip()
    assert out2 == "injected"
