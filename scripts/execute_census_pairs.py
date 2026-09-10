#!/usr/bin/env python3
"""Run the census's merge-clean pairs and find out whether their tests catch it.

`farm/census/claim_grade.jsonl` bounded what the tests *could* observe: 67 of
147 pairs have a one-edge directed chain and a test naming a changed definition
on each side. Bounding is not measuring. This applies the patches and runs the
suite.

Three runs decide a pair, and the middle one is why the count can be trusted:

    base      the suite at the pinned commit. A task whose base is red makes
              every pair under it unreadable, and that is reported rather than
              quietly dropped.
    lane      base plus ONE feature patch. Cached per feature, because a task
              with 10 features has 45 pairs and 10 lanes.
    merged    the two lane commits merged, both graded test patches applied
              where they apply.

`farm.failure_class.classify` then decides, with the same rule the campaigns
use: `semantic` needs a clean merge, every lane green alone, and a red merged
tree. A merged tree that fails while a lane was already red is not an
integration failure and is counted separately.

One thing this cannot decide and does not pretend to. A CooperBench task is one
pull request cut into N features, so a pair of them may reference a symbol that
a third, unapplied feature defines. That failure is an artifact of the cutting,
not two authors disagreeing, and every hit needs reading before it is counted.
The record carries the failing output so that reading is possible.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.failure_class import classify                      # noqa: E402

STAMP = {
    "GIT_AUTHOR_NAME": "conetic-farm census",
    "GIT_AUTHOR_EMAIL": "census@conetic-farm.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "conetic-farm census",
    "GIT_COMMITTER_EMAIL": "census@conetic-farm.invalid",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}
TAIL = 4000          # of failing output kept, so a hit can be read later


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git(root: Path, *args: str, check: bool = True, env: dict | None = None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=check, env=e)


def clone(url: str, dest: Path) -> bool:
    for attempt in (1, 2, 3):
        try:
            subprocess.run(["git", "clone", "--filter=blob:none", "--no-tags",
                            "--quiet", url, str(dest)], check=True, timeout=1800)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            log(f"    clone attempt {attempt} failed: {e}")
            shutil.rmtree(dest, ignore_errors=True)
            time.sleep(2 ** attempt)
    return False


def apply_patch(root: Path, patch: Path) -> bool:
    for extra in (["--ignore-whitespace"], ["--3way"]):
        if git(root, "apply", *extra, str(patch), check=False).returncode == 0:
            return True
    return False


def commit_all(root: Path, parent: str, message: str) -> str:
    git(root, "add", "-A")
    tree = git(root, "write-tree").stdout.strip()
    return git(root, "commit-tree", tree, "-p", parent, "-m", message,
               env=STAMP).stdout.strip()


def run_suite(root: Path, cmd: str, timeout: int) -> dict:
    """Green, red, or unusable, with the tail kept when it is not green."""
    started = time.time()
    try:
        r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "seconds": round(time.time() - started, 1),
                "tail": f"exceeded {timeout}s"}
    out = (r.stdout or "") + (r.stderr or "")
    return {"outcome": "pass" if r.returncode == 0 else "fail",
            "returncode": r.returncode,
            "seconds": round(time.time() - started, 1),
            "tail": "" if r.returncode == 0 else out[-TAIL:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", required=True,
                    help="JSON: {repo: {setup_commands: [...], test_command: str}}")
    ap.add_argument("--grade", default=str(REPO_ROOT / "farm" / "census" / "claim_grade.jsonl"))
    ap.add_argument("--dataset", default="/home/user/work/CooperBench/dataset")
    ap.add_argument("--manifest",
                    default=str(REPO_ROOT / "farm" / "census" / "manifest.jsonl"))
    ap.add_argument("--out", default=str(REPO_ROOT / "farm" / "census" / "execution.jsonl"))
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--only-repo", action="append", default=None)
    ap.add_argument("--suite-timeout", type=int, default=900)
    args = ap.parse_args()

    envs = json.loads(Path(args.envs).read_text())
    rows = [json.loads(l) for l in Path(args.grade).read_text().splitlines()]
    # The lane commits the manifest recorded, joined in by pair, so the canary
    # below has something to compare against.
    manifest = {}
    mpath = Path(args.manifest)
    if mpath.exists():
        for line in mpath.read_text().splitlines():
            m = json.loads(line)
            manifest[(m["repo"], m["task"], tuple(m["features"]))] = m
    for r in rows:
        m = manifest.get((r["repo"], r["task"], tuple(r["features"])))
        if m:
            r["lane_sha"] = m.get("lane_sha")
            r.setdefault("upstream", m.get("upstream"))
    dataset = Path(args.dataset)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)

    written: list[str] = []
    done: set[str] = set()
    if out.exists():
        written = [l for l in out.read_text().splitlines() if l.strip()]
        have: dict[str, int] = defaultdict(int)
        for l in written:
            have[json.loads(l)["repo"]] += 1
        done = {r for r, n in have.items() if n == len(by_repo.get(r, []))}
        written = [l for l in written if json.loads(l)["repo"] in done]
        if done:
            log(f"resuming; complete: {sorted(done)}")

    for repo, pairs in sorted(by_repo.items()):
        if args.only_repo and repo not in args.only_repo:
            continue
        if repo in done or repo not in envs:
            if repo not in envs:
                log(f"{repo}: no environment recorded; skipping {len(pairs)} pair(s)")
            continue
        env = envs[repo]
        checkout = work / repo
        # The environment lives OUTSIDE the checkout, and this is not tidiness.
        # A venv inside the repository is untracked, `git add -A` stages it --
        # jinja's .gitignore covers `venv/` and not `.venv/` -- the lane commit
        # then contains it, and the next `git checkout --force base` deletes it
        # as a file the target commit does not have. The first jinja run lost
        # its interpreter after the first lane and scored all 64 pairs off
        # `/bin/sh: .venv/bin/python: not found`, which the harness faithfully
        # recorded as "the lane is red on its own branch".
        venv = work / f"{repo}.venv"
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: cloning for {len(pairs)} pair(s)")
        if not clone(pairs[0].get("upstream") or env["url"], checkout):
            log(f"{repo}: clone failed")
            continue

        rows_for_repo: list[str] = []
        for task in sorted({p["task"] for p in pairs}):
            group = [p for p in pairs if p["task"] == task]
            task_dir = dataset / repo / task
            base = group[0]["base_sha"]
            git(checkout, "checkout", "--quiet", "--force", base)
            git(checkout, "clean", "-qfdx", check=False)

            # A base commit is only readable under a toolchain contemporary
            # with it, and "contemporary" differs by repository: jinja's base
            # is green under a current pytest and red under 7.x, click's two
            # tasks are the exact opposite -- a 2026 pytest turns their
            # parametrize deprecations into collection errors. Rather than
            # pick per repository by hand and hope, try each variant and let
            # the BASELINE decide, then record which one was used.
            variants = env.get("setup_variants") or [
                {"name": "default", "setup_commands": env["setup_commands"]}]
            setup_ok, setup_err, baseline, chosen = False, "", None, None
            for variant in variants:
                shutil.rmtree(venv, ignore_errors=True)
                ok, err = True, ""
                for cmd in variant["setup_commands"]:
                    r = subprocess.run(cmd.format(venv=venv), shell=True,
                                       cwd=checkout, capture_output=True,
                                       text=True, timeout=2400)
                    if r.returncode != 0:
                        ok = False
                        err = ((r.stdout or "") + (r.stderr or ""))[-TAIL:]
                        break
                if not ok:
                    setup_err = err
                    continue
                probe = run_suite(checkout, env["test_command"].format(venv=venv),
                                  args.suite_timeout)
                log(f"  {repo}/{task}: baseline {probe['outcome']} in "
                    f"{probe['seconds']}s under '{variant['name']}'")
                setup_ok, baseline, chosen = True, probe, variant["name"]
                if probe["outcome"] == "pass":
                    break
            if not setup_ok:
                log(f"  {repo}/{task}: environment failed; {len(group)} pair(s) unreadable")
                for p in group:
                    rows_for_repo.append(json.dumps(
                        {**{k: p[k] for k in ("repo", "task", "features", "base_sha",
                                              "head_sha", "label")},
                         "executed": False, "why": "environment build failed",
                         "setup_tail": setup_err}, sort_keys=True))
                continue

            baseline = {**baseline, "toolchain": chosen}

            # One lane run per feature, shared by every pair that names it.
            lane_cache: dict[int, dict] = {}
            lane_sha_expected: dict[int, str] = {}
            for p in group:
                for fid, sha in (p.get("lane_sha") or {}).items():
                    if sha:
                        lane_sha_expected[int(fid)] = sha

            def lane(fid: int) -> dict:
                if fid in lane_cache:
                    return lane_cache[fid]
                git(checkout, "checkout", "--quiet", "--force", base)
                git(checkout, "clean", "-qfdx", check=False)
                fp = task_dir / f"feature{fid}" / "feature.patch"
                if not apply_patch(checkout, fp):
                    lane_cache[fid] = {"sha": None, "suite": None,
                                       "why": "feature.patch does not apply to base"}
                    return lane_cache[fid]
                sha = commit_all(checkout, base, f"census lane: base + feature{fid}")
                # The canary. These commits are deterministic and the manifest
                # recorded them; a mismatch means the tree holds something the
                # manifest's did not, which is how the venv got in last time.
                expected = lane_sha_expected.get(fid)
                if expected and sha != expected:
                    raise SystemExit(
                        f"FATAL {repo}/{task} feature{fid}: lane commit {sha[:12]} "
                        f"does not match the manifest's {expected[:12]}. The "
                        f"working tree contains something it should not; "
                        f"refusing to score a contaminated run.")
                tp = task_dir / f"feature{fid}" / "tests.patch"
                tests_applied = bool(tp.exists() and apply_patch(checkout, tp))
                suite = run_suite(checkout, env["test_command"].format(venv=venv),
                                  args.suite_timeout)
                lane_cache[fid] = {"sha": sha, "suite": suite,
                                   "tests_patch_applied": tests_applied}
                return lane_cache[fid]

            for p in group:
                f1, f2 = p["features"]
                row = {k: p[k] for k in ("repo", "task", "features", "base_sha",
                                         "head_sha", "label")}
                row["executed"] = True
                row["baseline"] = baseline
                row["toolchain"] = chosen
                # Lanes only matter if the base is green. Running them anyway
                # cost dspy a full suite per lane to reach a verdict the
                # baseline had already decided.
                green = baseline["outcome"] == "pass"
                l1, l2 = (lane(f1), lane(f2)) if green else ({}, {})
                row["lanes"] = {str(f1): l1, str(f2): l2} if green else {}
                if not green:
                    row.update(verdict=None,
                               why="the base commit is not green, so nothing "
                                   "under this task can be read")
                    rows_for_repo.append(json.dumps(row, sort_keys=True))
                    continue
                if not (l1["sha"] and l2["sha"]):
                    row.update(verdict=None, why="a lane patch does not apply")
                    rows_for_repo.append(json.dumps(row, sort_keys=True))
                    continue

                git(checkout, "checkout", "--quiet", "--force", l1["sha"])
                merged = git(checkout, "merge", "--no-edit", "--no-ff", l2["sha"],
                             check=False, env=STAMP)
                if merged.returncode != 0:
                    git(checkout, "merge", "--abort", check=False)
                    row.update(merge="conflict", verdict=None,
                               why="git refuses the merge here, though the "
                                   "manifest recorded it as clean")
                    rows_for_repo.append(json.dumps(row, sort_keys=True))
                    continue
                head = git(checkout, "rev-parse", "HEAD").stdout.strip()
                # Both graded test patches, or the pair cannot be scored.
                #
                # A feature's tests.patch is the other half of its feature.patch:
                # click task2800's feature6 adds `import copy` to the source AND
                # adds "copy" to ALLOWED_IMPORTS in tests/test_imports.py, which
                # is the test that polices click's import cost. Apply the source
                # half without the test half and test_light_imports fails --
                # every time, for reasons that have nothing to do with the other
                # lane. That produced five "semantic failures" in this repository
                # on the first run, all of them this.
                #
                # The patches often touch the same test file, so order decides
                # who applies; try both before concluding they cannot coexist.
                wanted = [fid for fid in (f1, f2)
                          if (task_dir / f"feature{fid}" / "tests.patch").exists()]
                applied, order_used = [], None
                for order in ([f1, f2], [f2, f1]):
                    git(checkout, "checkout", "--quiet", "--force", head)
                    git(checkout, "clean", "-qfdx", check=False)
                    got = [fid for fid in order
                           if fid in wanted
                           and apply_patch(checkout,
                                           task_dir / f"feature{fid}" / "tests.patch")]
                    if len(got) > len(applied):
                        applied, order_used = got, order
                    if len(applied) == len(wanted):
                        break
                if len(applied) < len(wanted):
                    row.update(merge="clean",
                               head_sha_reproduced=head == p["head_sha"],
                               tests_patches_applied=applied,
                               tests_patches_wanted=wanted,
                               verdict=None,
                               why="the two graded test patches cannot both be "
                                   "applied to the merged tree, so the combined "
                                   "tree would be judged against test "
                                   "expectations that contradict the code it "
                                   "contains")
                    rows_for_repo.append(json.dumps(row, sort_keys=True))
                    git(checkout, "checkout", "--quiet", "--force", base)
                    git(checkout, "clean", "-qfdx", check=False)
                    continue
                combined = run_suite(checkout, env["test_command"].format(venv=venv),
                                     args.suite_timeout)
                every_lane_green = (l1["suite"]["outcome"] == "pass"
                                    and l2["suite"]["outcome"] == "pass")
                cls, why = classify("clean", combined["outcome"], every_lane_green)
                row.update(merge="clean",
                           head_sha_reproduced=head == p["head_sha"],
                           tests_patches_applied=applied,
                           tests_patches_wanted=wanted,
                           tests_patch_order=order_used,
                           combined=combined,
                           every_lane_green=every_lane_green,
                           verdict=cls, why=why)
                if cls == "semantic":
                    log(f"    SEMANTIC: {repo}/{task} f{f1}+f{f2}")
                rows_for_repo.append(json.dumps(row, sort_keys=True))
                git(checkout, "checkout", "--quiet", "--force", base)
                git(checkout, "clean", "-qfdx", check=False)

        written.extend(rows_for_repo)
        out.write_text("\n".join(written) + "\n")
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: {len(rows_for_repo)} row(s) written; total {len(written)}")

    log(f"done: {len(written)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
