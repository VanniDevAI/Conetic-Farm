"""The container-teardown race, reproduced the way the harness causes it.

`mini_swe_agent_v2` calls ``env.cleanup()`` the moment an agent finishes
(``adapter.py:278``), and ``cleanup()`` runs ``docker stop <cid>`` in the
background (``environments/docker.py:164-168``).  The container was started
with ``--rm``, so *stop* means *remove*.  Whichever agent finishes first has
its working tree destroyed while the other agent is still running, and by the
time the harness returns there is nothing left to read.

In `c02` this cost one agent's patch in 11 of 16 measured episodes.

This test tears a container down exactly as the harness does -- ``docker
stop`` resolved through the PATH and environment the harness is given -- and
asserts the agent's uncommitted work was captured *before* the container went
away.  Before the fix the environment carries no interception, real ``docker``
answers, and the work is gone: the test fails.  After the fix the same call
captures the work first: the test passes.  The test does not change between
the two; only ``farm.env.child_env`` does.

Skipped when docker or the sandbox base image is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from farm import env as farm_env

IMAGE = "conetic-farm/node22-base:local"
WORK_TREE = "/workspace/repo"


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE],
                          capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ready(), reason="docker daemon or sandbox base image unavailable"
)


def _exec(cid: str, script: str) -> str:
    return subprocess.run(["docker", "exec", cid, "/bin/sh", "-lc", script],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def agent_container():
    """A container shaped like an agent's: started with --rm, a git repo at
    the harness's work tree, identified by `git config user.name` the way
    GitConnector.setup() identifies it (`connectors/git.py:109`)."""
    name = f"farm-race-{uuid.uuid4().hex[:8]}"
    cid = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--entrypoint", "/bin/bash",
         IMAGE, "-c", "sleep 600"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    try:
        _exec(cid, f"""
            mkdir -p {WORK_TREE} && cd {WORK_TREE} && git init -q
            git config user.email agent@cooperbench.local
            git config user.name agent1
            printf 'def a():\\n    return 1\\n' > core.py
            git add -A && git commit -qm base
        """)
        base_sha = _exec(cid, f"git -C {WORK_TREE} rev-parse HEAD").strip()
        # The agent's work: uncommitted, unpushed -- exactly the LimitsExceeded case.
        _exec(cid, f"printf '\\ndef b():\\n    return 2\\n' >> {WORK_TREE}/core.py")
        yield cid, base_sha
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


def _gone(cid: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(["docker", "inspect", cid], capture_output=True)
        if r.returncode != 0:
            return True
        time.sleep(0.25)
    return False


def test_work_survives_the_harness_tearing_the_container_down(agent_container,
                                                              tmp_path: Path) -> None:
    cid, base_sha = agent_container
    extract_dir = tmp_path / "extracted"

    # The environment the harness runs under.  Before the fix this is a plain
    # copy of ours plus .env; after it, child_env() sees FARM_EXTRACT_DIR and
    # puts an intercepting `docker` first on PATH.
    env = farm_env.child_env({
        "FARM_EXTRACT_DIR": str(extract_dir),
        "FARM_BASE_SHA": base_sha,
        "FARM_WORK_TREE": WORK_TREE,
    })

    # What env.cleanup() does, minus the trailing `&`: stop the container via
    # whatever `docker` the PATH resolves.  --rm turns that into removal.
    subprocess.run(f"timeout 60 docker stop {cid} || docker rm -f {cid}",
                   shell=True, env=env, capture_output=True, timeout=120)

    # The harness's teardown must still have happened: the shim may read the
    # container first, but it must never keep it alive.
    assert _gone(cid), "container should have been stopped and removed"

    # ...and the agent's uncommitted work must have been captured before that.
    patch = extract_dir / "agent1.patch"
    assert patch.exists(), (
        f"nothing extracted under {extract_dir}: the container was torn down "
        f"before anyone read its working tree")
    text = patch.read_text()
    assert "def b():" in text and "+    return 2" in text, text
    # And the fallback record -- the checkpoint bundle -- is either exported or
    # honestly absent; what it must not be is silently skipped.
    assert (extract_dir / "agent1.done").exists(), "no completion marker written"
