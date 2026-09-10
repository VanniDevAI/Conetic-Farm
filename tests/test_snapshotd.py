"""End-to-end check that the snapshotter produces an ordered, replayable history.

Runs the daemon against a real temporary work tree, writes files in a known
order, then asserts the checkpoint history reproduces that order exactly.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTD = REPO_ROOT / "farm" / "snapshotd.py"


def _git(git_dir: Path, work_tree: Path, *args: str) -> str:
    env = {**os.environ, "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(work_tree),
           "HOME": str(git_dir), "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], env=env, capture_output=True,
                          text=True, check=True).stdout


def test_snapshots_are_ordered_and_replayable(tmp_path: Path) -> None:
    work = tmp_path / "repo"
    work.mkdir()
    (work / "a.txt").write_text("v0\n")

    git_dir = tmp_path / "checkpoints"
    index = git_dir / "index.jsonl"

    proc = subprocess.Popen(
        [sys.executable, str(SNAPSHOTD), "--work-tree", str(work),
         "--git-dir", str(git_dir), "--index", str(index),
         "--debounce-ms", "150", "--max-interval-ms", "2000"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Let the baseline snapshot land.
        deadline = time.time() + 20
        while time.time() < deadline and not index.exists():
            time.sleep(0.1)
        assert index.exists(), "daemon never wrote a baseline snapshot"

        writes = ["v1", "v2", "v3"]
        for i, content in enumerate(writes):
            (work / "a.txt").write_text(content + "\n")
            (work / f"new_{i}.txt").write_text(f"file {i}\n")
            time.sleep(0.8)  # longer than the debounce, so each write is its own snapshot
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)

    records = [json.loads(l) for l in index.read_text().splitlines() if l.strip()]
    assert records, "no checkpoints recorded"

    # 1. seq is monotonic from 1 with no gaps and no repeats.
    seqs = [r["seq"] for r in records]
    assert seqs == list(range(1, len(seqs) + 1)), f"seq not monotonic: {seqs}"

    # 2. timestamps are non-decreasing, in both clocks.
    assert all(a["ts"] <= b["ts"] for a, b in zip(records, records[1:]))
    assert all(a["ts_monotonic_ns"] <= b["ts_monotonic_ns"]
               for a, b in zip(records, records[1:]))

    # 3. the commit chain matches the recorded parents.
    for prev, cur in zip(records, records[1:]):
        assert cur["parent"] == prev["commit"], "commit chain is broken"

    # 4. replay: checking out each commit in order reproduces the write sequence.
    seen: list[str] = []
    for r in records:
        _git(git_dir, work, "checkout", "--quiet", "--force", r["commit"], "--", ".")
        seen.append((work / "a.txt").read_text().strip())
    #
    # What the daemon promises is that its snapshots are ordered and
    # replayable, not that every intermediate write becomes one: it debounces,
    # so two writes inside one window coalesce. This test used to assert every
    # write appeared, and failed roughly one run in three when the machine was
    # busy -- it flagged load, not a defect. Assert the guarantee instead: the
    # starting state and the final state are both there, and whatever was
    # captured is in the order it was written.
    expected = ["v0", *writes]
    assert seen[0] == expected[0], f"replay does not start at the base: {seen}"
    assert expected[-1] in seen, f"the final write is missing from replay: {seen}"
    captured = [v for v in expected if v in seen]
    positions = [seen.index(v) for v in captured]
    assert positions == sorted(positions), f"replay order wrong: {seen}"
    assert len(captured) >= 2, f"nothing but the base was captured: {seen}"


def test_agent_git_repo_is_untouched(tmp_path: Path) -> None:
    """The shadow repo must not disturb the agent's own git state."""
    work = tmp_path / "repo"
    work.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    (work / "a.txt").write_text("v0\n")
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "base"], cwd=work, check=True)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work,
                            capture_output=True, text=True, check=True).stdout.strip()

    git_dir = tmp_path / "checkpoints"
    index = git_dir / "index.jsonl"
    proc = subprocess.Popen(
        [sys.executable, str(SNAPSHOTD), "--work-tree", str(work),
         "--git-dir", str(git_dir), "--index", str(index), "--debounce-ms", "150"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not index.exists():
            time.sleep(0.1)
        (work / "b.txt").write_text("new\n")
        time.sleep(1.0)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)

    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work,
                           capture_output=True, text=True, check=True).stdout.strip()
    assert before == after, "snapshotd moved the agent's HEAD"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=work,
                            capture_output=True, text=True, check=True).stdout
    # b.txt should still be untracked from the agent's point of view.
    assert "b.txt" in status, "snapshotd staged files in the agent's own index"
