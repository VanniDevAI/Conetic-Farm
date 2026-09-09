#!/usr/bin/env python3
"""Run a seeded pair across a real package seam.

`s04` produced two semantic integration failures, but the ownership boundary was
constructed: files were removed from one agent's image because neither pair has
a package seam to enforce. This runner replaces that construction with the real
thing. The provider agent works in its own repository, whole and unmodified. The
consumer agent works in a different repository that depends on the provider as a
published package, installed from the registry at the version of the provider's
base commit. Neither can see the other, for the ordinary reason that they are
different repositories, and no file is cut and no path is mounted.

Two repositories cannot conflict, so the merge is clean by construction and is
recorded that way rather than inferred from a merge that ran. What decides the
episode is the integrated run: the provider is rebuilt from the provider agent's
patch, packed with `npm pack`, and installed over the registry copy in the
consumer's image, and the consumer's graded tests run against it.

Every episode also records the **stealth flag**: whether the provider's patch
leaves the provider repository's own full suite green. A failure the provider's
own CI would have caught is not a coordination failure, whatever the consumer
does with it.
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

from farm import sandbox                                       # noqa: E402
from farm.grade import interpret_tests                         # noqa: E402
from farm.provider import account_usage, settled_usage         # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def run_solo(cb: Path, repo: str, task_id: int, fid: int, model: str,
             run_name: str, log_root: Path, agent_config: Path,
             timeout_s: int) -> Path:
    argv = [str(cb / ".venv" / "bin" / "cooperbench"), "run",
            "-n", run_name, "-r", repo, "-t", str(task_id), "-f", str(fid),
            "-m", model, "-a", "mini_swe_agent_v2", "--backend", "docker",
            "--setting", "solo", "-c", "1", "--no-auto-eval",
            "--log-dir", str(log_root), "--agent-config", str(agent_config)]
    subprocess.run(argv, cwd=str(cb), timeout=timeout_s,
                   env={**os.environ, "FARM_COOPERBENCH_DIR": str(cb)})
    return log_root / run_name / "solo" / repo / str(task_id) / f"f{fid}"


def pack_provider(image: str, patch_dir: Path, patch_name: str, out_dir: Path,
                  package_dir: str, build_cmd: str, restore: str,
                  timeout_s: int = 1800) -> str | None:
    """Build the provider from an agent's patch and pack it into `out_dir`.

    Returns the tarball's file name, or None if the build failed -- which is a
    fact about the patch, not about the harness, and is recorded as one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.tgz"):
        stale.unlink()
    script = f"""set -e
cd /workspace/repo
{restore}
git apply --ignore-whitespace --ignore-space-change /patches/{patch_name} \
  || git apply --3way /patches/{patch_name}
cd {package_dir}
{build_cmd}
npm pack --pack-destination /out --loglevel=error
"""
    r = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{patch_dir}:/patches:ro",
         "-v", f"{out_dir}:/out", "--entrypoint", "bash", image, "-c", script],
        capture_output=True, text=True, timeout=timeout_s)
    (out_dir / "build.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    tarballs = sorted(out_dir.glob("*.tgz"))
    return tarballs[0].name if tarballs else None


def consumer_run(image: str, patches: Path, provider_dir: Path | None,
                 test_patch: str, feature_patch: str | None, tgz: str | None,
                 timeout_s: int = 1800):
    argv = ["docker", "run", "--rm", "-v", f"{patches}:/patches:ro"]
    if provider_dir is not None:
        argv += ["-v", f"{provider_dir}:/provider:ro"]
    argv += [image, test_patch]
    if feature_patch:
        argv.append(feature_patch)
    if tgz:
        # The runner takes the tarball as its third positional argument, so a
        # feature patch has to be present for it to be read as the third.
        if not feature_patch:
            raise ValueError("a provider tarball needs a feature patch before it")
        argv.append(tgz)
    return sandbox.run_cmd(argv, timeout_s=timeout_s)


def full_suite(image: str, patch_dir: Path, patch_name: str, restore: str,
               suite_cmd: str, timeout_s: int = 2400):
    script = f"""set -e
cd /workspace/repo
{restore}
git apply --ignore-whitespace --ignore-space-change /patches/{patch_name} \
  || git apply --3way /patches/{patch_name}
{suite_cmd}
"""
    return sandbox.run_cmd(
        ["docker", "run", "--rm", "-v", f"{patch_dir}:/patches:ro",
         "--entrypoint", "bash", image, "-c", script], timeout_s=timeout_s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--cooperbench-dir", default="/home/user/work/CooperBench")
    ap.add_argument("--model", required=True)
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--agent-config", default=str(REPO_ROOT / "config" / "agent_config.yaml"))
    ap.add_argument("--agent-timeout", type=int, default=3600)
    ap.add_argument("--only", default=None)
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    cb = Path(args.cooperbench_dir)
    root = Path(args.data_root)
    root.mkdir(parents=True, exist_ok=True)

    start = settled_usage()
    if start is None:
        log("FATAL: provider meter unreadable; refusing to spend blind")
        return 2
    log(f"meter at start ${start:.4f}; ceiling ${args.cap_usd:.2f}")
    ledger: list[dict] = []

    for pair in plan["pairs"]:
        if args.only and pair["id"] != args.only:
            continue
        out = root / pair["id"]
        patches_p = out / "patches_provider"
        patches_c = out / "patches_consumer"
        patches_p.mkdir(parents=True, exist_ok=True)
        patches_c.mkdir(parents=True, exist_ok=True)
        log(f"=== {pair['id']}")
        log(f"    prediction: {pair['prediction']} -- {pair['why']}")

        aborted = None
        lanes = [("A", pair["provider_repo"], pair["provider_task"], pair["provider_feature"]),
                 ("B", pair["consumer_repo"], pair["consumer_task"], pair["consumer_feature"])]
        for role, repo, task_id, fid in lanes:
            spent = (account_usage() or start) - start
            if spent >= args.cap_usd:
                aborted = f"cap reached before lane {role}: ${spent:.4f}"
                log(f"    STOPPING: {aborted}")
                break
            dest_patch = (patches_p if role == "A" else patches_c) / f"agent_{role}.patch"
            if dest_patch.exists() and dest_patch.stat().st_size > 0:
                # Resume: a lane that already produced a patch is not re-run and
                # not re-paid for. The first attempt at this run lost both
                # consumer lanes to CooperBench's task discovery, which skips any
                # task carrying fewer than two features, and re-running the
                # provider lanes to recover them would have paid for them twice.
                log(f"    lane {role}: reusing the patch already on disk, not re-run")
                continue
            log(f"    lane {role}: {repo}/task{task_id} f{fid}  (${spent:.4f} spent)")
            log_dir = run_solo(cb, repo, task_id, fid, args.model,
                               f"{plan['plan']}-{pair['id']}-{role}",
                               out / "logs", Path(args.agent_config), args.agent_timeout)
            dest = patches_p if role == "A" else patches_c
            src = log_dir / "solo.patch"
            if src.exists():
                shutil.copy2(src, dest / f"agent_{role}.patch")
            for extra in ("solo_traj.json", "result.json"):
                if (log_dir / extra).exists():
                    shutil.copy2(log_dir / extra, out / f"agent_{role}_{extra}")
            after = settled_usage() or start
            ledger.append({"pair": pair["id"], "role": role, "spent_total": after - start})
            log(f"    lane {role} done; ${after - start:.4f} spent in total")

        result: dict = {"pair": pair, "aborted": aborted}
        a_patch = patches_p / "agent_A.patch"
        b_patch = patches_c / "agent_B.patch"
        result["has_patch"] = {"A": a_patch.exists() and a_patch.stat().st_size > 0,
                               "B": b_patch.exists() and b_patch.stat().st_size > 0}

        if aborted is None and result["has_patch"]["A"]:
            shutil.copy2(cb / "dataset" / pair["provider_repo"] / f"task{pair['provider_task']}"
                         / f"feature{pair['provider_feature']}" / "tests.patch",
                         patches_p / "tests_A.patch")
            run = sandbox.run_feature_tests(pair["provider_image"], patches_p,
                                            "tests_A.patch", "agent_A.patch")
            outcome, detail = interpret_tests(run)
            write_json(out / "results" / "a_alone.json",
                       {"outcome": outcome.value, "detail": detail,
                        "stdout_tail": run.stdout[-20000:]})
            result["a_alone"] = outcome.value

            # Stealth flag: does A's own repository stay green on its own suite?
            fs = full_suite(pair["provider_image"], patches_p, "agent_A.patch",
                            pair["restore_cmd"], pair["full_suite_cmd"])
            fs_outcome, fs_detail = interpret_tests(fs)
            write_json(out / "results" / "a_full_suite.json",
                       {"outcome": fs_outcome.value, "detail": fs_detail,
                        "stdout_tail": fs.stdout[-20000:]})
            result["a_full_suite"] = fs_outcome.value
            result["stealthy"] = fs_outcome.value == "pass"

        if aborted is None and result["has_patch"]["B"]:
            shutil.copy2(cb / "dataset" / pair["consumer_repo"] / f"task{pair['consumer_task']}"
                         / f"feature{pair['consumer_feature']}" / "tests.patch",
                         patches_c / "tests_B.patch")
            run = consumer_run(pair["consumer_image"], patches_c, None,
                               "tests_B.patch", "agent_B.patch", None)
            outcome, detail = interpret_tests(run)
            write_json(out / "results" / "b_alone.json",
                       {"outcome": outcome.value, "detail": detail,
                        "stdout_tail": run.stdout[-20000:]})
            result["b_alone"] = outcome.value

        result["merge"] = {
            "outcome": "clean",
            "conflicted_paths": [],
            "why": "the two patches are in different repositories; there is no "
                   "shared path for git to conflict on",
            "structural": True,
        }

        if aborted is None and all(result["has_patch"].values()):
            tgz = pack_provider(pair["provider_image"], patches_p, "agent_A.patch",
                                out / "provider_build", pair["package_dir"],
                                pair["build_cmd"], pair["restore_cmd"])
            result["provider_tarball"] = tgz
            if tgz is None:
                result["integrated"] = "provider build failed"
            else:
                run = consumer_run(pair["consumer_image"], patches_c,
                                   out / "provider_build", "tests_B.patch",
                                   "agent_B.patch", tgz)
                outcome, detail = interpret_tests(run)
                write_json(out / "results" / "integrated.json",
                           {"outcome": outcome.value, "detail": detail,
                            "stdout_tail": run.stdout[-20000:]})
                result["integrated"] = outcome.value

        fired = (result.get("a_alone") == "pass" and result.get("b_alone") == "pass"
                 and result.get("integrated") == "fail")
        result["fired"] = fired
        result["failure_class"] = "semantic" if fired else None
        result["ledger"] = ledger
        write_json(out / "pair_result.json", result)
        log(f"    -> fired={fired}  a_alone={result.get('a_alone')} "
            f"b_alone={result.get('b_alone')} integrated={result.get('integrated')} "
            f"stealthy={result.get('stealthy')}")

    final = settled_usage() or start
    write_json(root / "spend.json", {"meter_start": start, "meter_end": final,
                                     "spent": final - start, "cap_usd": args.cap_usd,
                                     "ledger": ledger})
    log(f"done; ${final - start:.4f} spent of ${args.cap_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
