"""Campaign driver: run the frozen plan, episode by episode, under a hard cap.

Invariants:

* The plan is read, never written.  Nothing about a result can change which
  episodes run or in what order.
* Budget is reserved before an agent starts and settled from real token counts
  afterwards.  A reservation that would cross the cap stops the campaign; it
  does not shrink the work silently.
* Every attempt is written to disk and recorded in the manifest, including
  crashes, timeouts, and empty patches.  Nothing is filtered.
* The manifest is rewritten after every episode, so an interrupted campaign
  still leaves a complete index of what did run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm import env as farm_env                                   # noqa: E402
from farm.cost import (                                            # noqa: E402
    Budget, BudgetExceeded, MissingPrice, Usage, ZeroCostWithUsage,
    cost_of, load_pricing, price_for,
)
from farm.episode import EpisodeRunner, EpisodeSpec                 # noqa: E402
from farm.grade import write_json                                   # noqa: E402
from farm import provider                                          # noqa: E402
from farm.publish import (                                          # noqa: E402
    ArchiveTooLarge, CredentialInArtifact, publish_episode,
)
from farm.manifest import (                                         # noqa: E402
    AgentManifest, CampaignIndex, EpisodeManifest, build_attempt_entry, describe,
    describe_dir,
)


def _setting(flag, env_var: str, default):
    """An explicit flag wins, then the environment, then the default."""
    if flag is not None:
        return flag
    return os.environ.get(env_var, default)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# A pre-run hold sized to the worst plausible episode.  Deliberately generous:
# an under-sized hold lets two concurrent episodes jointly cross the cap, which
# is the one thing the cap exists to prevent.
def estimate_episode_cost(model_a: str, model_b: str, table) -> float:
    # Sized from measurement, not from the transcript: c01's first billed episode
    # cost $1.22 against a $0.78 hold, because trajectory token counts capture
    # only a fraction of what is really billed (farm/provider.py).  A hold that
    # is smaller than a real episode is not a hold.
    est = Usage(prompt_tokens=2_400_000, completion_tokens=200_000)
    total = 0.0
    for m in (model_a, model_b):
        p = price_for(m, table)
        total += p.cost(est.prompt_tokens, est.completion_tokens)
    return round(total, 4)



def _free_gb(path: Path) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


# Task images are rebuilt on demand and their episodes' artifacts are already
# published by the time the next episode starts, so they are the safe thing to
# reclaim.  Anything else -- above all the base image every task image is FROM --
# is not ours to delete.
TASK_IMAGE_PREFIXES = ("akhatua/cooperbench-", "conetic-farm/task-")


def reclaimable_images(listed: list[str], base: str) -> list[str]:
    """Which images the disk guard may delete.  The base is never one of them."""
    return [t for t in listed
            if t != base
            and t != "<none>:<none>"
            and any(t.startswith(pfx) for pfx in TASK_IMAGE_PREFIXES)]


def ensure_disk(min_free_gb: float, data_root: Path, log) -> None:
    """Keep enough writable space for the next episode, or stop cleanly.

    Task images are large (the react_hook_form image alone reports ~10 GB with
    its base and node_modules cache), and the plan spans eight repositories.
    Running out mid-episode corrupts nothing -- every artifact is written as it
    is produced -- but it wastes the spend on a half-finished run, so we check
    before starting rather than discovering it during one.
    """
    free = _free_gb(data_root)
    if free >= min_free_gb:
        return
    log(f"    disk low ({free:.1f} GB free, want {min_free_gb:.1f}); reclaiming")
    # Reclaim TASK images only, and never the base.
    #
    # Two wrong versions preceded this one, and both are worth remembering.
    # `image prune -f` removes only *dangling* images; every task image is
    # tagged, so it freed nothing and c02 hit ENOSPC twice with the guard firing
    # correctly.  `image prune -af` then removed every image no container was
    # using -- which includes conetic-farm/node22-base:local between builds, so
    # the guard deleted the base image and the next eight episodes died with
    # "base image missing".
    #
    # The base is the one image that must survive: it costs minutes to rebuild
    # and every task image is FROM it.  So remove task images by name instead of
    # asking docker for "everything unused".
    subprocess.run(["docker", "builder", "prune", "-af"],
                   capture_output=True, text=True, timeout=600)
    base = os.environ.get("FARM_BASE_IMAGE", "conetic-farm/node22-base:local")
    listed = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True, timeout=120).stdout.split()
    doomed = reclaimable_images(listed, base)
    if doomed:
        log(f"    reclaiming {len(doomed)} task image(s); keeping {base}")
        subprocess.run(["docker", "rmi", "-f", *doomed],
                       capture_output=True, text=True, timeout=900)
    # Dangling layers left behind by the above are safe to drop; -a is not.
    subprocess.run(["docker", "image", "prune", "-f"],
                   capture_output=True, text=True, timeout=600)
    free = _free_gb(data_root)
    log(f"    after reclaim: {free:.1f} GB free")
    if free < min_free_gb:
        raise SystemExit(
            f"stopping: only {free:.1f} GB free, need {min_free_gb:.1f} GB for the "
            f"next episode. Free space (docker image prune -a, or remove old "
            f"attempts under {data_root}) and re-run with --resume, which skips "
            f"episodes that already completed."
        )


class Campaign:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        farm_env.load()
        # Precedence: an explicit flag beats the environment, which beats the
        # default.  It used to be the other way round -- os.environ.get(VAR,
        # args.x) -- so `--data-root` was silently ignored whenever .env set
        # FARM_DATA_ROOT, and a run told to use a fresh directory quietly wrote
        # into the old one.  A flag that does nothing is worse than no flag.
        self.data_root = Path(_setting(args.data_root, "FARM_DATA_ROOT",
                                       "/home/user/farm-data"))
        self.cb = Path(_setting(args.cooperbench_dir, "FARM_COOPERBENCH_DIR",
                                "/home/user/work/CooperBench"))
        self.campaign = args.campaign
        self.model_a = _setting(args.model_a, "FARM_MODEL_A",
                                "openrouter/qwen/qwen3-coder")
        self.model_b = _setting(args.model_b, "FARM_MODEL_B",
                                "openrouter/qwen/qwen3-coder")
        self.cap = float(_setting(args.budget, "FARM_BUDGET_USD", 50.0))
        self.pricing = load_pricing()
        self.budget = Budget(self.cap, self.data_root / "ledger.jsonl")
        self.index = CampaignIndex(self.data_root / "manifest.json")
        self.log_path = self.data_root / f"campaign_{self.campaign}.log"
        # Where the provider's meter stood when this campaign began.  The cap is
        # enforced against the delta from here, not against the account's
        # lifetime usage, so a campaign is not punished for earlier runs.
        self.meter_start: float | None = None
        self.data_root.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        line = f"[{_utcnow()}] {msg}"
        print(line, flush=True)
        with self.log_path.open("a") as fh:
            fh.write(farm_env.redact(line) + "\n")

    # -- plan --------------------------------------------------------------

    def plan(self) -> list[EpisodeSpec]:
        data = json.loads(Path(self.args.plan).read_text())
        if not data.get("frozen"):
            raise SystemExit("refusing to run: the task plan is not marked frozen")
        specs = [EpisodeSpec(**{k: e[k] for k in
                                ("episode_id", "repo", "task_id", "f1", "f2",
                                 "language", "stratum", "gold_has_conflict", "order")})
                 for e in sorted(data["episodes"], key=lambda e: e["order"])]
        if self.args.limit:
            specs = specs[: self.args.limit]
        return specs

    # -- one episode -------------------------------------------------------

    def run_episode(self, spec: EpisodeSpec, n: int, total: int) -> dict[str, Any]:
        self.log(f"=== [{n}/{total}] {spec.episode_id}  ({spec.stratum}, {spec.language})")
        runner = EpisodeRunner(
            spec, data_root=self.data_root, cooperbench_dir=self.cb,
            budget=self.budget, model_a=self.model_a, model_b=self.model_b,
            campaign=self.campaign, agent_config=Path(self.args.agent_config),
            redis_url=os.environ.get("FARM_REDIS_URL", "redis://127.0.0.1:6379"),
            agent_timeout_s=self.args.agent_timeout, log=self.log,
        )
        manifest = EpisodeManifest(
            episode_id=spec.episode_id, campaign=self.campaign,
            repo=spec.repo, task_id=spec.task_id, features=(spec.f1, spec.f2),
            language=spec.language, stratum=spec.stratum,
            gold_has_conflict=spec.gold_has_conflict,
            data_root=str(self.data_root), episode_dir=str(runner.paths.root),
            harness={
                "name": "cooperbench", "adapter": "mini_swe_agent_v2",
                "setting": "coop", "backend": "docker",
                "commit": _git_head(self.cb),
                "agent_config": str(self.args.agent_config),
                "models": {"A": self.model_a, "B": self.model_b},
                "eval": "farm triad (A-alone / B-alone / merged); cooperbench eval NOT used",
            },
        )

        attempt_n = 1
        attempt_dir = runner.paths.attempt(attempt_n)
        while attempt_dir.exists():
            attempt_n += 1
            attempt_dir = runner.paths.attempt(attempt_n)
        attempt_dir.mkdir(parents=True, exist_ok=True)

        hold = f"{spec.episode_id}#{attempt_n}"
        estimate = estimate_episode_cost(self.model_a, self.model_b, self.pricing)
        started = _utcnow()
        # The provider's own meter, read before anything spends.  Settling from
        # the delta is the only figure that can bind a cap -- see farm/provider.py.
        usage_before = provider.account_usage()
        status, disposition, reason = "unknown", "counted", ""
        cls = None
        cost = 0.0
        agents_mf: list[AgentManifest] = []

        try:
            self.budget.reserve(hold, estimate, episode_id=spec.episode_id,
                                attempt=str(attempt_n), model=self.model_a)
        except BudgetExceeded as exc:
            self.budget.note(f"stopping before {spec.episode_id}: {exc}")
            raise

        try:
            runner.ensure_image()
            manifest.base = runner.prepare_base()
            run_info = runner.run_agents(attempt_dir)
            write_json(attempt_dir / "run_info.json", run_info)
            collected = runner.collect(attempt_dir, Path(run_info["log_dir"]))

            # Bill from real token counts against the pinned table, never from
            # the harness's reported figure (which is 0.0 on any pricing error).
            for role in ("A", "B"):
                info = collected.get("agents", {}).get(role)
                if not info:
                    continue
                usage: Usage = info["usage"]
                try:
                    c = cost_of(info["model"], usage, self.pricing)
                    src = "computed_from_tokens"
                except (MissingPrice, ZeroCostWithUsage) as exc:
                    c, src = 0.0, f"UNPRICED: {exc}"
                    self.log(f"    !! {role}: {exc}")
                cost += c
                agents_mf.append(AgentManifest(
                    role=role, feature_id=info["feature_id"], model=info["model"],
                    adapter="mini_swe_agent_v2", exit_status=str(info.get("status")),
                    usage={**usage.__dict__}, cost_usd=round(c, 6), cost_source=src,
                    patch=describe(attempt_dir / "agents" / role / "patch.diff"),
                    transcript=describe(attempt_dir / "agents" / role / "transcript.jsonl"),
                    raw_outputs=describe_dir(attempt_dir / "raw"),
                    checkpoints=_checkpoint_entry(attempt_dir, run_info),
                ))

            cls, _ = runner.grade(attempt_dir, collected)
            status = "completed"
            self.log(f"    -> {cls.label.value}  cost=${cost:.4f}  "
                     f"({'INTEGRATION FAILURE' if cls.genuine_integration_failure else 'not an integration failure'})")

        except Exception as exc:                              # noqa: BLE001
            status, disposition = "error", "counted"
            reason = f"{type(exc).__name__}: {exc}"
            (attempt_dir / "error.txt").write_text(
                farm_env.redact(reason + "\n\n" + traceback.format_exc()))
            self.log(f"    !! episode errored: {reason}")
        finally:
            rec = provider.reconcile(usage_before, cost)
            if rec.ratio is not None and (rec.ratio > 1.05 or rec.ratio < 0.95):
                self.log(f"    cost reconciled: tokens=${cost:.4f} "
                         f"provider=${rec.provider_usd:.4f} (x{rec.ratio})")
            if rec.source == "tokens_only" and rec.note:
                self.log(f"    !! billing from token counts only: {rec.note}")
            cost = rec.billed_usd
            self.budget.settle(hold, cost, episode_id=spec.episode_id,
                               attempt=str(attempt_n), model=self.model_a,
                               source=rec.source,
                               note=f"status={status}")
            write_json(attempt_dir / "cost.json",
                       {"episode_cost_usd": round(cost, 6),
                        "estimate_reserved_usd": estimate,
                        "reconciliation": rec.to_dict(),
                        "budget": self.budget.summary()})

        manifest.attempts.append(build_attempt_entry(
            attempt_dir, attempt_id=f"attempt-{attempt_n:03d}", status=status,
            disposition=disposition, disposition_reason=reason,
            started_at=started, finished_at=_utcnow(), agents=agents_mf,
            classification=cls.to_dict() if cls else None, cost_usd=cost))
        manifest.write()
        self.index.upsert(manifest)
        self.index.write()
        return {"episode_id": spec.episode_id, "status": status,
                "label": cls.label.value if cls else None, "cost": cost,
                "episode_dir": str(runner.paths.root),
                "stratum": spec.stratum, "language": spec.language,
                "genuine_integration_failure":
                    bool(cls.genuine_integration_failure) if cls else None}

    # -- resume -------------------------------------------------------------

    def already_completed(self, spec) -> bool:
        """True if this episode already has a completed attempt on disk.

        ensure_disk's stop message promised that completed episodes "will not be
        repeated" on a re-run.  They were: run_episode simply allocates the next
        free attempt directory and runs again, so resuming a disk-stopped
        campaign silently re-paid for every finished episode.  A promise the
        code did not keep is worse than no promise, so the code keeps it now.

        Only `completed` counts.  An episode that errored cost nothing (it died
        before any model call), and the reason may since have been fixed, so
        those are retried.
        """
        mf = self.data_root / "episodes" / spec.episode_id / "manifest.json"
        if not mf.exists():
            return False
        try:
            data = json.loads(mf.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        return any(a.get("status") == "completed" for a in data.get("attempts", []))

    # -- ceilings ----------------------------------------------------------

    def ceiling_reached(self, estimate: float) -> str:
        """Why the campaign must stop before the next episode, or "" to continue.

        Two independent ceilings, checked against the provider rather than
        against our own ledger -- c01 showed the ledger can be 5x low
        (farm/provider.py), and a ceiling checked against a wrong number is not
        a ceiling.

        1. The campaign cap: spend since this campaign started.
        2. The prepaid balance: a fact about the account, not a policy.  An
           episode that cannot be paid for should never be started, so the check
           is `remaining < estimate`, not `remaining <= 0` -- stopping *before*
           an unaffordable episode wastes nothing, stopping during one wastes it.

        An unreadable provider is not treated as permission to spend: it stops.
        """
        now = provider.account_usage()
        if now is None:
            return ("provider meter unreadable; refusing to continue without a "
                    "way to see spend")
        if self.meter_start is not None:
            spent = round(now - self.meter_start, 6)
            if spent >= self.cap:
                return f"campaign cap reached: ${spent:.4f} spent of ${self.cap:.2f}"

        bal = provider.credits()
        if bal.remaining is not None:
            if bal.remaining <= 0:
                return f"prepaid balance exhausted (${bal.remaining:.4f} left)"
            if bal.remaining < estimate:
                return (f"prepaid balance ${bal.remaining:.4f} is below the "
                        f"${estimate:.2f} an episode needs; stopping before an "
                        f"episode we cannot pay for")
        return ""

    # -- publish -----------------------------------------------------------

    def publish(self, result: dict[str, Any]) -> bool:
        """Archive a finished episode into the repo and push it.

        The campaign runs in an ephemeral container, so an episode that exists
        only under $FARM_DATA_ROOT is one reclaim away from gone -- and its
        spend is unrecoverable.  Publishing before the next episode starts
        bounds the loss to the episode in flight.
        """
        ep_dir = Path(result["episode_dir"])
        if not ep_dir.exists():
            self.log(f"    !! nothing to publish: {ep_dir} does not exist")
            return False
        try:
            res = publish_episode(
                ep_dir, repo_root=REPO_ROOT, campaign=self.campaign,
                branch=self.args.branch, summary=result, log=self.log,
                index_files={"manifest.json": self.data_root / "manifest.json",
                             "ledger.jsonl": self.data_root / "ledger.jsonl"},
            )
        except ArchiveTooLarge as exc:
            # Not fatal to the campaign: the episode's data is still on disk and
            # the run can continue.  It is loud, because an unarchived episode is
            # exactly what a container reclaim would take.
            self.log(f"    !! NOT PUBLISHED (too large): {exc}")
            return False
        except CredentialInArtifact as exc:
            # Never continue past this.  A key in an artifact is a leak, and the
            # next episode would write another one.
            self.log(f"    !! REFUSING TO PUBLISH: {exc}")
            return False
        except Exception as exc:                              # noqa: BLE001
            self.log(f"    !! publish failed: {type(exc).__name__}: {exc}")
            return False
        return res.pushed

    # -- campaign ----------------------------------------------------------

    def run(self) -> int:
        # Fail before building an image or starting a container.  Without this
        # the first missing credential surfaces as a 401 several minutes and one
        # image build into the run.
        farm_env.require("OPENROUTER_API_KEY")
        if not self.args.branch:
            self.args.branch = _current_branch(REPO_ROOT)
        specs = self.plan()
        self.meter_start = provider.account_usage()
        bal = provider.credits()
        self.log(f"campaign {self.campaign}: {len(specs)} episodes, "
                 f"cap ${self.cap:.2f}, models A={self.model_a} B={self.model_b}")
        self.log(f"provider meter at start: "
                 f"{'unreadable' if self.meter_start is None else f'${self.meter_start:.4f}'}"
                 f"; prepaid balance "
                 f"{'unknown' if bal.remaining is None else f'${bal.remaining:.4f}'}"
                 f" of ${bal.total_credits}")
        self.log(f"data root {self.data_root}")
        results: list[dict[str, Any]] = []
        stopped_unpublished = False
        per_episode = estimate_episode_cost(self.model_a, self.model_b, self.pricing)
        skipped = 0
        for i, spec in enumerate(specs, 1):
            if self.args.resume and self.already_completed(spec):
                self.log(f"=== [{i}/{len(specs)}] {spec.episode_id}  "
                         f"SKIPPED: already completed")
                skipped += 1
                continue
            if self.budget.remaining_usd <= 0:
                self.log(f"STOPPING: ledger cap reached after {i-1} episodes "
                         f"({self.budget.summary()})")
                break
            stop = self.ceiling_reached(per_episode)
            if stop:
                self.log(f"STOPPING cleanly after {i-1} episodes: {stop}")
                break
            try:
                ensure_disk(self.args.min_free_gb, self.data_root, self.log)
                result = self.run_episode(spec, i, len(specs))
                results.append(result)
            except BudgetExceeded as exc:
                self.log(f"STOPPING: {exc}")
                break
            except Exception as exc:                          # noqa: BLE001
                # run_episode guards its own body, but not its finally block or
                # the manifest writes after it.  An ENOSPC while writing
                # cost.json would otherwise kill the campaign *after* the agents
                # were billed and *before* anything was published -- losing a
                # paid-for episode to a bookkeeping failure.  The attempt
                # directory is on disk either way, so publish it, then stop.
                self.log(f"    !! episode raised outside its own guard: "
                         f"{type(exc).__name__}: {exc}")
                ep_dir = self.data_root / "episodes" / spec.episode_id
                if self.args.publish and ep_dir.exists():
                    self.publish({"episode_id": spec.episode_id,
                                  "status": "crashed_after_billing",
                                  "label": None, "cost": None,
                                  "episode_dir": str(ep_dir)})
                self.log("STOPPING: an episode failed outside its own error "
                         "handling; not starting another.")
                stopped_unpublished = True
                break
            if self.args.publish and not self.publish(result):
                self.log("STOPPING: the episode could not be pushed.  Its data "
                         "exists only in this container, which is ephemeral; "
                         "continuing would risk losing more paid-for episodes.")
                stopped_unpublished = True
                break
        write_json(self.data_root / f"campaign_{self.campaign}_results.json", {
            "campaign": self.campaign, "finished_at": _utcnow(),
            "episodes_run": len(results), "episodes_planned": len(specs),
            "budget": self.budget.summary(), "results": results,
            "provider": {"meter_start": self.meter_start,
                         "meter_end": provider.account_usage(),
                         "credits": provider.credits().to_dict()},
        })
        self.log(f"done: {len(results)} run, {skipped} skipped as already "
                 f"complete, of {len(specs)} planned; "
                 f"${self.budget.committed_usd:.4f} spent this invocation")
        # A campaign that stopped because it could not save an episode did not
        # succeed, and must not report success to whatever is watching.
        return 1 if stopped_unpublished else 0


def _checkpoint_entry(attempt_dir: Path, run_info: dict[str, Any]) -> dict[str, Any]:
    """Checkpoints are process data and live beside the patch, never inside it."""
    return {
        "dir": str(attempt_dir / "checkpoints_raw"),
        "containers": run_info.get("containers_attached", 0),
        "exports": run_info.get("checkpoints", {}),
        "attach_errors": run_info.get("attach_errors", []),
        "format": "git bundle + index.jsonl; commits oldest-first are seq 1..N",
    }


def _current_branch(path: Path) -> str:
    """The branch actually checked out, so a publish cannot push a stale ref."""
    r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path,
                       capture_output=True, text=True)
    name = r.stdout.strip()
    if r.returncode != 0 or not name or name == "HEAD":
        raise RuntimeError(
            "cannot determine the current branch (detached HEAD?); pass --branch "
            "explicitly rather than risk publishing to the wrong ref")
    return name


def _git_head(path: Path) -> str:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", default="c01")
    ap.add_argument("--plan", default=str(REPO_ROOT / "config" / "task_plan.json"))
    ap.add_argument("--agent-config", default=str(REPO_ROOT / "config" / "agent_config.yaml"))
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--cooperbench-dir", default=None)
    ap.add_argument("--model-a", default=None)
    ap.add_argument("--model-b", default=None)
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--agent-timeout", type=int, default=3600)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N episodes")
    ap.add_argument("--resume", action="store_true",
                    help="skip episodes that already have a completed attempt in "
                         "this data root (errored episodes are still retried, "
                         "since they cost nothing and their cause may be fixed)")
    ap.add_argument("--publish", action=argparse.BooleanOptionalAction, default=True,
                    help="archive each finished episode into the repo and push it "
                         "before starting the next (default: on; the container is "
                         "ephemeral, so unpublished episode data can be lost)")
    ap.add_argument("--branch", default=None,
                    help="branch to push published episodes to "
                         "(default: the branch actually checked out)")
    ap.add_argument("--min-free-gb", type=float, default=12.0,
                    help="free disk required before starting an episode")
    return Campaign(ap.parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
