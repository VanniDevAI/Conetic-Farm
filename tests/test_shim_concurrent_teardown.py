"""A losing shim must not destroy the container the winner is still reading.

The claim in ``test_shim_claim.py`` stops two shims *capturing* at once.  It
does not stop the loser from carrying on to ``execv`` the real ``docker
stop``, and that is what actually destroys the container -- while the winner
is halfway through ``git add -A``.

The harness makes this the normal case, not an edge one:
``DockerEnvironment.cleanup()`` runs twice per agent, once from
``adapter.py:278`` and again from ``__del__`` (``docker.py:170``), each
backgrounding ``(timeout 60 docker stop CID || docker rm -f CID)``.  Measured
by the reviewer on one container with a large working tree: with a single
cleanup the capture completed and produced a 19.8 MB patch; with the harness's
real two, the container was removed ~10s in and the patch came back empty.

So the loser must block until the holder writes ``.done`` (or gives up with
``.timeout``) before it passes the stop through.  Bounded, because a capture
that never finishes must not wedge the campaign either.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from farm import teardown


def test_loser_waits_for_the_holder_to_finish(tmp_path: Path) -> None:
    assert teardown.claim(tmp_path, "abc123456789") is True      # winner

    HOLD = 0.4

    def holder() -> None:
        time.sleep(HOLD)                       # the capture
        (tmp_path / "abc123456789.done").write_text("agent1")
        teardown.release(tmp_path, "abc123456789")

    t = threading.Thread(target=holder)
    t.start()
    t0 = time.monotonic()
    ok = teardown.wait_for_holder(tmp_path, "abc123456789", timeout_s=10)
    waited = time.monotonic() - t0
    t.join()

    assert ok is True
    assert waited >= HOLD * 0.9, (
        f"the loser returned after {waited:.2f}s, before the holder's {HOLD}s "
        f"capture finished: it would `docker stop` the container mid-capture")


def test_waiting_is_bounded_so_a_wedged_capture_cannot_wedge_the_campaign(tmp_path: Path) -> None:
    assert teardown.claim(tmp_path, "abc123456789") is True
    t0 = time.monotonic()
    ok = teardown.wait_for_holder(tmp_path, "abc123456789", timeout_s=0.5)
    assert ok is False
    assert time.monotonic() - t0 < 5, "the wait must be bounded"


def test_a_timeout_marker_releases_the_waiter(tmp_path: Path) -> None:
    """The holder gave up; the loser should proceed with the teardown rather
    than wait out its own budget too."""
    assert teardown.claim(tmp_path, "abc123456789") is True
    (tmp_path / "abc123456789.timeout").write_text("exceeded\n")
    assert teardown.wait_for_holder(tmp_path, "abc123456789", timeout_s=10) is True


def test_nothing_to_wait_for_returns_immediately(tmp_path: Path) -> None:
    t0 = time.monotonic()
    assert teardown.wait_for_holder(tmp_path, "abc123456789", timeout_s=10) is True
    assert time.monotonic() - t0 < 1


def test_maybe_capture_waits_when_it_loses_the_claim(monkeypatch, tmp_path: Path) -> None:
    """End to end: a second cleanup for a container someone else is capturing
    must block in _maybe_capture, not fall through to the real docker."""
    teardown.claim(tmp_path, "abc123456789")                      # someone else holds it
    monkeypatch.setenv("FARM_EXTRACT_DIR", str(tmp_path))
    monkeypatch.setattr(teardown, "HOLDER_WAIT_S", 0.5)
    called: list[str] = []
    monkeypatch.setattr(teardown, "_resolve_running", lambda ref: called.append(ref))

    t0 = time.monotonic()
    teardown._maybe_capture(["stop", "abc123456789"])
    waited = time.monotonic() - t0

    assert waited >= 0.4, "the second cleanup did not wait for the holder"
    assert called == [], "the loser must not start its own capture"
