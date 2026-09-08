"""The marker handshake between the teardown shim and run_agents.

The shim runs inside the harness's backgrounded ``docker stop``; run_agents
reads its markers after the harness returns.  The contract that matters:

* a capture that *completed* leaves ``<cid12>.done`` naming the agent and
  ``<agent>.json`` carrying the patch metadata -- run_agents uses it and
  skips live extraction, which would race a second ``git add`` in the tree;
* a capture that *did not complete* -- the shim timed out, or was killed by
  the harness's ``timeout 60`` -- must NOT look like a completed one.  If it
  does, run_agents skips live extraction on a container that may still be
  alive and readable, and the agent's work is lost to a marker file.  That
  is the exact outcome the shim exists to prevent.

Pinned here: only a ``.done`` backed by a ``.json`` that actually carries a
patch counts as captured; anything else returns None so the live path runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from farm.episode import _await_shim_capture


def test_completed_capture_is_returned(tmp_path: Path) -> None:
    (tmp_path / "abc123456789.done").write_text("agent1")
    (tmp_path / "agent1.json").write_text(json.dumps({
        "agent_id": "agent1", "patch": {"bytes": 1234, "files_changed": 3}}))
    meta = _await_shim_capture(tmp_path, "abc123456789", timeout_s=1)
    assert meta is not None and meta["patch"]["bytes"] == 1234


def test_a_bare_done_marker_from_a_timed_out_capture_is_not_a_capture(tmp_path: Path) -> None:
    """The timeout path writes `<cid12>.done` with the cid as its contents and
    no `.json`.  That must read as 'not captured', not as 'captured nothing'."""
    (tmp_path / "abc123456789.done").write_text("abc123456789")
    (tmp_path / "abc123456789.timeout").write_text("capture exceeded 40s\n")
    assert _await_shim_capture(tmp_path, "abc123456789", timeout_s=1) is None


def test_a_done_marker_whose_json_has_no_patch_is_not_a_capture(tmp_path: Path) -> None:
    (tmp_path / "abc123456789.done").write_text("agent1")
    (tmp_path / "agent1.json").write_text(json.dumps({"agent_id": "agent1"}))
    assert _await_shim_capture(tmp_path, "abc123456789", timeout_s=1) is None


def test_a_capture_that_recorded_an_error_is_returned_so_the_error_is_logged(tmp_path: Path) -> None:
    """An explicit error is information; it is surfaced, and the caller still
    falls back to live extraction because there is no patch."""
    (tmp_path / "abc123456789.done").write_text("agent1")
    (tmp_path / "agent1.json").write_text(json.dumps({
        "agent_id": "agent1", "error": "RuntimeError: boom"}))
    meta = _await_shim_capture(tmp_path, "abc123456789", timeout_s=1)
    assert meta is not None and meta["error"].startswith("RuntimeError")
    assert "patch" not in meta


def test_no_markers_at_all_means_the_shim_never_ran(tmp_path: Path) -> None:
    assert _await_shim_capture(tmp_path, "abc123456789", timeout_s=1) is None


def test_in_progress_without_done_waits_then_gives_up(tmp_path: Path) -> None:
    (tmp_path / "abc123456789.inprogress").write_text("")
    assert _await_shim_capture(tmp_path, "abc123456789", timeout_s=1) is None
