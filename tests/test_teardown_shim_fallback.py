"""The shim must never be the reason a harness docker call fails.

``farm/shim/docker`` is what the harness resolves as ``docker`` for the whole
episode: ``docker run -d`` at start, one ``docker exec`` per agent step, and
the ``docker stop`` this shim exists to intercept.  If the python behind it
cannot start -- a broken import, a missing interpreter, a bad ``execv``
target -- and the shell wrapper simply propagates that, then *every* docker
call fails and the episode dies before the first agent step, for a reason
that has nothing to do with the agent.

Contract pinned here:

* python exits with the sentinel ``97`` only when it failed *before* reaching
  ``execv`` (so the real command has NOT run).  The wrapper must then run the
  real docker itself, with the original arguments, exactly once.
* any other exit code came from the real docker after ``execv`` and must be
  propagated unchanged -- and the real docker must NOT be run a second time,
  or a ``docker stop`` becomes two stops and ``docker run`` two containers.

No real docker is involved: FARM_REAL_DOCKER points at a stub that records
its argv, and ``python3`` on PATH is a stub that exits with a chosen code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "farm" / "shim" / "docker"


def _stub_python(dir_: Path, exit_code: int) -> Path:
    """A `python3` that ignores its arguments and exits with `exit_code`."""
    p = dir_ / "python3"
    p.write_text(f"#!/bin/sh\nexit {exit_code}\n")
    p.chmod(0o755)
    return p


def _stub_docker(dir_: Path, log: Path, exit_code: int = 0) -> Path:
    """A `docker` that appends its argv to `log` and exits with `exit_code`."""
    p = dir_ / "real-docker"
    p.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexit {exit_code}\n')
    p.chmod(0o755)
    return p


def _run_shim(stub_dir: Path, real: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FARM_REAL_DOCKER"] = str(real)
    env["FARM_EXTRACT_DIR"] = str(stub_dir / "extract")
    return subprocess.run([str(SHIM), *args], env=env, capture_output=True, text=True,
                          timeout=30)


def test_pre_execv_failure_falls_back_to_the_real_docker_once(tmp_path: Path) -> None:
    log = tmp_path / "calls.log"
    _stub_python(tmp_path, 97)                         # "failed before execv"
    real = _stub_docker(tmp_path, log, exit_code=0)

    r = _run_shim(tmp_path, real, "stop", "abc123")

    assert log.exists(), "the real docker was never run: the harness's stop was lost"
    calls = log.read_text().splitlines()
    assert calls == ["stop abc123"], calls
    assert r.returncode == 0, r.stderr


def test_real_docker_exit_code_propagates_without_a_second_run(tmp_path: Path) -> None:
    """Exit 5 is what the real docker returned after execv; running it again
    would turn one `docker stop` into two."""
    log = tmp_path / "calls.log"
    _stub_python(tmp_path, 5)                          # "docker itself exited 5"
    real = _stub_docker(tmp_path, log, exit_code=0)

    r = _run_shim(tmp_path, real, "exec", "abc123", "true")

    assert r.returncode == 5, (r.returncode, r.stderr)
    assert not log.exists(), (
        f"real docker was run again after python already ran it: {log.read_text()}")


def test_fallback_is_used_when_the_real_docker_reports_failure_too(tmp_path: Path) -> None:
    """The fallback's own exit code is the harness's answer, unchanged."""
    log = tmp_path / "calls.log"
    _stub_python(tmp_path, 97)
    real = _stub_docker(tmp_path, log, exit_code=1)

    r = _run_shim(tmp_path, real, "rm", "-f", "abc123")

    assert log.read_text().splitlines() == ["rm -f abc123"]
    assert r.returncode == 1
