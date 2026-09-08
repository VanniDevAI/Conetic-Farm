"""Capture an agent's work at the instant the harness destroys its container.

The problem this closes (`docs/EXPECTATIONS.md` Appendix D):

`mini_swe_agent_v2` calls ``env.cleanup()`` the moment an agent finishes
(``adapter.py:278``).  ``cleanup()`` runs, in the background,

    (timeout 60 docker stop <cid> || docker rm -f <cid>) >/dev/null 2>&1 &

and the container was started with ``--rm`` (``environments/docker.py:30``), so
*stop* is *remove*.  The first agent to finish loses its working tree while the
second is still running; by the time the harness process returns there is one
container left to read.  In `c02` that cost one agent's patch in 11 of 16
measured episodes and, because a genuine integration failure needs both
patches, shrank the eligible sample from 16 to 5.

``run_args`` is not plumbed from the adapter's config into ``DockerEnvironment``
(only ``image``/``cwd``/``timeout``/``env`` are), so ``--rm`` cannot be dropped
by configuration, and patching the harness would make every manifest's
``harness.commit`` a lie.  What *is* under our control is the ``docker`` the
harness resolves: ``cleanup()`` invokes it by name through PATH.

So this module is that ``docker``.  ``farm/env.py`` puts ``farm/shim`` first on
the harness's PATH whenever an extraction directory is set.  On ``stop``,
``rm`` or ``kill`` of a running container it captures the working-tree patch
and exports the checkpoint bundle *first*, writes completion markers, and then
``execv``s the real docker with the original arguments.  Every other docker
call is passed straight through.

Three properties this must hold, in order of importance:

1. **The harness's teardown always happens.**  Capture failures, timeouts and
   bugs here are written to marker files and then the real command runs
   regardless.  A shim that could keep a container alive, or fail a stop the
   harness expected to succeed, would be worse than the race it replaces.
2. **Capture fits inside the harness's own timeout.**  ``cleanup()`` wraps the
   stop in ``timeout 60``; capture is bounded well under that, and ``execv``
   replaces the process image, so nothing here can outlive the real command.
3. **It never recurses.**  The capture itself shells out to docker; the shim
   directory is removed from PATH before that happens and a guard variable is
   set, so nested calls reach the real binary directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SHIM_DIR = HERE / "shim"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# farm imports are deferred into the functions that need them (see main):
# a failure to import must be a capture failure, never a failure of the
# harness's docker call.

PRE_EXECV_FAILURE = 97   # the wrapper's signal that the real docker did NOT run

TEARDOWN_VERBS = {"stop", "rm", "kill"}
# cleanup() wraps the stop in `timeout 60`.  Leave margin for the real stop.
CAPTURE_BUDGET_S = 40.0
# Checkpoint export's own wait for the snapshotter to flush; keep it short
# because it sits inside the budget above.
EXPORT_TIMEOUT_S = 12


def real_docker() -> str:
    return os.environ.get("FARM_REAL_DOCKER") or "/usr/bin/docker"


def _strip_shim_from_path() -> None:
    """Nested docker calls from the capture must reach the real binary."""
    keep = []
    for p in os.environ.get("PATH", "").split(os.pathsep):
        try:
            if p and Path(p).resolve() == SHIM_DIR.resolve():
                continue
        except OSError:
            pass
        keep.append(p)
    os.environ["PATH"] = os.pathsep.join(keep)


def teardown_targets(argv: list[str]) -> tuple[str, list[str]]:
    """(verb, container refs) when argv is a stop/rm/kill; ("", []) otherwise.

    Accepts both ``docker stop X`` and ``docker container stop X``.  Anything
    starting with ``-`` is an option, not a container.
    """
    args = list(argv)
    if args and args[0] == "container":
        args = args[1:]
    if not args or args[0] not in TEARDOWN_VERBS:
        return "", []
    return args[0], [a for a in args[1:] if a and not a.startswith("-")]


def _resolve_running(ref: str) -> str | None:
    """Full container id if `ref` names a *running* container, else None."""
    r = subprocess.run([real_docker(), "inspect", "-f", "{{.Id}} {{.State.Running}}", ref],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return None
    parts = r.stdout.split()
    if len(parts) != 2 or parts[1] != "true":
        return None
    return parts[0]


def capture(cid: str, extract_dir: Path, base_sha: str, work_tree: str,
            ckpt_dir: Path | None) -> dict:
    """Read everything the container holds that the run needs, then mark done.

    Markers, all under `extract_dir`:
      <cid12>.inprogress   capture started (removed on completion)
      <agent>.patch        the working-tree diff against the task base
      <agent>.json         provenance: patch metadata, checkpoint export result
      <cid12>.done         completion, contents = agent id
      <agent>.done         completion, contents = cid12
    `run_agents` waits on `.inprogress` and reads `.json`; nothing is inferred.
    """
    from farm import patchgen
    from farm.checkpoints import Attachment, detach_and_export

    extract_dir.mkdir(parents=True, exist_ok=True)
    short = cid[:12]
    meta: dict = {"container": short, "captured_by": "teardown_shim",
                  "captured_at": time.time()}
    (extract_dir / f"{short}.inprogress").write_text("")
    name = short
    try:
        name = patchgen.agent_id_of(cid, work_tree) or short
        meta["agent_id"] = name
        ex = patchgen.patch_from_container(cid, base_sha, work_tree=work_tree)
        (extract_dir / f"{name}.patch").write_text(ex.text)
        meta["patch"] = {**ex.to_dict(), "container": short}
        if ckpt_dir is not None:
            att = Attachment(container_id=cid, work_tree=work_tree)
            dest = Path(ckpt_dir) / short
            meta["checkpoints"] = detach_and_export(att, dest, timeout_s=EXPORT_TIMEOUT_S)
            meta["checkpoints_dest"] = str(dest)
    except Exception as exc:                                       # noqa: BLE001
        meta["error"] = f"{type(exc).__name__}: {exc}"
        meta.setdefault("agent_id", name)
    finally:
        (extract_dir / f"{name}.json").write_text(json.dumps(meta, indent=2, default=str))
        (extract_dir / f"{short}.done").write_text(name)
        (extract_dir / f"{name}.done").write_text(short)
        try:
            (extract_dir / f"{short}.inprogress").unlink()
        except OSError:
            pass
    return meta


def _capture_bounded(cid: str, extract_dir: Path, base_sha: str, work_tree: str,
                     ckpt_dir: Path | None) -> None:
    """Run capture() with a hard wall-clock budget; on overrun, record and move on.

    The thread cannot be killed, but the caller execv()s the real docker right
    after, which replaces the whole process -- threads included.
    """
    t = threading.Thread(target=capture, args=(cid, extract_dir, base_sha, work_tree, ckpt_dir),
                         daemon=True)
    t.start()
    t.join(CAPTURE_BUDGET_S)
    if t.is_alive():
        short = cid[:12]
        (extract_dir / f"{short}.timeout").write_text(
            f"capture exceeded {CAPTURE_BUDGET_S:.0f}s; proceeding with the harness's teardown\n")
        # Deliberately NO .done marker: a capture that did not finish is not a
        # capture, and run_agents must fall through to reading the container
        # live if it is still there.  Clear .inprogress so it does not wait.
        try:
            (extract_dir / f"{short}.inprogress").unlink()
        except OSError:
            pass


def _maybe_capture(argv: list[str]) -> None:
    """Everything that may run before the real docker.  Best-effort only."""
    extract = os.environ.get("FARM_EXTRACT_DIR")
    if not extract or os.environ.get("FARM_SHIM_ACTIVE"):
        return
    verb, refs = teardown_targets(argv)
    if not refs:
        return
    os.environ["FARM_SHIM_ACTIVE"] = "1"
    _strip_shim_from_path()
    from farm import patchgen
    extract_dir = Path(extract)
    base_sha = os.environ.get("FARM_BASE_SHA", "")
    work_tree = os.environ.get("FARM_WORK_TREE") or patchgen.DEFAULT_WORK_TREE
    ck = os.environ.get("FARM_CHECKPOINTS_DIR")
    ckpt_dir = Path(ck) if ck else None
    for ref in refs:
        try:
            cid = _resolve_running(ref)
            if not cid:
                continue                       # already stopped, or not a container
            if (extract_dir / f"{cid[:12]}.done").exists():
                continue                       # captured once already
            _capture_bounded(cid, extract_dir, base_sha, work_tree, ckpt_dir)
        except Exception as exc:                           # noqa: BLE001
            try:
                extract_dir.mkdir(parents=True, exist_ok=True)
                (extract_dir / f"{ref[:12]}.error").write_text(
                    f"{type(exc).__name__}: {exc}\n")
            except OSError:
                pass


def _exec_real(argv: list[str]) -> None:
    """Replace this process with the real docker.  Returns only on failure."""
    candidates = [real_docker()]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        c = Path(p) / "docker"
        try:
            if p and c.exists() and c.resolve() != (SHIM_DIR / "docker").resolve():
                candidates.append(str(c))
        except OSError:
            continue
    for rd in candidates:
        try:
            os.execv(rd, [rd, *argv])
        except OSError:
            continue


def main(argv: list[str]) -> int:
    try:
        _maybe_capture(argv)
    except BaseException:                                          # noqa: BLE001
        pass                    # a capture problem is never the harness's problem
    # Property 1: the real command always runs, with the original arguments.
    _exec_real(argv)
    # Only reachable if every execv failed: tell the wrapper the real docker
    # has NOT run, so it runs it itself.
    return PRE_EXECV_FAILURE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
