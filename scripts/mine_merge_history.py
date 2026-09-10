#!/usr/bin/env python3
"""Method A: a two-parent merge commit already holds the experiment.

CooperBench is closed for the semantic class -- its pairs come from one pull
request and are co-authored. Real history is not. And it needs no CI status and
no API to read, because a merge commit records the whole thing:

    parent 1   main, immediately before the merge
    parent 2   the pull request branch, exactly as its author wrote it
    the merge  both, together, for the first time

Run all three. Both parents green and the merge red is a coordination failure
between two changes whose authors never saw each other -- measured here rather
than trusted from a badge that may no longer exist. Then walk forward from the
red merge until main is green again: that commit is the fix, and the fix is the
ground truth for what the interaction was.

What this cannot tell you, and reports instead of hiding:

* a merge that is red *today* may have been green when it landed. Dependency
  drift moves under old commits. That is why the FIRST PARENT is run under the
  same toolchain on the same day: if the parent is red too, the redness is the
  environment and the merge says nothing.
* a repository that squash-merges has no second parent. The experiment was
  discarded at merge time and no amount of walking recovers it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TAIL = 3000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git(root: Path, *args: str, check: bool = True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=check)


def run_suite(root: Path, cmd: str, timeout: int) -> dict:
    started = time.time()
    try:
        r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "seconds": round(time.time() - started, 1), "tail": ""}
    out = (r.stdout or "") + (r.stderr or "")
    return {"outcome": "pass" if r.returncode == 0 else "fail",
            "seconds": round(time.time() - started, 1),
            "tail": "" if r.returncode == 0 else out[-TAIL:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path to a clone on its default branch")
    ap.add_argument("--name", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--setup", action="append", required=True)
    ap.add_argument("--test-command", required=True)
    ap.add_argument("--since", default="12 months ago")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--suite-timeout", type=int, default=600)
    args = ap.parse_args()

    root = Path(args.repo)
    venv = Path(args.venv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    merges = []
    for line in git(root, "log", f"--since={args.since}", "--merges",
                    "--pretty=%H\t%P\t%ct\t%s").stdout.splitlines():
        sha, parents, when, subject = line.split("\t", 3)
        ps = parents.split()
        if len(ps) == 2:
            merges.append({"sha": sha, "p1": ps[0], "p2": ps[1],
                           "when": int(when), "subject": subject})
    merges.reverse()               # oldest first, so a fix walk goes forwards
    if args.limit:
        merges = merges[-args.limit:]
    log(f"{args.name}: {len(merges)} two-parent merges since {args.since}")

    for cmd in args.setup:
        r = subprocess.run(cmd.format(venv=venv), shell=True, cwd=root,
                           capture_output=True, text=True, timeout=2400)
        if r.returncode != 0:
            log(f"setup failed: {cmd}\n{(r.stdout + r.stderr)[-800:]}")
            return 1

    cache: dict[str, dict] = {}

    def suite_at(sha: str) -> dict:
        if sha in cache:
            return cache[sha]
        git(root, "checkout", "--quiet", "--force", sha)
        git(root, "clean", "-qfdx", check=False)
        cache[sha] = run_suite(root, args.test_command.format(venv=venv),
                               args.suite_timeout)
        return cache[sha]

    rows, hits = [], 0
    for i, m in enumerate(merges, 1):
        p1 = suite_at(m["p1"])
        row = {"repo": args.name, "merge": m["sha"], "p1": m["p1"], "p2": m["p2"],
               "when": m["when"], "subject": m["subject"],
               "p1_suite": p1["outcome"], "p1_seconds": p1["seconds"]}
        if p1["outcome"] != "pass":
            # Main was already red under today's toolchain. Nothing about this
            # merge is readable, and saying so is the point of running it.
            row.update(verdict=None, why="main was already red before the merge, "
                                         "under the toolchain used here")
            rows.append(row)
            continue
        p2 = suite_at(m["p2"])
        row.update(p2_suite=p2["outcome"], p2_seconds=p2["seconds"])
        if p2["outcome"] != "pass":
            row.update(verdict=None, why="the pull request branch is red on its "
                                         "own, so the merge is not an interaction")
            rows.append(row)
            continue
        mm = suite_at(m["sha"])
        row.update(merge_suite=mm["outcome"], merge_seconds=mm["seconds"])
        if mm["outcome"] == "pass":
            row.update(verdict=None, why="both parents green and the merge green")
            rows.append(row)
            continue
        row.update(verdict="coordination_failure",
                   why="both parents green on their own and the merge red: two "
                       "independently authored changes that disagree",
                   merge_tail=mm["tail"])
        hits += 1
        log(f"  HIT {m['sha'][:10]} {m['subject'][:60]}")
        rows.append(row)
        if i % 10 == 0:
            out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
            log(f"  {i}/{len(merges)} merges, {hits} hit(s)")

    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    log(f"done: {len(rows)} merges examined, {hits} coordination failure(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
