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
import time
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


def test_a_capture_whose_diff_failed_is_not_reported_as_success(tmp_path: Path) -> None:
    """The shape the reviewer measured on a container killed mid-capture:

        "patch": {"bytes": 0, "files_changed": 0, "empty": true,
                  "note": "diff failed: ... container is not running",
                  "warnings": ["git add failed: ", "base ... not found; using HEAD"]}

    with no "error" key, because patch_from_container returns *normally* when
    the diff fails -- it records the failure in `note` rather than raising.  A
    `patch` key was therefore present, the handshake reported a successful
    capture, and run_agents skipped live extraction on a container that in
    other orderings is still readable.  An empty patch with a recorded failure
    is a failure, not a capture.
    """
    (tmp_path / "abc123456789.done").write_text("agent1")
    (tmp_path / "agent1.json").write_text(json.dumps({
        "agent_id": "agent1",
        "patch": {"bytes": 0, "files_changed": 0, "empty": True,
                  "note": "diff failed: container is not running",
                  "warnings": ["git add failed: "]},
    }))
    meta = _await_shim_capture(tmp_path, "abc123456789", timeout_s=1)
    # Not None: the reason has to reach the episode log.  But no usable patch,
    # so run_agents falls through to live extraction instead of recording an
    # empty patch as this agent's work.
    assert meta is not None
    assert not meta.get("patch"), meta
    assert "diff failed" in meta["error"]


def test_an_empty_patch_with_no_recorded_failure_is_still_a_capture(tmp_path: Path) -> None:
    """An agent that genuinely changed nothing is a real, informative result --
    it must not be re-extracted and must not be mistaken for a failure."""
    (tmp_path / "abc123456789.done").write_text("agent1")
    (tmp_path / "agent1.json").write_text(json.dumps({
        "agent_id": "agent1",
        "patch": {"bytes": 0, "files_changed": 0, "empty": True, "note": "", "warnings": []},
    }))
    meta = _await_shim_capture(tmp_path, "abc123456789", timeout_s=1)
    assert meta is not None and meta["patch"]["empty"] is True


def test_a_grace_window_lets_a_just_started_shim_claim_first(tmp_path: Path) -> None:
    """cleanup() is backgrounded, so the harness can return before the shim has
    even started python.  Without a grace window run_agents sees no markers,
    concludes the shim never ran, and races a live extraction against it."""
    import threading

    def late_claim() -> None:
        time.sleep(0.3)
        (tmp_path / "abc123456789.inprogress").write_text("")
        time.sleep(0.2)
        (tmp_path / "abc123456789.done").write_text("agent1")
        (tmp_path / "agent1.json").write_text(json.dumps({
            "agent_id": "agent1", "patch": {"bytes": 42, "files_changed": 1}}))
        try:
            (tmp_path / "abc123456789.inprogress").unlink()
        except OSError:
            pass

    t = threading.Thread(target=late_claim)
    t.start()
    meta = _await_shim_capture(tmp_path, "abc123456789", timeout_s=10, grace_s=3)
    t.join()
    assert meta is not None and meta["patch"]["bytes"] == 42
