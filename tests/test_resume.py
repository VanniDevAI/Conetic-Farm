"""A completed episode must never be paid for twice."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from farm.run import Campaign


class _C(Campaign):
    """Just the resume predicate, without building a whole campaign."""
    def __init__(self, data_root: Path) -> None:      # noqa: D107
        self.data_root = data_root


def _write(root: Path, ep: str, statuses: list[str]) -> None:
    d = root / "episodes" / ep
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(
        {"episode_id": ep, "attempts": [{"status": s} for s in statuses]}))


def test_completed_episode_is_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "ep1", ["completed"])
    assert _C(tmp_path).already_completed(SimpleNamespace(episode_id="ep1"))


def test_errored_episode_is_retried(tmp_path: Path) -> None:
    """An errored episode cost nothing -- it died before any model call -- and
    its cause (a blocked host, a full disk) may since have been fixed."""
    _write(tmp_path, "ep2", ["error"])
    assert not _C(tmp_path).already_completed(SimpleNamespace(episode_id="ep2"))


def test_a_later_completed_attempt_counts(tmp_path: Path) -> None:
    _write(tmp_path, "ep3", ["error", "completed"])
    assert _C(tmp_path).already_completed(SimpleNamespace(episode_id="ep3"))


def test_unknown_episode_is_not_skipped(tmp_path: Path) -> None:
    assert not _C(tmp_path).already_completed(SimpleNamespace(episode_id="nope"))


def test_unreadable_manifest_is_not_skipped(tmp_path: Path) -> None:
    """When in doubt, run it: skipping wrongly loses an episode, running
    wrongly only costs one."""
    d = tmp_path / "episodes" / "ep4"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text("{ not json")
    assert not _C(tmp_path).already_completed(SimpleNamespace(episode_id="ep4"))
