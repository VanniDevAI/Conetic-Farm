#!/usr/bin/env python3
"""Step B: three agents, one application, nothing planted.

Steps A and earlier all seeded a failure and asked whether the harness could
see it. This asks the opposite question. Three agents get three ordinary
feature requests on one real application, each in its own container on its own
branch with no channel between them, and the only thing arranged is that the
three tasks approach the same surfaces -- the router table, the migration
sequence, the config namespace, and the published API of `@trpc/server`. Whether
anything collides is the measurement.

Because nothing is seeded there are no per-lane graded tests. The product
outcome is what the repository's own checks say about the combination:
`tsc --noEmit` and the unit suite, run on the merged tree. The classes fall out
of that:

    a merge that conflicts                      -> textual
    a clean merge whose suite then fails        -> semantic
    a clean merge whose suite still passes      -> null, and that is a result

Every episode records the **stealth flag**: whether lane 1's own branch passes
the same checks. A failure the first branch's own CI would have caught is not a
coordination failure, and the flag is what keeps that honest.

Predictions are frozen in the plan and copied into the record before the
episode runs, so a prediction can never be written after its outcome.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm import conventions                                    # noqa: E402
from farm.episode_record import SCHEMA_VERSION, write_episode    # noqa: E402
from farm.grade import interpret_tests, run_cmd                  # noqa: E402
from farm.identity import build_index                            # noqa: E402
from farm.nway_merge import merge_lanes                          # noqa: E402
from farm.overlap import classify_overlap, parse_patch, semantic_link  # noqa: E402
from farm.provider import account_usage, settled_usage           # noqa: E402
from farm.surface import build_surface                           # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def run_solo(cb: Path, repo: str, task_id: int, fid: int, model: str,
             run_name: str, log_root: Path, agent_config: Path, timeout_s: int) -> Path:
    argv = [str(cb / ".venv" / "bin" / "cooperbench"), "run",
            "-n", run_name, "-r", repo, "-t", str(task_id), "-f", str(fid),
            "-m", model, "-a", "mini_swe_agent_v2", "--backend", "docker",
            "--setting", "solo", "-c", "1", "--no-auto-eval",
            "--log-dir", str(log_root), "--agent-config", str(agent_config)]
    subprocess.run(argv, cwd=str(cb), timeout=timeout_s,
                   env={**os.environ, "FARM_COOPERBENCH_DIR": str(cb)})
    return log_root / run_name / "solo" / repo / str(task_id) / f"f{fid}"


def suite(image: str, patches_dir: Path, patch_names: list[str], timeout_s: int = 2400):
    """The repository's own checks against a tree built from these patches."""
    argv = ["docker", "run", "--rm", "-v", f"{patches_dir}:/patches:ro", image, *patch_names]
    run = run_cmd(argv, timeout_s=timeout_s)
    text = run.stdout + run.stderr
    if "PATCH_FAILED:" in text:
        return "patch_failed", {"reason": text.split("PATCH_FAILED:", 1)[1].splitlines()[0].strip()}
    if "SUITE: pass" in text:
        return "pass", {"typecheck": 0, "vitest": 0}
    if "SUITE: fail" in text:
        detail = {}
        for key, marker in (("typecheck", "TYPECHECK_EXIT:"), ("vitest", "VITEST_EXIT:")):
            if marker in text:
                detail[key] = text.split(marker, 1)[1].splitlines()[0].strip()
        detail["tail"] = text[-4000:]
        return "fail", detail
    return "error", {"tail": text[-4000:]}


def claim_map(patches: dict[str, Path], consumer_root: Path,
              provider_root: Path | None, provider_entries: list[str]) -> dict:
    """Pairwise: does one lane's changed code reach another's, and is it public."""
    idx = build_index(consumer_root)
    surface = build_surface(provider_root, provider_entries) if provider_root else None
    facts = {lane: parse_patch(p.read_text()) for lane, p in patches.items() if p.exists()}
    pairs = []
    for a, b in combinations(sorted(facts), 2):
        chain = semantic_link(facts[a], facts[b], idx)
        row = {"lanes": [a, b],
               "overlap_class": classify_overlap(facts[a], facts[b], idx),
               "chain": chain,
               "published_surface": None}
        if chain and surface is not None:
            target = chain[-1]
            row["published_surface"] = {
                "symbol": target, "published": surface.is_published(target),
                "how": surface.how(target), "entries": provider_entries,
                "of": "@trpc/server",
            }
        pairs.append(row)
    return {"pairs": pairs,
            "note": "the consumer is an application and publishes no surface of "
                    "its own; the attribute is answered against @trpc/server, "
                    "the package the three lanes all build on"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--cooperbench-dir", default="/home/user/work/CooperBench")
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

    for ep in plan["episodes"]:
        if args.only and ep["id"] != args.only:
            continue
        out = root / ep["id"]
        patches_dir = out / "patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        log(f"=== {ep['id']}  ({ep['title']})")
        log(f"    frozen prediction: {ep['prediction']['frozen']}")

        aborted = None
        for lane in ep["lanes"]:
            dest = patches_dir / f"{lane['id']}.patch"
            if dest.exists() and dest.stat().st_size > 0:
                log(f"    {lane['id']}: reusing the patch already on disk")
                continue
            spent = (account_usage() or start) - start
            if spent >= args.cap_usd:
                aborted = f"cap reached before {lane['id']}: ${spent:.4f}"
                log(f"    STOPPING: {aborted}")
                break
            log(f"    {lane['id']}: {lane['model']}  (${spent:.4f} spent)")
            log_dir = run_solo(cb, ep["repo"], ep["task_id"], lane["feature"],
                               lane["model"], f"{plan['plan']}-{ep['id']}-{lane['id']}",
                               out / "logs", Path(args.agent_config), args.agent_timeout)
            src = log_dir / "solo.patch"
            if src.exists():
                shutil.copy2(src, dest)
            for extra in ("solo_traj.json", "result.json"):
                if (log_dir / extra).exists():
                    shutil.copy2(log_dir / extra, out / f"{lane['id']}_{extra}")
            after = settled_usage() or start
            ledger.append({"episode": ep["id"], "lane": lane["id"],
                           "spent_total": after - start})
            log(f"    {lane['id']} done; ${after - start:.4f} spent in total")

        present = [l for l in ep["lanes"]
                   if (patches_dir / f"{l['id']}.patch").exists()
                   and (patches_dir / f"{l['id']}.patch").stat().st_size > 0]

        # Each lane alone, against the repository's own checks.
        alone: dict[str, str] = {}
        for lane in present:
            outcome, detail = suite(ep["image"], patches_dir, [f"{lane['id']}.patch"])
            alone[lane["id"]] = outcome
            write_json(out / "results" / f"alone_{lane['id']}.json",
                       {"outcome": outcome, "detail": detail})
            log(f"    alone {lane['id']}: {outcome}")

        merge = None
        merged_outcome = None
        if len(present) >= 2:
            rep = merge_lanes(ep["image"], patches_dir,
                              [(l["id"], f"{l['id']}.patch") for l in present],
                              out_dir=out / "merge")
            merge = rep.to_dict()
            write_json(out / "merge" / "merge.json", merge)
            (out / "merge" / "merge_raw.txt").write_text(rep.raw)
            log(f"    merge: {rep.outcome} {rep.conflicted_paths or ''}")
            if rep.outcome == "clean":
                merged_outcome, detail = suite(
                    ep["image"], patches_dir, [f"{l['id']}.patch" for l in present])
                write_json(out / "results" / "merged.json",
                           {"outcome": merged_outcome, "detail": detail})
                log(f"    merged suite: {merged_outcome}")

        branches = {l["id"]: (patches_dir / f"{l['id']}.patch").read_text() for l in present}
        conv = conventions.grade(branches)
        write_json(out / "results" / "conventions.json", conv)
        cmap = claim_map({l["id"]: patches_dir / f"{l['id']}.patch" for l in present},
                         Path(ep["consumer_checkout"]),
                         Path(ep["provider_checkout"]) if ep.get("provider_checkout") else None,
                         ep.get("provider_entries", []))
        write_json(out / "results" / "claim_map.json", cmap)

        if merge is None:
            failure_class = None
        elif merge["outcome"] == "conflict":
            failure_class = "textual"
        elif merge["outcome"] == "clean" and merged_outcome == "fail":
            failure_class = "semantic"
        else:
            failure_class = None

        first = ep["lanes"][0]["id"]
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": ep["id"], "split": "train",
            "corpus": {"name": plan["corpus"], "repo": ep["repo"],
                       "base_commit": ep["base_commit"], "language": "typescript",
                       "provider": "@trpc/server@11.18.0 from the npm registry"},
            "seam": {"kind": "published_package",
                     "detail": "three lanes in one application repository, each in "
                               "its own container on its own branch with no channel; "
                               "the shared surfaces are the router table, the "
                               "migration sequence, the config namespace and the "
                               "published API of @trpc/server"},
            "lanes": [{"agent": l["id"], "model": l["model"],
                       "runtime": "cooperbench solo: own container, own branch, no "
                                  "mailbox, no shared git remote",
                       "brief": l["brief"],
                       "assumptions": [],
                       "alone_suite": alone.get(l["id"])}
                      for l in ep["lanes"]],
            "git_outcome": merge or {"outcome": None,
                                     "why": "fewer than two lanes produced a patch"},
            "product_outcome": {"per_lane_alone": alone, "merged_suite": merged_outcome,
                                "checks": "tsc --noEmit and vitest run"},
            "failure_class": failure_class,
            "stealth": {
                "flag": (failure_class is not None and alone.get(first) == "pass"),
                "measured": True,
                "why": "lane 1's own branch is measured against the same checks; "
                       "a failure its own CI would have caught is not stealthy",
                "first_lane": first, "first_lane_alone": alone.get(first),
            },
            "claim": cmap,
            "convention_graders": {
                "migration_ordinals": conv["migration_ordinals"],
                "route_paths": conv["route_paths"],
                "config_keys": conv["config_keys"],
                "concurrent_migrations": conv["concurrent_migrations"],
                "per_lane": conv["per_lane"],
            },
            "published_surface": {
                "published": any(p.get("published_surface", {}) and
                                 p["published_surface"].get("published")
                                 for p in cmap["pairs"]),
                "detail": [p["published_surface"] for p in cmap["pairs"]
                           if p.get("published_surface")],
            },
            "cost": {"usd": round((settled_usage() or start) - start
                                  - sum(0 for _ in []), 4),
                     "source": "provider meter delta since the run started",
                     "note": "cumulative for the run; per-lane deltas are in the ledger",
                     "ledger": [e for e in ledger if e["episode"] == ep["id"]]},
            "prediction": {
                "frozen": ep["prediction"]["frozen"],
                "observed": {"failure_class": failure_class,
                             "merge": merge["outcome"] if merge else None,
                             "merged_suite": merged_outcome,
                             "convention_hits": {k: len(conv[k]) for k in
                                                 ("migration_ordinals", "route_paths",
                                                  "config_keys")}},
                "correct": None,
                "source": args.plan,
            },
            "patches": {l["id"]: str(patches_dir / f"{l['id']}.patch") for l in present},
            "merge": {"dir": str(out / "merge"),
                      "outcome": merge["outcome"] if merge else None},
            "test_logs": {"dir": str(out / "results")},
            "checkpoints": {"dir": None,
                            "why": "solo runs keep no cross-agent checkpoint stream"},
            "aborted": aborted,
        }
        write_episode(record)
        write_json(out / "episode.json", record)
        log(f"    -> class={failure_class} stealth={record['stealth']['flag']} "
            f"hits={ {k: len(conv[k]) for k in ('migration_ordinals','route_paths','config_keys')} }")
        if aborted:
            break

    final = settled_usage() or start
    write_json(root / "spend.json", {"meter_start": start, "meter_end": final,
                                     "spent": final - start, "cap_usd": args.cap_usd,
                                     "ledger": ledger})
    log(f"done; ${final - start:.4f} spent of ${args.cap_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
