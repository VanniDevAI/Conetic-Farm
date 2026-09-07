"""End-to-end: attach the snapshotter to a real container, then replay its history.

Skipped when docker or the sandbox base image is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from farm.checkpoints import attach, detach_and_export

IMAGE = "conetic-farm/node22-base:local"


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


@pytest.fixture
def container():
    name = f"farm-test-{uuid.uuid4().hex[:8]}"
    cid = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--entrypoint", "/bin/bash",
         IMAGE, "-c", "sleep 600"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["docker", "exec", cid, "mkdir", "-p", "/workspace/repo"], check=True)
    try:
        yield cid
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


def _write(cid: str, path: str, content: str) -> None:
    # `-i` is required: without it docker exec does not attach stdin and `cat`
    # sees EOF immediately, silently creating an empty file.
    subprocess.run(
        ["docker", "exec", "-i", cid, "sh", "-c", f"cat > {path}"],
        input=content, text=True, check=True,
    )


def test_checkpoints_capture_and_replay_write_order(container, tmp_path: Path) -> None:
    cid = container
    _write(cid, "/workspace/repo/a.txt", "v0\n")

    att = attach(cid, "/workspace/repo", debounce_ms=150)

    for v in ("v1", "v2", "v3"):
        _write(cid, "/workspace/repo/a.txt", f"{v}\n")
        _write(cid, f"/workspace/repo/{v}.txt", f"file {v}\n")
        time.sleep(0.9)      # exceed the debounce so each write is its own snapshot

    out = tmp_path / "checkpoints"
    result = detach_and_export(att, out)

    assert result["checkpoints"] >= 4, result
    assert result["seq_monotonic"], "sequence numbers are not monotonic"
    assert (out / "index.jsonl").exists()
    assert (out / "checkpoints.bundle").exists()

    records = [json.loads(l) for l in (out / "index.jsonl").read_text().splitlines() if l.strip()]
    assert [r["seq"] for r in records] == list(range(1, len(records) + 1))
    assert all(a["ts"] <= b["ts"] for a, b in zip(records, records[1:]))

    # The bundle must be a standalone, replayable repository.
    work = tmp_path / "replay"
    subprocess.run(["git", "clone", "--quiet", str(out / "checkpoints.bundle"), str(work)],
                   check=True, capture_output=True)
    commits = subprocess.run(
        ["git", "log", "--reverse", "--format=%H"], cwd=work,
        capture_output=True, text=True, check=True).stdout.split()
    assert len(commits) == len(records)
    assert commits == [r["commit"] for r in records], "bundle order != index order"

    seen = []
    for c in commits:
        subprocess.run(["git", "checkout", "--quiet", "--force", c], cwd=work,
                       check=True, capture_output=True)
        f = work / "a.txt"
        seen.append(f.read_text().strip() if f.exists() else None)

    for expected in ("v0", "v1", "v2", "v3"):
        assert expected in seen, f"{expected!r} missing from replay: {seen}"
    positions = [seen.index(v) for v in ("v0", "v1", "v2", "v3")]
    assert positions == sorted(positions), f"replay order wrong: {seen}"


def test_attach_fails_loudly_on_a_dead_container(tmp_path: Path) -> None:
    """A silently dead snapshotter would cost a run's entire history."""
    from farm.checkpoints import AttachError
    with pytest.raises(AttachError):
        attach("definitely-not-a-container", "/workspace/repo")
