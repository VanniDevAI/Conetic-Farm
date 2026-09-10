#!/usr/bin/env python3
"""Run a seeded pair with the two agents genuinely isolated from each other.

`s03` ran both pairs in CooperBench's coop setting and neither fired. Two
suppressors were visible in the transcripts: the provider agent audited its own
call sites and repaired the consumer, and -- in one pair -- the agents opened
a channel and negotiated who was touching which lines. This runner removes both
confounds and changes nothing else.

**No channel.** Each feature runs as its own `--setting solo` invocation.
CooperBench's solo path passes `messaging_enabled=False`, `git_enabled=False`,
`comm_url=None` and `git_server_url=None`, so there is neither a mailbox nor
the shared `team` git remote that coop mode configures. The agents cannot
message each other and cannot fetch each other's branch.

**No shared territory.** The provider agent runs in an image whose consumer
module, and every file that reaches it through a runtime import, has been
removed and committed away; the leak check that built the image asserts the
consumer's method name appears nowhere. The consumer agent runs in the full
image with the provider's source bind-mounted read-only from the host at the
base commit, so it can build against the old contract but cannot edit it.

Grading is unchanged and happens in the *full* task image: each agent against
its own tests and its partner's, then a real three-way merge, then the merged
tree against both suites.

The cap is the provider's own meter, read before every agent and reconciled
after: no token estimate is trusted, and the run stops rather than starting an
agent that could take spend past the ceiling.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm import sandbox                                        # noqa: E402
from farm.classify import (AgentResult, MergeOutcome, MergeResult,  # noqa: E402
                           TestOutcome, classify)
from farm.grade import interpret_tests                          # noqa: E402
from farm.identity import build_index, reaches                  # noqa: E402
from farm.overlap import classify_overlap, parse_patch          # noqa: E402
from farm.surface import build_surface                         # noqa: E402
from farm.provider import account_usage, settled_usage          # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def harness_tag(cb: Path, repo: str, task_id: int) -> str:
    out = subprocess.run(
        [str(cb / ".venv" / "bin" / "python"), "-c",
         f"from cooperbench.utils import get_image_name;"
         f"print(get_image_name({repo!r}, {task_id}))"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def retag(source: str, dest: str) -> None:
    """Point the name CooperBench resolves at the image this agent should see."""
    subprocess.run(["docker", "tag", source, dest], check=True)


def extract_file(image: str, path_in_image: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", image,
                        path_in_image], capture_output=True, check=True)
    dest.write_bytes(r.stdout)


def agent_config_for(role: str, base_config: Path, out: Path,
                     readonly_mounts: list[tuple[str, str]]) -> Path:
    """Copy the campaign's agent config, adding this role's read-only mounts.

    `environment.run_args` reaches DockerEnvironment through a three-line
    forward added to the vendored adapter; see dataset/seeded/isolation.
    """
    import yaml
    cfg = yaml.safe_load(base_config.read_text()) or {}
    if readonly_mounts:
        env = cfg.setdefault("environment", {})
        run_args = list(env.get("run_args") or ["--rm"])
        for host, inside in readonly_mounts:
            run_args += ["-v", f"{host}:{inside}:ro"]
        env["run_args"] = run_args
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return out


def run_solo(cb: Path, repo: str, task_id: int, fid: int, model: str,
             run_name: str, log_root: Path, agent_config: Path,
             timeout_s: int) -> Path:
    """One agent, one feature, no peers. Returns the directory it logged to."""
    argv = [str(cb / ".venv" / "bin" / "cooperbench"), "run",
            "-n", run_name, "-r", repo, "-t", str(task_id), "-f", str(fid),
            "-m", model, "-a", "mini_swe_agent_v2", "--backend", "docker",
            "--setting", "solo", "-c", "1", "--no-auto-eval",
            "--log-dir", str(log_root), "--agent-config", str(agent_config)]
    log(f"    $ {' '.join(argv[-14:])}")
    subprocess.run(argv, cwd=str(cb), timeout=timeout_s,
                   env={**os.environ, "FARM_COOPERBENCH_DIR": str(cb)})
    return log_root / run_name / "solo" / repo / str(task_id) / f"f{fid}"


def claim_edge(pair_dir: Path, source_root: Path | None,
               entry_points: list[str] | None = None) -> dict:
    """What a claim map would have had to surface, from the gold patches.

    Recorded from the *gold* pair rather than from what the agents produced, so
    the answer to "would the claim map have flagged it" does not move when the
    agents' patches do.
    """
    a = parse_patch((pair_dir / "feature1" / "feature.patch").read_text())
    b = parse_patch((pair_dir / "feature2" / "feature.patch").read_text())
    out = {"diff_only_class": classify_overlap(a, b)}
    if source_root is None or not Path(source_root).is_dir():
        out["resolved"] = "no source checkout available"
        return out
    idx = build_index(Path(source_root))
    def changed(facts):
        got = set()
        for path, lines in facts.changed_lines.items():
            for ln in lines:
                d = idx.enclosing(path, ln)
                if d is not None:
                    got.add(d)
        return got
    A, B = changed(a), changed(b)
    path_names = reaches(idx, B, A, max_hops=3) or reaches(idx, A, B, max_hops=3)
    out.update({
        "a_changed": sorted(f"{d.path}::{d.name}" for d in A),
        "b_changed": sorted(f"{d.path}::{d.name}" for d in B),
        "claim_chain": path_names,
        "flagged": bool(path_names),
    })
    # Whether the contract at the end of the chain is on the package's published
    # surface. c05a split two runs of the same seed on exactly this: an internal
    # contract is repaired by the provider's own call-site audit and never
    # reaches a downstream consumer; an exported one does.
    entries = entry_points or []
    if path_names and entries:
        surface = build_surface(Path(source_root), entries)
        target = path_names[-1]
        out["published_surface"] = {
            "symbol": target,
            "published": surface.is_published(target),
            "how": surface.how(target),
            "entries": entries,
        }
    if path_names:
        for d in list(A) + list(B):
            if d.name == path_names[-1]:
                out["claim_line"] = f"{d.path}:{d.start}"
                break
    return out


def grade(image: str, out_dir: Path, task_dir: Path, fa: int, fb: int) -> dict:
    patches = out_dir / "patches"
    results = out_dir / "results"
    merge_dir = out_dir / "merge"
    results.mkdir(parents=True, exist_ok=True)
    merge_dir.mkdir(parents=True, exist_ok=True)
    for fid in (fa, fb):
        shutil.copy2(task_dir / f"feature{fid}" / "tests.patch",
                     patches / f"tests_f{fid}.patch")

    def suite(test_fid: int, patch_name: str | None, tag: str):
        run = sandbox.run_feature_tests(image, patches, f"tests_f{test_fid}.patch", patch_name)
        outcome, detail = interpret_tests(run)
        write_json(results / f"{tag}.json", {
            "outcome": outcome.value, "detail": detail, "command": run.command,
            "exit_code": run.exit_code, "duration_s": run.duration_s,
            "timed_out": run.timed_out, "stdout_tail": run.stdout[-20000:],
            "stderr_tail": run.stderr[-20000:]})
        return outcome, detail

    a_has = (patches / "agent_A.patch").exists() and (patches / "agent_A.patch").stat().st_size > 0
    b_has = (patches / "agent_B.patch").exists() and (patches / "agent_B.patch").stat().st_size > 0

    a_own = a_partner = b_own = b_partner = TestOutcome.NOT_RUN
    a_detail = b_detail = None
    if a_has:
        a_own, a_detail = suite(fa, "agent_A.patch", "a_alone_own")
        a_partner, _ = suite(fb, "agent_A.patch", "a_alone_partner")
    if b_has:
        b_own, b_detail = suite(fb, "agent_B.patch", "b_alone_own")
        b_partner, _ = suite(fa, "agent_B.patch", "b_alone_partner")

    a_res = AgentResult(a_has, a_own, a_partner,
                        patch_bytes=(patches / "agent_A.patch").stat().st_size if a_has else 0,
                        own_detail=a_detail)
    b_res = AgentResult(b_has, b_own, b_partner,
                        patch_bytes=(patches / "agent_B.patch").stat().st_size if b_has else 0,
                        own_detail=b_detail)

    merge = MergeResult(MergeOutcome.NOT_ATTEMPTED)
    if a_has and b_has:
        rep = sandbox.three_way_merge(image, patches, "agent_A.patch",
                                      "agent_B.patch", out_dir=merge_dir)
        write_json(merge_dir / "merge.json", rep.to_dict())
        (merge_dir / "merge_raw.txt").write_text(rep.raw)
        if rep.outcome is MergeOutcome.CLEAN:
            (merge_dir / "merged.diff").write_text(rep.merged_diff)
            shutil.copy2(merge_dir / "merged.diff", patches / "merged.patch")
            m_a, _ = suite(fa, "merged.patch", "merged_a")
            m_b, _ = suite(fb, "merged.patch", "merged_b")
            merge = MergeResult(MergeOutcome.CLEAN, m_a, m_b)
        elif rep.outcome is MergeOutcome.CONFLICT:
            merge = MergeResult(MergeOutcome.CONFLICT,
                                conflicted_paths=tuple(rep.conflicted_paths))
        else:
            merge = MergeResult(MergeOutcome.ERROR)

    cls = classify(a_res, b_res, merge)
    write_json(results / "classification.json", cls.to_dict())
    return {"classification": cls.to_dict(),
            "failure_class": cls.label.failure_class}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--cooperbench-dir", default="/home/user/work/CooperBench")
    ap.add_argument("--model", required=True)
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--agent-config", default=str(REPO_ROOT / "config" / "agent_config.yaml"))
    ap.add_argument("--agent-timeout", type=int, default=3600)
    ap.add_argument("--only", default=None, help="run just this pair id")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    cb = Path(args.cooperbench_dir)
    root = Path(args.data_root)
    root.mkdir(parents=True, exist_ok=True)

    start_meter = settled_usage()
    if start_meter is None:
        log("FATAL: the provider meter is unreadable; refusing to spend blind")
        return 2
    log(f"meter at start: ${start_meter:.4f}; ceiling ${args.cap_usd:.2f} of spend")

    ledger = []
    for pair in plan["pairs"]:
        if args.only and pair["id"] != args.only:
            continue
        repo, task_id = pair["repo"], pair["task_id"]
        fa, fb = pair["f1"], pair["f2"]
        out_dir = root / pair["id"]
        (out_dir / "patches").mkdir(parents=True, exist_ok=True)
        tag = harness_tag(cb, repo, task_id)
        full_image = pair["full_image"]
        task_dir = cb / "dataset" / repo / f"task{task_id}"

        log(f"=== {pair['id']}  ({repo}/task{task_id}, f{fa}+f{fb})")

        # B may read the provider, but only at the base commit and only as a
        # file it cannot write.  Take the copy out of the full image so it is
        # the same bytes the grader will use.
        provider_host = out_dir / "provider_readonly" / Path(pair["provider_path"]).name
        extract_file(full_image, f"/workspace/repo/{pair['provider_path']}", provider_host)
        provider_host.chmod(0o444)

        roles = [
            ("A", fa, pair["agent_a_image"], []),
            ("B", fb, full_image,
             [(str(provider_host), f"/workspace/repo/{pair['provider_path']}")]),
        ]
        aborted = None
        for role, fid, image, mounts in roles:
            spent = (account_usage() or start_meter) - start_meter
            if spent >= args.cap_usd:
                aborted = f"cap reached before agent {role}: ${spent:.4f} spent"
                log(f"    STOPPING: {aborted}")
                break
            log(f"    agent {role}: feature {fid}, image {image}, "
                f"${spent:.4f} spent so far")
            retag(image, tag)
            cfg = agent_config_for(role, Path(args.agent_config),
                                   out_dir / "configs" / f"agent_{role}.yaml", mounts)
            log_dir = run_solo(cb, repo, task_id, fid, args.model,
                               f"{plan['plan']}-{pair['id']}-{role}",
                               out_dir / "logs", cfg, args.agent_timeout)
            src = log_dir / "solo.patch"
            if src.exists():
                shutil.copy2(src, out_dir / "patches" / f"agent_{role}.patch")
            for extra in ("solo_traj.json", "result.json"):
                if (log_dir / extra).exists():
                    shutil.copy2(log_dir / extra, out_dir / f"agent_{role}_{extra}")
            after = settled_usage() or start_meter
            ledger.append({"pair": pair["id"], "role": role,
                           "meter_after": after, "spent_total": after - start_meter})
            log(f"    agent {role} done; ${after - start_meter:.4f} spent in total")

        # Grading always happens in the full image, never a trimmed one.
        retag(full_image, tag)
        graded = grade(full_image, out_dir, task_dir, fa, fb) if aborted is None else None
        edge = claim_edge(REPO_ROOT / "dataset" / "seeded" / repo / f"task{task_id}",
                          pair.get("source_checkout"), pair.get("entry_points"))
        write_json(out_dir / "pair_result.json", {
            "pair": pair, "aborted": aborted, "graded": graded,
            "claim_map": edge, "ledger": ledger,
        })
        if graded:
            log(f"    -> {graded['classification']['label']}  "
                f"class={graded['failure_class']}")

    final = settled_usage() or start_meter
    write_json(root / "spend.json", {
        "meter_start": start_meter, "meter_end": final,
        "spent": final - start_meter, "cap_usd": args.cap_usd, "ledger": ledger})
    log(f"done; ${final - start_meter:.4f} spent of ${args.cap_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
