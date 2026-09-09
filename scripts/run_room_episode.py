#!/usr/bin/env python3
"""c06: does a room change what an agent ships.

Two arms over the same tasks, the same model and the same sandbox rules, with
one difference between them.

    bare    the task and the repository, and nothing else.
    roomed  the same, plus a brief generated from the claim map -- what this
            code assumes, who looks at it, what names are already claimed --
            an assumption check to run before writing, and one repair pass if
            the integration check flags something.

The room is machine-made (`farm.room_brief`). No model writes it, or the
experiment would be measuring the model that wrote the brief rather than the
room.

Both lanes of an episode run alone, in their own containers, on their own
branches, with no channel. Nothing is planted: the two briefs in a pair ask for
different features *of the same kind* on the same table, which is where a
convention collision actually lives, and whether the lanes collide is the
measurement.
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

from farm import conventions                                     # noqa: E402
from farm.episode_record import SCHEMA_VERSION, write_episode     # noqa: E402
from farm.grade import run_cmd                                    # noqa: E402
from farm.identity import build_index                             # noqa: E402
from farm.lane_budget import LaneWatchdog, Reserve, image_base_commit  # noqa: E402
from farm.nway_merge import merge_lanes                           # noqa: E402
from farm.overlap import classify_overlap, parse_patch, semantic_link  # noqa: E402
from farm.provider import account_usage, settled_usage            # noqa: E402
from farm.room_brief import build as build_room                   # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def install_brief(cb: Path, repo: str, task_id: int, fid: int, text: str) -> None:
    d = cb / "dataset" / repo / f"task{task_id}" / f"feature{fid}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.md").write_text(text)


def run_solo(cb: Path, repo: str, task_id: int, fid: int, model: str,
             run_name: str, log_root: Path, agent_config: Path, timeout_s: int) -> Path:
    argv = [str(cb / ".venv" / "bin" / "cooperbench"), "run",
            "-n", run_name, "-r", repo, "-t", str(task_id), "-f", str(fid),
            "-m", model, "-a", "mini_swe_agent_v2", "--backend", "docker",
            "--setting", "solo", "-c", "1", "--no-auto-eval", "--force",
            "--log-dir", str(log_root),
            "--agent-config", str(Path(agent_config).resolve())]
    subprocess.run(argv, cwd=str(cb), timeout=timeout_s,
                   env={**os.environ, "FARM_COOPERBENCH_DIR": str(cb)})
    return log_root / run_name / "solo" / repo / str(task_id) / f"f{fid}"


def suite(image: str, patches_dir: Path, names: list[str], timeout_s: int = 2400):
    argv = ["docker", "run", "--rm", "-v", f"{patches_dir}:/patches:ro", image, *names]
    run = run_cmd(argv, timeout_s=timeout_s)
    text = run.stdout + run.stderr
    if "PATCH_FAILED:" in text:
        return "patch_failed", {"tail": text[-3000:]}
    if "SUITE: pass" in text:
        return "pass", {}
    if "SUITE: fail" in text:
        return "fail", {"tail": text[-3000:]}
    return "error", {"tail": text[-3000:]}


def repair_image(base_image: str, patch: Path, tag: str) -> str | None:
    """An image whose HEAD carries one lane's work, so it can continue from it."""
    ctx = patch.parent / f"_repair_{tag.replace('/', '_').replace(':', '_')}"
    ctx.mkdir(parents=True, exist_ok=True)
    shutil.copy2(patch, ctx / "lane.patch")
    (ctx / "Dockerfile").write_text(f"""FROM {base_image}
COPY lane.patch /tmp/lane.patch
WORKDIR /workspace/repo
RUN git apply --ignore-whitespace /tmp/lane.patch || git apply --3way /tmp/lane.patch \\
    && git -c user.email=farm@local -c user.name=farm add -A \\
    && git -c user.email=farm@local -c user.name=farm commit -qm "lane work so far"
""")
    r = subprocess.run(["docker", "build", "-q", "-t", tag, str(ctx)],
                       capture_output=True, text=True)
    return tag if r.returncode == 0 else None


def combine(image: str, base_sha: str, patch_dir: Path, names: list[str],
            dest: Path) -> int:
    """One patch for the lane: its original work plus whatever the repair added."""
    applies = " && ".join(
        f'(git apply --ignore-whitespace /patches/{n} || git apply --3way /patches/{n})'
        for n in names)
    script = (f"cd /workspace/repo && {applies} && git add -A >/dev/null 2>&1; "
              f"git diff --binary {base_sha}")
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{patch_dir}:/patches:ro",
                        "--entrypoint", "bash", image, "-lc", script],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return 0
    dest.write_text(r.stdout)
    return len(r.stdout.splitlines())


def flags_from(merge: dict | None, conv: dict, merged_outcome: str | None) -> list[str]:
    out: list[str] = []
    if merge and merge.get("outcome") == "conflict":
        out.append("git cannot merge your branch with the other one; the "
                   f"conflict is in {', '.join(merge.get('conflicted_paths') or [])}")
    for hit in conv.get("migration_ordinals", []):
        out.append(f"another branch also added migration ordinal {hit['ordinal']}")
    for hit in conv.get("route_paths", []):
        out.append(f"another branch also registered the route `{hit['path']}`")
    for hit in conv.get("config_keys", []):
        out.append(f"another branch also defined the config key `{hit['key']}`")
    if merged_outcome == "fail":
        out.append("the two branches merge cleanly but the combined tree fails "
                   "the repository's own checks")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--cooperbench-dir", default="/home/user/work/CooperBench")
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--lane-ceiling", type=float, default=0.9)
    ap.add_argument("--agent-config", default=str(REPO_ROOT / "config" / "agent_config_field.yaml"))
    ap.add_argument("--agent-timeout", type=int, default=2400)
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    cb = Path(args.cooperbench_dir)
    root = Path(args.data_root)
    root.mkdir(parents=True, exist_ok=True)
    consumer = Path(plan["consumer_checkout"])
    idx = build_index(consumer)

    start = settled_usage()
    if start is None:
        log("FATAL: provider meter unreadable; refusing to spend blind")
        return 2
    log(f"meter at start ${start:.4f}; cap ${args.cap_usd:.2f} billed, "
        f"lane ceiling ${args.lane_ceiling:.2f}")
    reserve = Reserve(cap_usd=args.cap_usd, floor_usd=args.lane_ceiling)
    ledger: list[dict] = []
    base_sha = image_base_commit(plan["image_canonical"])

    for ep in plan["episodes"]:
        out = root / ep["id"]
        patches = out / "patches"
        patches.mkdir(parents=True, exist_ok=True)
        # Each pair is its own task id and so its own image tag; grading and
        # the repair retag must use the episode's tag, not a plan-wide one.
        ep_image = ep.get("image", plan["image"])
        log(f"=== {ep['id']}  arm={ep['arm']}  ({ep['title']})")

        room = ""
        if ep["arm"] == "roomed":
            room = build_room(consumer, ep["room_targets"], index=idx)
            (out / "room.md").write_text(room)

        aborted = None
        for lane in ep["lanes"]:
            dest = patches / f"{lane['id']}.patch"
            if dest.exists() and dest.stat().st_size > 0:
                log(f"    {lane['id']}: reusing the patch already on disk")
                continue
            spent = (account_usage() or start) - start
            ok, why = reserve.may_start(spent)
            if not ok:
                aborted = f"stopping before {ep['id']}/{lane['id']}: {why}"
                log(f"    STOPPING: {aborted}")
                break
            brief = (REPO_ROOT / lane["brief"]).read_text() + room
            install_brief(cb, plan["repo"], ep["task_id"], lane["feature"], brief)
            log(f"    {lane['id']}: {plan['model']} (${spent:.4f} spent)")
            lane_start = account_usage() or start
            with LaneWatchdog(ceiling_usd=args.lane_ceiling, start_usd=lane_start,
                              base_commit=base_sha, dest=dest) as dog:
                log_dir = run_solo(cb, plan["repo"], ep["task_id"], lane["feature"],
                                   plan["model"], f"{plan['plan']}-{ep['id']}-{lane['id']}",
                                   out / "logs", Path(args.agent_config),
                                   args.agent_timeout)
            src = log_dir / "solo.patch"
            if src.exists() and src.stat().st_size > 0:
                shutil.copy2(src, dest)
            for extra in ("solo_traj.json", "result.json"):
                if (log_dir / extra).exists():
                    shutil.copy2(log_dir / extra, out / f"{lane['id']}_{extra}")
            after = settled_usage() or start
            cost = after - lane_start
            reserve.observe(cost)
            ledger.append({"episode": ep["id"], "arm": ep["arm"], "lane": lane["id"],
                           "phase": "initial", "lane_cost": round(cost, 4),
                           "ceiling_tripped": dog.tripped,
                           "salvaged_lines": dog.salvaged_lines,
                           "spent_total": round(after - start, 4)})
            log(f"    {lane['id']} done; lane ${cost:.4f}"
                + (f", salvaged {dog.salvaged_lines} lines" if dog.tripped else ""))
        if aborted:
            write_json(out / "aborted.json", {"why": aborted})
            break

        def grade(tag: str) -> dict:
            present = [l for l in ep["lanes"]
                       if (patches / f"{l['id']}.patch").exists()
                       and (patches / f"{l['id']}.patch").stat().st_size > 0]
            alone = {}
            for l in present:
                o, d = suite(ep_image, patches, [f"{l['id']}.patch"])
                alone[l["id"]] = o
                write_json(out / "results" / f"{tag}_alone_{l['id']}.json",
                           {"outcome": o, "detail": d})
            merge = merged = None
            if len(present) >= 2:
                rep = merge_lanes(ep_image, patches,
                                  [(l["id"], f"{l['id']}.patch") for l in present],
                                  out_dir=out / f"merge_{tag}")
                merge = rep.to_dict()
                if rep.outcome == "clean":
                    merged, d = suite(ep_image, patches,
                                      [f"{l['id']}.patch" for l in present])
                    write_json(out / "results" / f"{tag}_merged.json",
                               {"outcome": merged, "detail": d})
            branches = {l["id"]: (patches / f"{l['id']}.patch").read_text()
                        for l in present}
            conv = conventions.grade(branches)
            facts = {k: parse_patch(v) for k, v in branches.items()}
            pairs = []
            ids = sorted(facts)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    pairs.append({"lanes": [a, b],
                                  "overlap_class": classify_overlap(facts[a], facts[b], idx),
                                  "chain": semantic_link(facts[a], facts[b], idx)})
            g = {"alone": alone, "merge": merge, "merged": merged,
                 "conventions": conv, "claim_pairs": pairs,
                 "lanes_present": [l["id"] for l in present]}
            write_json(out / "results" / f"{tag}_grade.json", g)
            return g

        graded = grade("initial")
        flags = flags_from(graded["merge"], graded["conventions"], graded["merged"])
        repaired = False

        if ep["arm"] == "roomed" and flags and not aborted:
            log(f"    engine flagged: {flags}")
            for lane in ep["lanes"]:
                lane_patch = patches / f"{lane['id']}.patch"
                if not lane_patch.exists() or lane_patch.stat().st_size == 0:
                    continue
                spent = (account_usage() or start) - start
                ok, why = reserve.may_start(spent)
                if not ok:
                    aborted = f"stopping before repair of {lane['id']}: {why}"
                    log(f"    STOPPING: {aborted}")
                    break
                tag = f"conetic-farm/c06-repair-{ep['id']}-{lane['id']}:local".lower()
                img = repair_image(ep_image, lane_patch, tag)
                if img is None:
                    log(f"    repair image failed for {lane['id']}; skipping")
                    continue
                brief = ((REPO_ROOT / lane["brief"]).read_text() + room
                         + "\n## The integration check flagged this\n\n"
                         + "\n".join(f"* {f}" for f in flags)
                         + "\n\nFix it inside your own branch. Keep the feature you "
                           "built; change only what the flag is about, and say in "
                           "one line what you changed and why.\n")
                install_brief(cb, plan["repo"], ep["task_id"], lane["feature"], brief)
                log(f"    repair {lane['id']}")
                lane_start = account_usage() or start
                repair_dest = patches / f"{lane['id']}_repair.patch"
                # The repair runs on an image whose HEAD already carries the
                # lane's work, so its own diff is only the delta.
                subprocess.run(["docker", "tag", img, ep_image], check=True)
                try:
                    with LaneWatchdog(ceiling_usd=args.lane_ceiling,
                                      start_usd=lane_start, base_commit=None,
                                      dest=repair_dest) as dog:
                        log_dir = run_solo(cb, plan["repo"], ep["task_id"],
                                           lane["feature"], plan["model"],
                                           f"{plan['plan']}-{ep['id']}-{lane['id']}-repair",
                                           out / "logs", Path(args.agent_config),
                                           args.agent_timeout)
                finally:
                    subprocess.run(["docker", "tag", plan["image_canonical"],
                                    ep_image], check=True)
                src = log_dir / "solo.patch"
                if src.exists() and src.stat().st_size > 0:
                    shutil.copy2(src, repair_dest)
                    lines = combine(img, base_sha, patches,
                                    [f"{lane['id']}_repair.patch"],
                                    patches / f"{lane['id']}.patch")
                    log(f"    repair {lane['id']}: combined patch {lines} lines")
                    repaired = True
                after = settled_usage() or start
                cost = after - lane_start
                reserve.observe(cost)
                ledger.append({"episode": ep["id"], "arm": ep["arm"],
                               "lane": lane["id"], "phase": "repair",
                               "lane_cost": round(cost, 4),
                               "spent_total": round(after - start, 4)})
            if repaired:
                graded = grade("after_repair")
                flags = flags_from(graded["merge"], graded["conventions"],
                                   graded["merged"])

        merge_outcome = graded["merge"]["outcome"] if graded["merge"] else None
        if merge_outcome == "conflict":
            failure_class = "textual"
        elif merge_outcome == "clean" and graded["merged"] == "fail":
            failure_class = "semantic"
        else:
            failure_class = None
        alone = graded["alone"]
        both_pass = (len(alone) == len(ep["lanes"])
                     and all(o == "pass" for o in alone.values()))
        stealth = {"flag": None, "measured": True,
                   "why": "not applicable: the merge is not clean"}
        if merge_outcome == "clean":
            if failure_class == "semantic" and both_pass:
                stealth = {"flag": True, "measured": True,
                           "why": "clean merge, every lane green alone, combined "
                                  "tree wrong"}
            elif failure_class == "semantic":
                stealth = {"flag": False, "measured": True,
                           "why": "a lane is red on its own branch, so it was "
                                  "catchable before any merge"}
            else:
                stealth = {"flag": None, "measured": True,
                           "why": "not applicable: the combined tree is not broken"}

        ep_ledger = [e for e in ledger if e["episode"] == ep["id"]]
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": ep["id"], "split": "train",
            "corpus": {"name": plan["corpus"], "repo": plan["repo"],
                       "base_commit": plan["base_commit"], "language": "typescript",
                       "arm": ep["arm"]},
            "seam": {"kind": "same_repository_two_lanes",
                     "detail": "two lanes, own containers, own branches, no "
                               "channel; the briefs ask for different features "
                               "of the same kind on the same table"},
            "lanes": [{"agent": l["id"], "model": plan["model"],
                       "runtime": "cooperbench solo: own container, own branch, "
                                  "no mailbox, no shared git remote"
                                  + (" ; roomed brief from the claim map"
                                     if ep["arm"] == "roomed" else ""),
                       "brief": l["brief"], "assumptions": [],
                       "alone_suite": alone.get(l["id"])}
                      for l in ep["lanes"]],
            "git_outcome": graded["merge"] or {"outcome": None,
                                               "why": "fewer than two lanes produced a patch"},
            "product_outcome": {"per_lane_alone": alone,
                                "merged_suite": graded["merged"],
                                "both_pass": both_pass,
                                "checks": "tsc --noEmit and vitest run"},
            "failure_class": failure_class,
            "stealth": stealth,
            "claim": {"pairs": graded["claim_pairs"],
                      "room_used": ep["arm"] == "roomed",
                      "room": str(out / "room.md") if room else None},
            "convention_graders": {
                "migration_ordinals": graded["conventions"]["migration_ordinals"],
                "route_paths": graded["conventions"]["route_paths"],
                "config_keys": graded["conventions"]["config_keys"],
                "per_lane": graded["conventions"]["per_lane"],
            },
            "published_surface": {"published": None,
                                  "why": "both lanes are inside one application; "
                                         "no package boundary is crossed"},
            "cost": {"usd": round(sum(e["lane_cost"] for e in ep_ledger), 4),
                     "source": "provider meter deltas per lane",
                     "ledger": ep_ledger},
            "prediction": {"frozen": plan["predictions"][ep["arm"]],
                           "observed": {"both_pass": both_pass,
                                        "own_tests": alone,
                                        "failure_class": failure_class},
                           "correct": None, "source": args.plan},
            "patches": {l["id"]: str(patches / f"{l['id']}.patch")
                        for l in ep["lanes"]
                        if (patches / f"{l['id']}.patch").exists()},
            "merge": {"dir": str(out / "merge_initial"), "outcome": merge_outcome},
            "test_logs": {"dir": str(out / "results")},
            "checkpoints": {"dir": None,
                            "why": "solo runs keep no cross-agent checkpoint stream"},
            "repair": {"offered": ep["arm"] == "roomed", "ran": repaired,
                       "flags_before": flags_from(graded["merge"],
                                                  graded["conventions"],
                                                  graded["merged"]) if not repaired else None,
                       "flags_after": flags if repaired else None},
        }
        write_episode(record)
        write_json(out / "episode.json", record)
        log(f"    -> arm={ep['arm']} class={failure_class} both_pass={both_pass} "
            f"alone={alone} hits="
            + str({k: len(graded['conventions'][k]) for k in
                   ('migration_ordinals', 'route_paths', 'config_keys')}))

    final = settled_usage() or start
    write_json(root / "spend.json", {"meter_start": start, "meter_end": final,
                                     "spent": final - start, "cap_usd": args.cap_usd,
                                     "ledger": ledger})
    log(f"done; ${final - start:.4f} spent of ${args.cap_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
