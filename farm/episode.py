"""One episode: run two agents, collect everything, grade the triad, label it.

Ordering matters and is deliberate:

1. Reserve budget **before** launching agents, so two concurrent episodes cannot
   jointly overshoot the cap.
2. Snapshot attachment starts **before** the harness, so the first write an agent
   makes is already captured.
3. Grading happens in fresh containers **after** the run, never in the agent's
   own container, so a graded tree cannot contain leftovers from the agent's
   session.
4. Every artifact is written as it is produced.  A crash mid-episode leaves a
   partial but readable episode directory, not nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import env as farm_env
from . import sandbox
from .checkpoints import ContainerWatcher, detach_and_export
from .classify import (
    AgentResult, Classification, MergeOutcome, MergeResult, TestOutcome, classify,
)
from .cost import Budget, BudgetExceeded, Usage, ZeroCostWithUsage, cost_of
from .grade import interpret_tests, write_json


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class EpisodeSpec:
    episode_id: str
    repo: str
    task_id: int
    f1: int
    f2: int
    language: str
    stratum: str
    gold_has_conflict: bool | None = None
    order: int = 0


@dataclass
class EpisodePaths:
    root: Path

    @property
    def base(self) -> Path: return self.root / "base"
    @property
    def attempts(self) -> Path: return self.root / "attempts"
    def attempt(self, n: int) -> Path: return self.attempts / f"attempt-{n:03d}"


class EpisodeRunner:
    def __init__(
        self,
        spec: EpisodeSpec,
        *,
        data_root: Path,
        cooperbench_dir: Path,
        budget: Budget,
        model_a: str,
        model_b: str,
        campaign: str,
        agent_config: Path | None = None,
        redis_url: str = "redis://127.0.0.1:6379",
        agent_timeout_s: int = 3600,
        log=print,
    ) -> None:
        self.spec = spec
        self.data_root = Path(data_root)
        self.cb = Path(cooperbench_dir)
        self.budget = budget
        self.model_a, self.model_b = model_a, model_b
        self.campaign = campaign
        self.agent_config = agent_config
        self.redis_url = redis_url
        self.agent_timeout_s = agent_timeout_s
        self.log = log
        self.paths = EpisodePaths(self.data_root / "episodes" / spec.episode_id)
        self.image = self._image_name()

    # -- setup -------------------------------------------------------------

    def _image_name(self) -> str:
        out = subprocess.run(
            [str(self.cb / ".venv" / "bin" / "python"), "-c",
             f"from cooperbench.utils import get_image_name;"
             f"print(get_image_name({self.spec.repo!r}, {self.spec.task_id}))"],
            capture_output=True, text=True, check=True)
        return out.stdout.strip()

    def ensure_image(self) -> None:
        if sandbox.image_exists(self.image):
            return
        self.log(f"    building task image {self.image}")
        r = subprocess.run(
            [str(Path(__file__).resolve().parents[1] / "scripts" / "build_task_image.sh"),
             self.spec.repo, str(self.spec.task_id)],
            capture_output=True, text=True,
            env={**os.environ, "FARM_COOPERBENCH_DIR": str(self.cb)},
            timeout=3600)
        if r.returncode != 0 or not sandbox.image_exists(self.image):
            raise sandbox.SandboxError(
                f"task image build failed for {self.spec.repo}/task{self.spec.task_id}: "
                f"{(r.stderr or r.stdout)[-800:]}")

    def prepare_base(self) -> dict[str, Any]:
        """Capture the exact pre-agent state, once per episode."""
        self.paths.base.mkdir(parents=True, exist_ok=True)
        marker = self.paths.base / "image.json"
        if marker.exists():
            return json.loads(marker.read_text())

        info = sandbox.export_base_bundle(self.image, self.paths.base)
        image_id = subprocess.run(
            ["docker", "image", "inspect", self.image, "--format", "{{.Id}}"],
            capture_output=True, text=True).stdout.strip()
        info |= {
            "image": self.image,
            "image_id": image_id,
            "substitution": {
                "upstream_base": "node:22-slim (per the dataset Dockerfile)",
                "actual_base": os.getenv("FARM_BASE_IMAGE", "conetic-farm/node22-base:local"),
                "reason": "registry blob downloads are blocked; base imported from the host rootfs",
                "apt_layer": "replaced by an assertion that git and python3 are present",
                "extra_env": ["NODE_EXTRA_CA_CERTS", "CYPRESS_INSTALL_BINARY=0",
                              "PUPPETEER_SKIP_DOWNLOAD=1", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1"],
            },
        }
        write_json(marker, info)

        task_src = self.cb / "dataset" / self.spec.repo / f"task{self.spec.task_id}"
        task_dst = self.paths.base / "task"
        if not task_dst.exists():
            shutil.copytree(task_src, task_dst)
        return info

    # -- the agent run -----------------------------------------------------

    def _cooperbench_argv(self, run_name: str, log_dir: Path) -> list[str]:
        return [
            str(self.cb / ".venv" / "bin" / "cooperbench"), "run",
            "-n", run_name,
            "-r", self.spec.repo,
            "-t", str(self.spec.task_id),
            "-f", f"{self.spec.f1},{self.spec.f2}",
            "-m", self.model_a,
            "-a", "mini_swe_agent_v2",
            "--backend", "docker",
            "--setting", "coop",
            "-c", "1",
            "--redis", self.redis_url,
            "--no-auto-eval",          # we grade ourselves; see docs/HARNESS_NOTES.md
            "--log-dir", str(log_dir),
            *(["--agent-config", str(self.agent_config)] if self.agent_config else []),
        ]

    def run_agents(self, attempt_dir: Path) -> dict[str, Any]:
        """Launch the two coop agents with checkpointing attached."""
        log_dir = attempt_dir / "harness_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        run_name = f"{self.campaign}_{self.spec.episode_id}"

        attached: dict[str, Any] = {}
        errors: list[str] = []
        watcher = ContainerWatcher(
            work_tree=sandbox.WORKDIR,
            on_attach=lambda a: attached.setdefault(a.container_id, a),
            on_error=lambda cid, exc: errors.append(f"{cid[:12]}: {exc}"),
        )
        watcher.start()

        started = _utcnow()
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                self._cooperbench_argv(run_name, log_dir),
                cwd=str(self.cb), env=farm_env.child_env(),
                capture_output=True, text=True, timeout=self.agent_timeout_s,
            )
            rc, out, err, timed_out = proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as exc:
            rc, timed_out = None, True
            out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        finally:
            # Export checkpoints while the containers are still alive.
            for cid, att in attached.items():
                try:
                    dest = attempt_dir / "checkpoints_raw" / cid[:12]
                    attached[cid] = {"attachment": att,
                                     "export": detach_and_export(att, dest),
                                     "dest": str(dest)}
                except Exception as exc:      # noqa: BLE001
                    errors.append(f"checkpoint export {cid[:12]}: {exc}")
            watcher.stop()

        # Credential-shaped strings must never reach disk, even in a stack trace.
        (attempt_dir / "harness_stdout.log").write_text(farm_env.redact(out))
        (attempt_dir / "harness_stderr.log").write_text(farm_env.redact(err))

        return {
            "returncode": rc,
            "timed_out": timed_out,
            "started_at": started,
            "finished_at": _utcnow(),
            "wallclock_s": round(time.monotonic() - t0, 2),
            "containers_attached": len(attached),
            "attach_errors": errors,
            "checkpoints": {cid: v.get("export") for cid, v in attached.items()
                            if isinstance(v, dict)},
            "log_dir": str(log_dir),
        }

    # -- collection --------------------------------------------------------

    def _harness_dir(self, log_dir: Path) -> Path | None:
        """Locate the harness's output directory for this pair.

        Layout is `<logs>/<run>/coop/<repo>/<task_id>/f<i>_f<j>/`
        (runner/coop.py:72).  Resolved by glob rather than reconstructed, so a
        change upstream surfaces as "not found" instead of silently reading the
        wrong directory.
        """
        fs = "_".join(f"f{f}" for f in sorted((self.spec.f1, self.spec.f2)))
        hits = list(log_dir.glob(f"*/coop/{self.spec.repo}/{self.spec.task_id}/{fs}"))
        return hits[0] if hits else None

    @staticmethod
    def _usage_from_trajectory(traj: dict[str, Any]) -> Usage:
        """Recover real token counts from the trajectory.

        The harness records only ``{"cost": …}`` (litellm_model.py:199), and that
        figure is zero whenever pricing lookup fails.  The underlying provider
        response is kept verbatim under ``extra.response``, so the true token
        counts are recoverable -- and we bill from those against our pinned
        table rather than trusting the harness's number.
        """
        u = Usage()
        for msg in traj.get("messages", []):
            extra = msg.get("extra") or {}
            usage = ((extra.get("response") or {}).get("usage")) or {}
            if not usage:
                continue
            u.requests += 1
            u.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            u.completion_tokens += int(usage.get("completion_tokens") or 0)
            details = usage.get("prompt_tokens_details") or {}
            u.cached_prompt_tokens += int(details.get("cached_tokens") or 0)
            cdet = usage.get("completion_tokens_details") or {}
            u.reasoning_tokens += int(cdet.get("reasoning_tokens") or 0)
        return u

    def collect(self, attempt_dir: Path, log_dir: Path) -> dict[str, Any]:
        """Copy every harness artifact into the episode, and index the agents."""
        src = self._harness_dir(log_dir)
        agents_dir = attempt_dir / "agents"
        raw_root = attempt_dir / "raw"
        collected: dict[str, Any] = {"harness_dir": str(src) if src else None,
                                     "agents": {}}
        if src is None:
            collected["error"] = "harness output directory not found"
            return collected

        raw_root.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, raw_root / f.name)

        for role, fid, model in (("A", self.spec.f1, self.model_a),
                                 ("B", self.spec.f2, self.model_b)):
            adir = agents_dir / role
            adir.mkdir(parents=True, exist_ok=True)
            patch_src = raw_root / f"agent{fid}.patch"
            traj_src = raw_root / f"agent{fid}_traj.json"

            patch_text = patch_src.read_text(errors="replace") if patch_src.exists() else ""
            (adir / "patch.diff").write_text(patch_text)

            traj: dict[str, Any] = {}
            if traj_src.exists():
                try:
                    traj = json.loads(traj_src.read_text())
                except json.JSONDecodeError:
                    traj = {}
            if traj:
                # Transcript as JSONL, one event per line, timestamps preserved.
                with (adir / "transcript.jsonl").open("w") as fh:
                    for i, msg in enumerate(traj.get("messages", [])):
                        extra = msg.get("extra") or {}
                        fh.write(json.dumps({
                            "index": i,
                            "role": msg.get("role"),
                            "ts_epoch": extra.get("timestamp"),
                            "ts": (datetime.fromtimestamp(extra["timestamp"], timezone.utc)
                                   .isoformat().replace("+00:00", "Z")
                                   if extra.get("timestamp") else None),
                            "content": msg.get("content"),
                            "actions": extra.get("actions"),
                            "usage": ((extra.get("response") or {}).get("usage")),
                            "type": "tool_call" if extra.get("actions") else "message",
                        }, default=str) + "\n")

            usage = self._usage_from_trajectory(traj)
            collected["agents"][role] = {
                "feature_id": fid,
                "model": traj.get("model") or model,
                "status": traj.get("status"),
                "steps": traj.get("steps"),
                "harness_reported_cost": traj.get("cost"),
                "usage": usage,
                "patch_bytes": len(patch_text),
                "has_patch": bool(patch_text.strip()),
                "dir": str(adir),
            }
        return collected

    # -- grading -----------------------------------------------------------

    def grade(self, attempt_dir: Path, collected: dict[str, Any]) -> tuple[Classification, dict]:
        """The A-alone / B-alone / merged triad, each in a fresh container."""
        results_dir = attempt_dir / "results"
        merge_dir = attempt_dir / "merge"
        results_dir.mkdir(parents=True, exist_ok=True)
        merge_dir.mkdir(parents=True, exist_ok=True)

        patches = attempt_dir / "patches"
        patches.mkdir(exist_ok=True)
        task = self.paths.base / "task"
        fa, fb = self.spec.f1, self.spec.f2

        # Test patches come from the dataset, never from an agent.
        for fid in (fa, fb):
            shutil.copy2(task / f"feature{fid}" / "tests.patch", patches / f"tests_f{fid}.patch")
        for role, fid in (("A", fa), ("B", fb)):
            src = attempt_dir / "agents" / role / "patch.diff"
            if src.exists():
                shutil.copy2(src, patches / f"agent_{role}.patch")

        def suite(test_fid: int, patch_name: str | None, tag: str) -> tuple[TestOutcome, dict]:
            run = sandbox.run_feature_tests(
                self.image, patches, f"tests_f{test_fid}.patch", patch_name)
            outcome, detail = interpret_tests(run)
            write_json(results_dir / f"{tag}.json", {
                "outcome": outcome.value, "detail": detail,
                "command": run.command, "exit_code": run.exit_code,
                "duration_s": run.duration_s, "timed_out": run.timed_out,
                "stdout_tail": run.stdout[-20000:], "stderr_tail": run.stderr[-20000:],
            })
            return outcome, detail

        agents = collected.get("agents", {})
        a_has = agents.get("A", {}).get("has_patch", False)
        b_has = agents.get("B", {}).get("has_patch", False)

        # A alone, against its own tests and its partner's.
        a_own = a_partner = TestOutcome.NOT_RUN
        if a_has:
            a_own, _ = suite(fa, "agent_A.patch", "a_alone_own")
            a_partner, _ = suite(fb, "agent_A.patch", "a_alone_partner")
        b_own = b_partner = TestOutcome.NOT_RUN
        if b_has:
            b_own, _ = suite(fb, "agent_B.patch", "b_alone_own")
            b_partner, _ = suite(fa, "agent_B.patch", "b_alone_partner")

        a_res = AgentResult(a_has, a_own, a_partner,
                            patch_bytes=agents.get("A", {}).get("patch_bytes", 0))
        b_res = AgentResult(b_has, b_own, b_partner,
                            patch_bytes=agents.get("B", {}).get("patch_bytes", 0))

        # The merge is attempted only when both patches exist; with one missing
        # there is nothing to integrate and the label is already decided.
        merge = MergeResult(MergeOutcome.NOT_ATTEMPTED)
        if a_has and b_has:
            rep = sandbox.three_way_merge(self.image, patches, "agent_A.patch", "agent_B.patch")
            write_json(merge_dir / "merge.json", rep.to_dict())
            (merge_dir / "merge_raw.txt").write_text(rep.raw)
            if rep.outcome is MergeOutcome.CLEAN:
                (merge_dir / "merged.diff").write_text(rep.merged_diff)
                shutil.copy2(merge_dir / "merged.diff", patches / "merged.patch")
                m_a, _ = suite(fa, "merged.patch", "merged_a")
                m_b, _ = suite(fb, "merged.patch", "merged_b")
                merge = MergeResult(MergeOutcome.CLEAN, m_a, m_b)
            elif rep.outcome is MergeOutcome.CONFLICT:
                (merge_dir / "conflict.txt").write_text(
                    "\n".join(rep.conflicted_paths) + "\n\n" + rep.raw)
                merge = MergeResult(MergeOutcome.CONFLICT,
                                    conflicted_paths=tuple(rep.conflicted_paths))
            else:
                merge = MergeResult(MergeOutcome.ERROR)

        harness_error = None
        if merge.outcome is MergeOutcome.ERROR:
            harness_error = None   # a patch that will not apply is a patch fact,
            # not infrastructure; classify() handles it via the alone-results.

        cls = classify(a_res, b_res, merge, harness_error=harness_error)
        write_json(results_dir / "classification.json", cls.to_dict())
        return cls, {"a": a_res, "b": b_res, "merge": merge}
