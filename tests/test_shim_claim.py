"""Only one shim may capture a container, and it must say so immediately.

Two findings from the adversarial review, both about the window between
"cleanup started" and "capture finished":

* ``DockerEnvironment`` calls ``cleanup()`` explicitly (``adapter.py:278``) and
  again from ``__del__`` (``docker.py:170``), so two shims can be capturing the
  same container within milliseconds.  Both run ``git add -A`` in the same
  working tree; the loser's ``git diff --cached`` reads a half-staged index and
  writes a patch missing the agent's untracked files -- over the winner's.
* Nothing existed until after ``docker inspect`` returned, so ``run_agents``
  could see no markers, conclude the shim never ran, and start its own live
  extraction against a container that was mid-``docker stop``.  Its ``git add``
  fails, it writes an empty patch over the shim's good one, and the episode
  records ``no_patch``.

Both are fixed by one thing: an ``O_EXCL`` claim taken *before any docker call*,
which is exactly the marker ``run_agents`` waits on.  A second shim that cannot
take the claim captures nothing and goes straight to the real docker -- it must
never block the teardown, and never write a patch.
"""

from __future__ import annotations

import os
from pathlib import Path

from farm import teardown


def test_claim_is_exclusive(tmp_path: Path) -> None:
    assert teardown.claim(tmp_path, "abc123456789") is True
    assert teardown.claim(tmp_path, "abc123456789") is False, (
        "a second cleanup for the same container must not capture it too")
    assert (tmp_path / "abc123456789.inprogress").exists()


def test_claim_is_per_container(tmp_path: Path) -> None:
    assert teardown.claim(tmp_path, "aaaaaaaaaaaa") is True
    assert teardown.claim(tmp_path, "bbbbbbbbbbbb") is True


def test_a_completed_capture_is_not_reclaimed(tmp_path: Path) -> None:
    """`docker stop` then `docker rm -f` for the same container: the second must
    not redo a capture that already succeeded."""
    (tmp_path / "abc123456789.done").write_text("agent1")
    assert teardown.claim(tmp_path, "abc123456789") is False


def test_a_timed_out_capture_is_not_retried_by_the_rm_path(tmp_path: Path) -> None:
    """cleanup() is `stop || rm -f`.  If the stop's capture already burned the
    budget, the rm must pass straight through rather than spend it again."""
    (tmp_path / "abc123456789.timeout").write_text("exceeded\n")
    assert teardown.claim(tmp_path, "abc123456789") is False


def test_claim_is_created_before_any_docker_call(monkeypatch, tmp_path: Path) -> None:
    """The ordering that matters: run_agents must be able to see the claim even
    if the shim is still waiting on `docker inspect`."""
    seen: list[bool] = []

    def fake_inspect(ref: str) -> str | None:
        seen.append((tmp_path / f"{ref}.inprogress").exists())
        return None                                  # not running -> no capture

    monkeypatch.setattr(teardown, "_resolve_running", fake_inspect)
    monkeypatch.setenv("FARM_EXTRACT_DIR", str(tmp_path))
    teardown._maybe_capture(["stop", "abc123456789"])
    assert seen == [True], "the claim must exist before `docker inspect` is called"


def test_releasing_an_unclaimed_container_is_harmless(tmp_path: Path) -> None:
    teardown.release(tmp_path, "abc123456789")       # must not raise


def test_release_clears_the_claim_so_a_later_pass_can_retry(tmp_path: Path) -> None:
    assert teardown.claim(tmp_path, "abc123456789") is True
    teardown.release(tmp_path, "abc123456789")
    assert not (tmp_path / "abc123456789.inprogress").exists()
    assert teardown.claim(tmp_path, "abc123456789") is True


def test_the_recursion_guard_never_reaches_the_harness(monkeypatch, tmp_path: Path) -> None:
    """FARM_SHIM_ACTIVE stops the shim recursing into itself during a capture.
    Inherited by the harness, it silently disables every capture instead --
    no error, no marker, just c02's data loss again.

    Found by an ordering interaction in this suite: a test that ran
    _maybe_capture in-process left the guard in os.environ, and the container
    race test then failed because child_env copied it into the harness.  The
    same thing happens in production if a campaign is launched from a shell
    that has the variable set.  child_env must clear it: the harness is by
    definition not inside a capture.
    """
    from farm import env as farm_env

    monkeypatch.setenv("FARM_SHIM_ACTIVE", "1")
    monkeypatch.setenv("FARM_EXTRACT_DIR", str(tmp_path))
    env = farm_env.child_env({"FARM_EXTRACT_DIR": str(tmp_path)})
    assert "FARM_SHIM_ACTIVE" not in env, (
        "the guard was inherited: the shim will skip every capture and the "
        "campaign will silently lose one agent per episode again")
