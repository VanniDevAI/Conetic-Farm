"""An episode that times out must not leave its agent containers running.

`run_agents` bounds the harness with `subprocess.run(..., timeout=...)`, which
kills the *harness* process.  Nothing else: `DockerEnvironment.cleanup()`
(adapter.py:278) and `__del__` (docker.py:170) never run, so the two agent
containers keep executing their entrypoint -- `sleep 2h`, the adapter's default
`container_timeout` -- and `--rm` will not fire for another hour.

The leak does not stay a leak.  `farm/run.py`'s disk guard reclaims task images
between episodes with `docker rmi -f`, and that fails outright for any image a
*running* container references:

    Error response from daemon: conflict: unable to delete <id>
    (cannot be forced) - image is being used by running container <cid>

The recheck then still sees insufficient space and the campaign aborts, blaming
disk for what is actually a container leak -- one episode's timeout ending a
campaign several episodes later, with a misleading reason.

Pinned here: on the timeout path only.  Everywhere else the harness's own
cleanup runs, and removing a container out from under a capture still in flight
is precisely what the teardown shim exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

from farm import episode as ep


def test_reap_removes_each_container_by_force(monkeypatch) -> None:
    calls: list[list[str]] = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ep.subprocess, "run",
                        lambda argv, **kw: (calls.append(list(argv)), R())[1])

    out = ep._reap(["aaaaaaaaaaaa1111", "bbbbbbbbbbbb2222"])

    assert len(calls) == 2, calls
    for argv, cid in zip(calls, ("aaaaaaaaaaaa1111", "bbbbbbbbbbbb2222")):
        assert argv[1:] == ["rm", "-f", cid], argv
    assert out == {"aaaaaaaaaaaa": "removed", "bbbbbbbbbbbb": "removed"}


def test_reap_never_raises_and_records_what_failed(monkeypatch) -> None:
    """Reaping is hygiene.  A docker that is gone, wedged, or refusing must not
    turn a completed episode into a crashed one."""
    def boom(argv, **kw):
        raise OSError("docker vanished")

    monkeypatch.setattr(ep.subprocess, "run", boom)
    out = ep._reap(["aaaaaaaaaaaa1111"])
    assert "OSError" in out["aaaaaaaaaaaa"], out


def test_reap_goes_to_the_real_docker_not_the_shim(monkeypatch, tmp_path: Path) -> None:
    """Through the shim this would take a claim, run a capture we have already
    done, and burn the budget again on a container we are deleting."""
    calls: list[list[str]] = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setenv("FARM_REAL_DOCKER", str(tmp_path / "real-docker"))
    monkeypatch.setattr(ep.subprocess, "run",
                        lambda argv, **kw: (calls.append(list(argv)), R())[1])

    ep._reap(["aaaaaaaaaaaa1111"])

    assert calls[0][0] == str(tmp_path / "real-docker"), calls[0]


def test_reap_of_nothing_does_nothing(monkeypatch) -> None:
    monkeypatch.setattr(ep.subprocess, "run",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("called")))
    assert ep._reap([]) == {}
