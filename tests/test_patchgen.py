"""Pin patch extraction: an agent that wrote code must never be recorded as one
that wrote nothing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from farm import patchgen


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


def _snapshot_repo(root: Path) -> Path:
    """A stand-in for the snapshotter's shadow repo: one commit per write."""
    repo = root / "shadow"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    src = repo / "src"
    src.mkdir()

    (src / "core.py").write_text("def a():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "baseline")

    (src / "core.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    (src / "sedAbCdEf").write_text("garbage from sed -i\n")   # editing artifact
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "write 1")

    (src / "new_module.py").write_text("VALUE = 3\n")          # untracked-new work
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "write 2")
    return repo


def _bundle(repo: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "bundle", "create", str(dest), "--all")
    return dest


def test_normalize_matches_the_harness_contract() -> None:
    # One trailing newline, leading blanks trimmed...
    assert patchgen.normalize_patch("\n\ndiff --git a b\n\n") == "diff --git a b\n"
    assert patchgen.normalize_patch("") == ""
    assert patchgen.normalize_patch("   \n ") == ""
    # ...but a blank *context* line (" \n") inside a hunk must survive, because
    # strip() would desynchronise the hunk header and git apply would reject it.
    body = "@@ -1 +1 @@\n-a\n+b\n \n"
    assert patchgen.normalize_patch(body).endswith("+b\n \n")


def test_bundle_extraction_recovers_the_real_edits(tmp_path: Path) -> None:
    repo = _snapshot_repo(tmp_path)
    b = _bundle(repo, tmp_path / "ck" / "checkpoints.bundle")

    res = patchgen.patch_from_bundle(b, agent_id="agent1")
    assert not res.is_empty
    assert res.agent_id == "agent1"
    assert res.source == "checkpoint_bundle"
    # The added function and the new module are both present...
    assert "def b():" in res.text
    assert "new_module.py" in res.text
    # ...and the sed leftover is not: it is an artifact of the editing tool.
    assert "sedAbCdEf" not in res.text
    assert res.files_changed == 2


def test_bundle_with_only_a_baseline_yields_nothing_and_says_why(tmp_path: Path) -> None:
    repo = tmp_path / "shadow"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "baseline")
    b = _bundle(repo, tmp_path / "ck" / "checkpoints.bundle")

    res = patchgen.patch_from_bundle(b)
    assert res.is_empty
    assert "1 checkpoint" in res.note


def test_missing_bundle_is_reported_not_raised(tmp_path: Path) -> None:
    res = patchgen.patch_from_bundle(tmp_path / "nope.bundle")
    assert res.is_empty and "no bundle" in res.note


def test_wrote_but_submitted_nothing_sees_writes(tmp_path: Path) -> None:
    """The c01 signature: the snapshotter recorded source writes, so an empty
    submitted patch is a disagreement, not evidence the agent idled."""
    att = tmp_path / "attempt-001"
    d = att / "checkpoints_raw" / "abc123456789"
    d.mkdir(parents=True)
    rows = [
        {"seq": 1, "trigger": "baseline", "paths": [], "files_changed": 145},
        {"seq": 2, "trigger": "write", "paths": ["src/click/core.py"], "files_changed": 1},
    ]
    d.joinpath("index.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert patchgen.wrote_but_submitted_nothing(att) == ["abc123456789"]


def test_baseline_only_is_not_counted_as_a_write(tmp_path: Path) -> None:
    att = tmp_path / "attempt-001"
    d = att / "checkpoints_raw" / "def000000000"
    d.mkdir(parents=True)
    d.joinpath("index.jsonl").write_text(
        json.dumps({"seq": 1, "trigger": "baseline", "paths": [], "files_changed": 145}) + "\n")
    assert patchgen.wrote_but_submitted_nothing(att) == []


def test_checkpoint_bundles_indexes_only_real_bundles(tmp_path: Path) -> None:
    att = tmp_path / "attempt-001"
    good = att / "checkpoints_raw" / "aaa111222333"
    good.mkdir(parents=True)
    good.joinpath("checkpoints.bundle").write_bytes(b"x")
    (att / "checkpoints_raw" / "bbb444555666").mkdir(parents=True)   # no bundle
    got = patchgen.checkpoint_bundles(att)
    assert list(got) == ["aaa111222333"]
