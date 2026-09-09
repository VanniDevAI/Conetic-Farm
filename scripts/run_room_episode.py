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
from farm.failure_class import classify as classify_failure       # noqa: E402
from farm.failure_class import stealth as stealth_flag            # noqa: E402
from farm.grade import run_cmd                                    # noqa: E402
from farm.identity import build_index                             # noqa: E402
from farm.lane_budget import (LaneWatchdog, Reserve,               # noqa: E402
                              image_base_commit, salvage_live_lanes)
from farm.nway_merge import merge_lanes                           # noqa: E402
from farm.overlap import classify_overlap, parse_patch, semantic_link  # noqa: E402
from farm.provider import account_usage, settled_usage            # noqa: E402
from farm.room_brief import build as build_room                   # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def changed_lines(patch: Path) -> int:
    """Added and removed lines, not the diff's own headers."""
    if not patch.exists():
        return 0
    return sum(1 for line in patch.read_text(errors="replace").splitlines()
               if line[:1] in ("+", "-") and not line.startswith(("+++", "---")))


def patch_was_salvaged(log_dir: Path) -> bool:
    """True when the lane published nothing and its working tree was graded.

    Set by the vendored adapter (docs/HARNESS_NOTES.md 16). A salvaged patch is
    real work and is graded like any other, but it says the lane never ran a
    git command, which is a different thing from a lane that pushed.
    """
    res = log_dir / "result.json"
    if not res.exists():
        return False
    try:
        return bool(json.loads(res.read_text())["agent"].get("patch_salvaged"))
    except (json.JSONDecodeError, KeyError):
        return False


# How the room is joined to the task, stated per plan rather than assumed.
# c06 and c06b appended it, so the last thing a roomed agent read was the room's
# closing "only then start editing" -- and roomed lanes skipped the submit step
# at 5 of 12 against bare's 1 of 12. The default is now the other way round:
# facts first, task last, so the working agreement is what the prompt ends on.
ROOM_DEFAULTS = {"placement": "before_brief", "closing_protocol": False}


def assemble(brief_path: str, room: str, cfg: dict) -> str:
    """The prompt a lane sees: the task, and the room on the configured side."""
    brief = (REPO_ROOT / brief_path).read_text()
    if not room:
        return brief
    return (room + "\n" + brief if cfg["placement"] == "before_brief"
            else brief + room)


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
    room_cfg = {**ROOM_DEFAULTS, **plan.get("room", {})}
    consumer = Path(plan["consumer_checkout"])
    idx = build_index(consumer)

    start = settled_usage()
    if start is None:
        log("FATAL: provider meter unreadable; refusing to spend blind")
        return 2
    log(f"meter at start ${start:.4f}; cap ${args.cap_usd:.2f} billed, "
        f"lane ceiling ${args.lane_ceiling:.2f}")
    log(f"room: {room_cfg['placement']}, closing protocol "
        f"{'on' if room_cfg['closing_protocol'] else 'ABLATED'}")
    reserve = Reserve(cap_usd=args.cap_usd, floor_usd=args.lane_ceiling)
    ledger: list[dict] = []
    lane_facts: dict[tuple[str, str], dict] = {}
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
            room = build_room(consumer, ep["room_targets"], index=idx,
                              closing_protocol=room_cfg["closing_protocol"])
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
            brief = assemble(lane["brief"], room, room_cfg)
            install_brief(cb, plan["repo"], ep["task_id"], lane["feature"], brief)
            log(f"    {lane['id']}: {plan['model']} (${spent:.4f} spent)")
            lane_start = account_usage() or start
            timed_out = False
            salvaged_lines = 0
            with LaneWatchdog(ceiling_usd=args.lane_ceiling, start_usd=lane_start,
                              base_commit=base_sha, dest=dest) as dog:
                try:
                    log_dir = run_solo(cb, plan["repo"], ep["task_id"], lane["feature"],
                                       plan["model"],
                                       f"{plan['plan']}-{ep['id']}-{lane['id']}",
                                       out / "logs", Path(args.agent_config),
                                       args.agent_timeout)
                except subprocess.TimeoutExpired:
                    # A slow provider can carry a lane past the wall-clock limit.
                    # Take what the container has rather than losing the lane.
                    timed_out = True
                    salvaged_lines = salvage_live_lanes(base_sha, dest)
                    log(f"    {lane['id']}: wall-clock timeout; salvaged "
                        f"{salvaged_lines} lines from the container")
                    log_dir = (out / "logs" /
                               f"{plan['plan']}-{ep['id']}-{lane['id']}" / "solo" /
                               plan["repo"] / str(ep["task_id"]) / f"f{lane['feature']}")
            src = log_dir / "solo.patch"
            if src.exists() and src.stat().st_size > 0:
                shutil.copy2(src, dest)
            for extra in ("solo_traj.json", "result.json"):
                if (log_dir / extra).exists():
                    shutil.copy2(log_dir / extra, out / f"{lane['id']}_{extra}")
            # What the lane actually shipped, recorded per lane rather than
            # inferred later from a pass/fail. Grading the working tree means a
            # lane whose only change is a stray file now gets graded and passes
            # trivially; a rate that cannot tell that from a feature is not a
            # measurement, so the size sits beside it.
            lane_facts[(ep["id"], lane["id"])] = {
                "changed_lines": changed_lines(dest),
                "salvaged": patch_was_salvaged(log_dir),
                "run_position": ep.get("run_position"),
                "lane_position": [l["id"] for l in ep["lanes"]].index(lane["id"]) + 1,
            }
            after = settled_usage() or start
            cost = after - lane_start
            reserve.observe(cost)
            ledger.append({"episode": ep["id"], "arm": ep["arm"], "lane": lane["id"],
                           "phase": "initial", "lane_cost": round(cost, 4),
                           "ceiling_tripped": dog.tripped,
                           "wall_clock_timeout": timed_out,
                           # Both salvage paths, not only the ceiling's. The
                           # watchdog sets `dog.salvaged_lines` when it trips on
                           # cost; a wall-clock timeout salvages from a different
                           # call and left the watchdog's counter at zero, so the
                           # ledger read "salvaged 0" for the lane whose run log
                           # says 261.
                           "salvaged_lines": max(dog.salvaged_lines, salvaged_lines),
                           "spent_total": round(after - start, 4)})
            salvaged_lines = max(dog.salvaged_lines, salvaged_lines)
            log(f"    {lane['id']} done; lane ${cost:.4f}"
                + (f", salvaged {salvaged_lines} lines" if salvaged_lines else ""))
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
                brief = (assemble(lane["brief"], room, room_cfg)
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
                    # `combine` writes the lane's own patch file, which is the
                    # artifact `grade("initial")` scored. Keep a copy under its
                    # own name first, or the record points at a file that no
                    # longer holds what was graded.
                    shutil.copy2(patches / f"{lane['id']}.patch",
                                 patches / f"{lane['id']}_initial.patch")
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
        alone = graded["alone"]
        both_pass = (len(alone) == len(ep["lanes"])
                     and all(o == "pass" for o in alone.values()))
        failure_class, class_why = classify_failure(merge_outcome,
                                                    graded["merged"], both_pass)
        stealth = stealth_flag(failure_class, merge_outcome, both_pass)

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
                       "alone_suite": alone.get(l["id"]),
                       **lane_facts.get((ep["id"], l["id"]), {})}
                      for l in ep["lanes"]],
            "git_outcome": graded["merge"] or {"outcome": None,
                                               "why": "fewer than two lanes produced a patch"},
            "product_outcome": {"per_lane_alone": alone,
                                "merged_suite": graded["merged"],
                                "both_pass": both_pass,
                                "checks": "tsc --noEmit and vitest run"},
            "failure_class": failure_class,
            "failure_class_why": class_why,
            "stealth": stealth,
            "claim": {"pairs": graded["claim_pairs"],
                      "room_used": ep["arm"] == "roomed",
                      "room_cfg": room_cfg if ep["arm"] == "roomed" else None,
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
