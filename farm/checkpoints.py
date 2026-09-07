"""Attach the working-tree snapshotter to a running task container.

CooperBench's ``DockerEnvironment`` starts a long-lived container
(``docker run -d ... sleep <timeout>``) and then runs every agent action through
``docker exec``.  That shape lets us capture intermediate source checkpoints
**without forking the harness**: copy the snapshotter in, start it detached, and
pull the resulting shadow git repo out when the agent is done.

Attachment is driven by ``docker events`` rather than by patching the harness,
so it works with any adapter that uses the docker backend and survives upstream
changes to the adapter internals.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
SNAPSHOTD = HERE / "snapshotd.py"

CONTAINER_SNAPSHOTD = "/opt/farm/snapshotd.py"
CONTAINER_GIT_DIR = "/workspace/.farm-checkpoints"
CONTAINER_INDEX = "/workspace/.farm-checkpoints/index.jsonl"


class AttachError(RuntimeError):
    pass


def _docker(*args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise AttachError(f"docker {' '.join(args[:3])} failed: {r.stderr.strip()[:400]}")
    return r


@dataclass
class Attachment:
    container_id: str
    work_tree: str
    git_dir: str = CONTAINER_GIT_DIR
    index: str = CONTAINER_INDEX


def attach(
    container_id: str,
    work_tree: str,
    *,
    debounce_ms: int = 250,
    max_interval_ms: int = 15000,
) -> Attachment:
    """Copy the snapshotter into a running container and start it detached."""
    if not SNAPSHOTD.exists():
        raise AttachError(f"snapshotter not found at {SNAPSHOTD}")

    _docker("exec", container_id, "mkdir", "-p", "/opt/farm")
    _docker("cp", str(SNAPSHOTD), f"{container_id}:{CONTAINER_SNAPSHOTD}")

    # `-d` detaches, so the daemon outlives this exec and runs alongside the agent.
    _docker(
        "exec", "-d", container_id,
        "python3", CONTAINER_SNAPSHOTD,
        "--work-tree", work_tree,
        "--git-dir", CONTAINER_GIT_DIR,
        "--index", CONTAINER_INDEX,
        "--debounce-ms", str(debounce_ms),
        "--max-interval-ms", str(max_interval_ms),
    )

    # Confirm it actually came up.  A silently dead snapshotter would leave us
    # with a final patch and no history, discovered only after the run.
    deadline = time.time() + 30
    while time.time() < deadline:
        r = _docker("exec", container_id, "test", "-f", CONTAINER_INDEX, check=False)
        if r.returncode == 0:
            return Attachment(container_id=container_id, work_tree=work_tree)
        time.sleep(0.5)
    raise AttachError(
        f"snapshotter did not produce {CONTAINER_INDEX} in {container_id[:12]} within 30s"
    )


def detach_and_export(att: Attachment, dest_dir: Path, *, timeout_s: int = 60) -> dict:
    """Stop the snapshotter and copy its history out of the container.

    Produces ``index.jsonl`` and ``checkpoints.bundle`` under ``dest_dir``.  The
    bundle is a self-contained git repository: cloning it and walking commits
    oldest-first replays the agent's writes in order.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # SIGTERM makes the daemon flush a final snapshot before exiting.
    _docker("exec", att.container_id, "pkill", "-TERM", "-f", "snapshotd.py", check=False)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = _docker("exec", att.container_id, "pgrep", "-f", "snapshotd.py", check=False)
        if r.returncode != 0:
            break
        time.sleep(0.5)
    else:
        _docker("exec", att.container_id, "pkill", "-KILL", "-f", "snapshotd.py", check=False)

    bundle_in_container = f"{att.git_dir}/checkpoints.bundle"
    r = _docker(
        "exec", att.container_id, "sh", "-c",
        f"GIT_DIR={att.git_dir} git bundle create {bundle_in_container} --all 2>&1",
        check=False, timeout=300,
    )
    result: dict = {"bundle_created": r.returncode == 0,
                    "bundle_stderr": r.stdout.strip()[-1000:] if r.returncode else ""}

    for remote, local in ((att.index, "index.jsonl"),
                          (bundle_in_container, "checkpoints.bundle")):
        cp = _docker("cp", f"{att.container_id}:{remote}", str(dest_dir / local), check=False)
        result[local] = cp.returncode == 0

    idx = dest_dir / "index.jsonl"
    if idx.exists():
        records = [json.loads(l) for l in idx.read_text().splitlines() if l.strip()]
        result["checkpoints"] = len(records)
        result["seq_monotonic"] = [r_["seq"] for r_ in records] == list(range(1, len(records) + 1))
        result["degraded"] = any(r_.get("degraded_watch") for r_ in records)
        if records:
            result["first_ts"], result["last_ts"] = records[0]["ts"], records[-1]["ts"]
    else:
        result["checkpoints"] = 0
    return result


def correlate_with_transcript(index_path: Path, transcript_path: Path) -> int:
    """Attach the nearest preceding tool call to each snapshot, by timestamp.

    Only fills in snapshots the adapter did not already mark ``explicit``.
    Returns how many records were updated.  Ordering is never inferred from this
    -- ``seq`` already carries it; this only improves attribution.
    """
    if not index_path.exists() or not transcript_path.exists():
        return 0

    calls: list[tuple[str, int, str]] = []
    for i, line in enumerate(transcript_path.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = ev.get("ts") or ev.get("timestamp")
        if ts and ev.get("type") in ("tool_call", "action", "tool_use"):
            calls.append((ts, i, ev.get("name") or ev.get("tool") or ""))
    calls.sort()

    records = [json.loads(l) for l in index_path.read_text().splitlines() if l.strip()]
    updated = 0
    for rec in records:
        if rec.get("correlation", {}).get("confidence") == "explicit":
            continue
        prior = [c for c in calls if c[0] <= rec["ts"]]
        if not prior:
            continue
        ts, idx, name = prior[-1]
        rec["correlation"] = {"tool_call_index": idx, "tool_name": name,
                              "tool_call_ts": ts, "confidence": "timestamp"}
        updated += 1
    index_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n")
    return updated


class ContainerWatcher:
    """Auto-attach the snapshotter to task containers as the harness starts them.

    Watches ``docker events`` for container starts whose name matches a prefix
    (``minisweagent-`` for the mini_swe_agent_v2 backend).  Avoids patching the
    harness, so an upstream change to the adapter cannot silently disable
    checkpointing -- if attachment fails, ``on_error`` is called and the run can
    be marked degraded rather than quietly losing its history.
    """

    def __init__(
        self,
        *,
        name_prefix: str = "minisweagent-",
        work_tree: str = "/workspace/repo",
        on_attach: Callable[[Attachment], None] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self.name_prefix = name_prefix
        self.work_tree = work_tree
        self.on_attach = on_attach
        self.on_error = on_error
        self.attachments: dict[str, Attachment] = {}
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not shutil.which("docker"):
            raise AttachError("docker not on PATH")
        self._proc = subprocess.Popen(
            ["docker", "events", "--filter", "type=container", "--filter", "event=start",
             "--format", "{{json .}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if self._stop.is_set():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = (ev.get("Actor", {}).get("Attributes", {}) or {}).get("name", "")
            cid = ev.get("Actor", {}).get("ID", "")
            if not cid or not name.startswith(self.name_prefix):
                continue
            try:
                att = attach(cid, self.work_tree)
                self.attachments[cid] = att
                if self.on_attach:
                    self.on_attach(att)
            except Exception as exc:                      # noqa: BLE001
                if self.on_error:
                    self.on_error(cid, exc)

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
