"""The wrapper must know whether the real docker ran, without guessing from a code.

Found by adversarial review of the first shim, and the reason this file exists
rather than a wider sentinel: signalling "the real docker did not run" through
an *exit status* cannot work, because the exit status belongs to the real
docker.  `docker exec ... ` returns the command's status, so a harness step
whose command exits 97 was re-executed by the wrapper -- appends appended
twice, `git commit` committed twice, the model shown both runs' output
concatenated, and nothing anywhere saying so.

The replacement is a marker file, and its polarity is the whole design:

    absent  -> the real docker did NOT run; the wrapper must run it
    present -> execv succeeded, so this process IS the real docker

`teardown.py` writes it immediately before `execv` and removes it again only
if `execv` returns (which means it failed).  So every way python can fail --
unparsable module, ImportError, missing interpreter, bad binary, a crash
before it ever starts -- leaves the marker absent and the wrapper runs the
real command.  Nothing is inferred from a number.

No real docker is involved here: FARM_REAL_DOCKER points at a stub that logs
its argv, and the `python3` on PATH is a stub with a chosen exit code and
marker behaviour.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "farm" / "shim" / "docker"


def _fake_python(dir_: Path, *, exit_code: int, write_marker: bool) -> None:
    """A `python3` that optionally writes $FARM_SHIM_RAN, then exits."""
    body = '#!/bin/sh\n'
    if write_marker:
        body += '[ -n "$FARM_SHIM_RAN" ] && : > "$FARM_SHIM_RAN"\n'
    body += f'exit {exit_code}\n'
    p = dir_ / "python3"
    p.write_text(body)
    p.chmod(0o755)


def _fake_docker(dir_: Path, log: Path, exit_code: int = 0) -> Path:
    p = dir_ / "real-docker"
    p.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexit {exit_code}\n')
    p.chmod(0o755)
    return p


def _run(stub_dir: Path, real: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FARM_REAL_DOCKER"] = str(real)
    env["FARM_EXTRACT_DIR"] = str(stub_dir / "extract")
    return subprocess.run([str(SHIM), *args], env=env, capture_output=True,
                          text=True, timeout=30)


def test_a_real_exit_code_of_97_is_not_a_signal(tmp_path: Path) -> None:
    """The bug this file was written for.  97 is an ordinary status once the
    marker exists: propagate it, and do not run the command a second time."""
    log = tmp_path / "calls.log"
    _fake_python(tmp_path, exit_code=97, write_marker=True)   # execv happened
    real = _fake_docker(tmp_path, log)

    r = _run(tmp_path, real, "exec", "abc123", "bash", "-lc", "exit 97")

    assert r.returncode == 97, (r.returncode, r.stderr)
    assert not log.exists(), (
        f"the command was executed twice; side effects duplicated: {log.read_text()}")


def test_python_failing_before_exec_makes_the_wrapper_run_the_real_docker(tmp_path: Path) -> None:
    log = tmp_path / "calls.log"
    _fake_python(tmp_path, exit_code=1, write_marker=False)   # crashed before execv
    real = _fake_docker(tmp_path, log)

    r = _run(tmp_path, real, "stop", "abc123")

    assert log.read_text().splitlines() == ["stop abc123"]
    assert r.returncode == 0


def test_any_python_exit_code_without_the_marker_falls_back(tmp_path: Path) -> None:
    """A syntax error (rc 1), a missing module (rc 1), a signal (rc 143), a
    missing file (rc 2): none of them may take the harness's docker call down
    with them."""
    for rc in (1, 2, 127, 143):
        d = tmp_path / f"rc{rc}"
        d.mkdir()
        log = d / "calls.log"
        _fake_python(d, exit_code=rc, write_marker=False)
        real = _fake_docker(d, log)

        r = _run(d, real, "run", "-d", "--rm", "img", "sleep", "1")

        assert log.read_text().splitlines() == ["run -d --rm img sleep 1"], rc
        assert r.returncode == 0, rc


def test_a_missing_interpreter_still_runs_the_real_docker(tmp_path: Path) -> None:
    """No python3 on PATH at all: the wrapper must not be a hard dependency on
    the interpreter for every docker call an episode makes."""
    log = tmp_path / "calls.log"
    real = _fake_docker(tmp_path, log)
    env = dict(os.environ)
    env["PATH"] = str(tmp_path)                      # only real-docker lives here
    env["FARM_REAL_DOCKER"] = str(real)
    env["FARM_EXTRACT_DIR"] = str(tmp_path / "extract")

    r = subprocess.run([str(SHIM), "stop", "abc"], env=env, capture_output=True,
                       text=True, timeout=30)

    assert log.read_text().splitlines() == ["stop abc"]
    assert r.returncode == 0
