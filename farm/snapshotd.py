#!/usr/bin/env python3
"""In-container working-tree snapshotter.

Retains the *sequence* in which an agent built its change, not just the final
patch.  Runs inside the task container alongside the agent, watches the agent's
working tree, and commits the whole tree into a shadow git repository after
every filesystem write.

Design constraints:

* **Invisible to the agent.**  The shadow repo lives outside the work tree
  (``GIT_DIR`` elsewhere, ``GIT_WORK_TREE`` pointed at it) and never touches the
  agent's own ``.git``, index, HEAD, or config.  ``core.excludesFile`` is
  neutralised so nothing the repo ignores is silently dropped from a snapshot.
* **Ordered and monotonic.**  ``seq`` counts from 1 and never repeats.  Ordering
  survives clock steps because a monotonic counter is recorded alongside
  wall-clock time.
* **Lossless under bursts.**  A debounce coalesces the many writes a single tool
  call makes into one snapshot, but a *quiet* period always flushes, so no write
  is left uncommitted.  ``fsync`` on the index file makes a killed container
  still leave a readable history.
* **Zero dependencies.**  Standard library plus ``git``.  inotify is used via
  ctypes when available; otherwise it falls back to polling.  The container has
  no pip access.

Usage (inside the container):

    python3 /opt/farm/snapshotd.py \
        --work-tree /workspace/repo \
        --git-dir   /workspace/.farm-checkpoints \
        --index     /workspace/.farm-checkpoints/index.jsonl \
        --debounce-ms 250

Send SIGTERM to stop; it flushes a final snapshot before exiting.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import json
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# inotify via ctypes (no third-party dependency inside the sandbox)
# ---------------------------------------------------------------------------

IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_ISDIR = 0x40000000
IN_Q_OVERFLOW = 0x00004000

WATCH_MASK = (
    IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO
    | IN_CREATE | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF
)

_EVENT_HEADER = struct.Struct("iIII")  # wd, mask, cookie, len

# Directories never worth watching or snapshotting.
SKIP_DIRS = {
    ".git", "node_modules", ".pnpm-store", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "target", "dist", "build",
    ".next", ".cache", ".farm-checkpoints",
}


class Inotify:
    """Minimal recursive inotify wrapper."""

    def __init__(self) -> None:
        libc_name = ctypes.util.find_library("c")
        self._libc = ctypes.CDLL(libc_name, use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.fd = self._libc.inotify_init1(0o4000)  # IN_NONBLOCK
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.watches: dict[int, str] = {}

    def add_tree(self, root: str) -> int:
        added = 0
        for dirpath, dirnames, _ in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if self.add(dirpath):
                added += 1
        return added

    def add(self, path: str) -> bool:
        wd = self._libc.inotify_add_watch(self.fd, path.encode(), WATCH_MASK)
        if wd < 0:
            err = ctypes.get_errno()
            if err == errno.ENOSPC:
                # Watch limit hit: the caller degrades to polling rather than
                # silently missing writes.
                raise OSError(errno.ENOSPC, "inotify watch limit reached")
            return False
        self.watches[wd] = path
        return True

    def read(self, timeout_s: float) -> tuple[list[tuple[str, int]], bool]:
        """Return (events, overflowed).  Blocks up to ``timeout_s``."""
        import select

        r, _, _ = select.select([self.fd], [], [], timeout_s)
        if not r:
            return [], False
        try:
            buf = os.read(self.fd, 65536)
        except BlockingIOError:
            return [], False
        out: list[tuple[str, int]] = []
        overflow = False
        off = 0
        while off + _EVENT_HEADER.size <= len(buf):
            wd, mask, _cookie, nlen = _EVENT_HEADER.unpack_from(buf, off)
            off += _EVENT_HEADER.size
            raw = buf[off:off + nlen]
            off += nlen
            if mask & IN_Q_OVERFLOW:
                overflow = True
                continue
            name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
            base = self.watches.get(wd)
            if base is None:
                continue
            path = os.path.join(base, name) if name else base
            # A new directory needs its own watch, or writes inside it are lost.
            if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO):
                if os.path.basename(path) not in SKIP_DIRS:
                    try:
                        self.add_tree(path)
                    except OSError:
                        overflow = True
            out.append((path, mask))
        return out, overflow

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Shadow git repository
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ShadowRepo:
    """A git repo whose work tree is the agent's, but whose state is ours."""

    def __init__(self, git_dir: Path, work_tree: Path) -> None:
        self.git_dir = git_dir
        self.work_tree = work_tree
        self._env = {
            **os.environ,
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(work_tree),
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(git_dir),           # keep ~/.gitconfig out of it
            "GIT_AUTHOR_NAME": "conetic-farm-snapshotd",
            "GIT_AUTHOR_EMAIL": "snapshotd@conetic-farm.invalid",
            "GIT_COMMITTER_NAME": "conetic-farm-snapshotd",
            "GIT_COMMITTER_EMAIL": "snapshotd@conetic-farm.invalid",
        }

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], env=self._env, capture_output=True,
            text=True, check=check,
        )

    def init(self) -> None:
        self.git_dir.mkdir(parents=True, exist_ok=True)
        if not (self.git_dir / "HEAD").exists():
            self.git("init", "--quiet", "--initial-branch=checkpoints")
        # The agent's .gitignore must not hide files from a *forensic* record.
        self.git("config", "core.excludesFile", "/dev/null")
        self.git("config", "core.fileMode", "false")
        self.git("config", "gc.auto", "0")
        self.git("config", "user.name", "conetic-farm-snapshotd")
        self.git("config", "user.email", "snapshotd@conetic-farm.invalid")
        # Ignore only what would make snapshots enormous or self-referential.
        info = self.git_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text("\n".join(sorted(SKIP_DIRS)) + "\n")

    def snapshot(self, message: str) -> tuple[str, str, str, dict[str, int]] | None:
        """Stage everything and commit.  Returns None when nothing changed."""
        self.git("add", "-A", check=False)
        diff = self.git("diff", "--cached", "--numstat", check=False).stdout
        if not diff.strip() and self._has_commit():
            return None
        stats = {"files_changed": 0, "insertions": 0, "deletions": 0}
        for line in diff.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                stats["files_changed"] += 1
                for i, key in ((0, "insertions"), (1, "deletions")):
                    if parts[i].isdigit():
                        stats[key] += int(parts[i])
        parent = self.head()
        self.git("commit", "--quiet", "--allow-empty", "-m", message, check=False)
        commit = self.head()
        if not commit:
            return None
        tree = self.git("rev-parse", f"{commit}^{{tree}}", check=False).stdout.strip()
        return commit, parent, tree, stats

    def _has_commit(self) -> bool:
        return bool(self.head())

    def head(self) -> str:
        r = self.git("rev-parse", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


class Snapshotter:
    def __init__(self, args: argparse.Namespace) -> None:
        self.work_tree = Path(args.work_tree).resolve()
        self.git_dir = Path(args.git_dir).resolve()
        self.index_path = Path(args.index).resolve()
        self.debounce_s = args.debounce_ms / 1000.0
        self.max_interval_s = args.max_interval_ms / 1000.0
        self.repo = ShadowRepo(self.git_dir, self.work_tree)
        self.seq = 0
        self._stop = threading.Event()
        self._pending: set[str] = set()
        self._marker_path = self.git_dir / "marker"
        self._degraded = False

    # -- index ------------------------------------------------------------

    def _append_index(self, rec: dict[str, object]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _read_marker(self) -> dict[str, object] | None:
        """An adapter that can hook per-tool-call drops a JSON marker here.

        Presence upgrades a snapshot's correlation from "timestamp" to
        "explicit"; absence is fine and costs only attribution precision.
        """
        try:
            data = json.loads(self._marker_path.read_text())
            self._marker_path.unlink(missing_ok=True)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def commit(self, trigger: str, paths: set[str]) -> None:
        marker = self._read_marker()
        seq = self.seq + 1
        msg = f"checkpoint {seq} {trigger} {_utcnow()}"
        res = self.repo.snapshot(msg)
        if res is None:
            return
        commit, parent, tree, stats = res
        self.seq = seq
        rel = sorted(
            os.path.relpath(p, self.work_tree)
            for p in paths
            if not os.path.relpath(p, self.work_tree).startswith("..")
        )[:64]
        correlation: dict[str, object]
        if marker:
            correlation = {**marker, "confidence": "explicit"}
        else:
            correlation = {"confidence": "timestamp"}
        self._append_index({
            "seq": seq,
            "ts": _utcnow(),
            "ts_monotonic_ns": time.monotonic_ns(),
            "commit": commit,
            "parent": parent,
            "tree": tree,
            "trigger": trigger,
            "paths": rel,
            "paths_truncated": len(paths) > 64,
            "files_changed": stats["files_changed"],
            "insertions": stats["insertions"],
            "deletions": stats["deletions"],
            "correlation": correlation,
            "degraded_watch": self._degraded,
        })

    # -- main loop --------------------------------------------------------

    def run(self) -> int:
        self.work_tree.mkdir(parents=True, exist_ok=True)
        self.repo.init()
        self.commit("baseline", set())

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self._stop.set())

        watcher: Inotify | None = None
        try:
            watcher = Inotify()
            watcher.add_tree(str(self.work_tree))
        except OSError as exc:
            print(f"snapshotd: inotify unavailable ({exc}); polling instead",
                  file=sys.stderr, flush=True)
            self._degraded = True
            if watcher:
                watcher.close()
            watcher = None

        last_event = 0.0
        last_commit = time.monotonic()

        while not self._stop.is_set():
            now = time.monotonic()
            if watcher is not None:
                events, overflow = watcher.read(timeout_s=0.1)
                if overflow:
                    # Queue overflow means writes were missed.  Record that
                    # honestly rather than pretending the history is complete.
                    self._degraded = True
                for path, _mask in events:
                    if any(part in SKIP_DIRS for part in Path(path).parts):
                        continue
                    self._pending.add(path)
                    last_event = now
            else:
                time.sleep(0.5)
                self._pending.add(str(self.work_tree))
                last_event = now

            quiesced = self._pending and (now - last_event) >= self.debounce_s
            overdue = self._pending and (now - last_commit) >= self.max_interval_s
            if quiesced or overdue:
                paths, self._pending = self._pending, set()
                self.commit("write" if quiesced else "interval", paths)
                last_commit = time.monotonic()

        if self._pending:
            self.commit("write", self._pending)
        self.commit("final", set())
        if watcher:
            watcher.close()
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Working-tree snapshotter")
    p.add_argument("--work-tree", required=True)
    p.add_argument("--git-dir", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--debounce-ms", type=int, default=250)
    p.add_argument("--max-interval-ms", type=int, default=15000,
                   help="force a snapshot if writes keep arriving this long")
    return Snapshotter(p.parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
