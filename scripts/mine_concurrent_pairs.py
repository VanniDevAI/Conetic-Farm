#!/usr/bin/env python3
"""Method B: two changes written at the same time, replayed from where they started.

Method A can only see what survived to a merge commit, and a project that
requires a branch to be current before merging has already tested the
interaction before the merge button appears. That hygiene is exactly what an
agent lacks, so method A measures a condition that good projects remove.

This constructs it instead, from git alone and with no API.

Every pull-request branch has a merge-base with main: the commit its author
started from. For two merges M1 and M2:

    base1 = merge-base(main, p2 of M1)      where author 1 began
    base2 = merge-base(main, p2 of M2)      where author 2 began

If both branch points precede both merges, then while author 2 was writing,
author 1's work was not yet on main and vice versa. Neither saw the other. Take
the older of the two branch points as the common base, replay each branch's own
diff onto it as a lane, merge the lanes, and grade the combined tree.

The result is not what happened -- what happened is that somebody rebased. It is
what would have happened had neither author rebased, which is precisely the
position two agents are in.

Grading is `farm.failure_class.classify`, the same rule the campaigns use:
`semantic` needs a clean merge, every lane green alone, and a red combined tree.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.failure_class import classify        # noqa: E402
from farm.identity import build_index, reaches  # noqa: E402
from farm.overlap import changed_definitions, parse_patch  # noqa: E402

STAMP = {
    "GIT_AUTHOR_NAME": "conetic-farm history",
    "GIT_AUTHOR_EMAIL": "history@conetic-farm.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "conetic-farm history",
    "GIT_COMMITTER_EMAIL": "history@conetic-farm.invalid",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}
TAIL = 3000
DAY = 86400


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git(root: Path, *args: str, check: bool = True, env: dict | None = None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=check, env=e)


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


def branches(root: Path, since: str, default: str) -> list[dict]:
    """Every PR merge in the window, with where its author started."""
    out = []
    for line in git(root, "log", f"--since={since}", "--merges",
                    "--pretty=%H\t%P\t%ct\t%s").stdout.splitlines():
        sha, parents, when, subject = line.split("\t", 3)
        ps = parents.split()
        if len(ps) != 2:
            continue
        base = git(root, "merge-base", ps[0], ps[1], check=False).stdout.strip()
        if not base:
            continue
        files = git(root, "diff", "--name-only", base, ps[1], check=False).stdout.split()
        out.append({"merge": sha, "p1": ps[0], "tip": ps[1], "base": base,
                    "when": int(when), "subject": subject, "files": files})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--setup", action="append", required=True)
    ap.add_argument("--test-command", required=True)
    ap.add_argument("--since", default="12 months ago")
    ap.add_argument("--default-branch", default="main")
    ap.add_argument("--within-days", type=int, default=7)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pairs", type=int, default=60)
    ap.add_argument("--suite-timeout", type=int, default=600)
    args = ap.parse_args()

    root, venv, out = Path(args.repo), Path(args.venv), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs = branches(root, args.since, args.default_branch)
    log(f"{args.name}: {len(prs)} pull-request merges with a derivable branch point")

    # Concurrent: each author started before the other landed, and they landed
    # within the window of each other.
    cands = []
    for a, b in combinations(prs, 2):
        if abs(a["when"] - b["when"]) > args.within_days * DAY:
            continue
        a_base_when = int(git(root, "show", "-s", "--format=%ct", a["base"]).stdout.strip())
        b_base_when = int(git(root, "show", "-s", "--format=%ct", b["base"]).stdout.strip())
        if not (a_base_when <= b["when"] and b_base_when <= a["when"]):
            continue
        if set(a["files"]) & set(b["files"]):
            overlap = "shared_file"      # git would likely refuse; keep and record
        else:
            overlap = "disjoint_files"
        cands.append({"a": a, "b": b, "overlap": overlap,
                      "common_base": a["base"] if a_base_when <= b_base_when else b["base"]})
    log(f"{args.name}: {len(cands)} concurrent pair(s) within {args.within_days} days")
    cands = cands[:args.max_pairs]

    for cmd in args.setup:
        r = subprocess.run(cmd.format(venv=venv), shell=True, cwd=root,
                           capture_output=True, text=True, timeout=2400)
        if r.returncode != 0:
            log(f"setup failed: {cmd}\n{(r.stdout + r.stderr)[-600:]}")
            return 1

    idx_cache: dict[str, object] = {}
    suite_cache: dict[str, dict] = {}

    def at(sha: str) -> dict:
        if sha not in suite_cache:
            git(root, "checkout", "--quiet", "--force", sha)
            git(root, "clean", "-qfdx", check=False)
            suite_cache[sha] = run_suite(root, args.test_command.format(venv=venv),
                                         args.suite_timeout)
        return suite_cache[sha]

    def lane(base: str, tip: str, tag: str) -> tuple[str | None, str]:
        """base plus one branch's own diff, as a commit."""
        git(root, "checkout", "--quiet", "--force", base)
        git(root, "clean", "-qfdx", check=False)
        diff = git(root, "diff", "--binary", base, tip, check=False).stdout
        if not diff.strip():
            return None, "the branch has no diff against the common base"
        proc = subprocess.run(["git", "-C", str(root), "apply", "--3way", "-"],
                              input=diff, capture_output=True, text=True)
        if proc.returncode != 0:
            return None, "the branch's diff does not apply to the common base"
        git(root, "add", "-A")
        tree = git(root, "write-tree").stdout.strip()
        return git(root, "commit-tree", tree, "-p", base, "-m", f"lane {tag}",
                   env=STAMP).stdout.strip(), ""

    rows, semantic = [], 0
    for n, c in enumerate(cands, 1):
        a, b, base = c["a"], c["b"], c["common_base"]
        row = {"repo": args.name, "a_merge": a["merge"], "b_merge": b["merge"],
               "a_subject": a["subject"], "b_subject": b["subject"],
               "common_base": base, "overlap": c["overlap"],
               "a_files": a["files"][:20], "b_files": b["files"][:20]}
        bs = at(base)
        row["base_suite"] = bs["outcome"]
        if bs["outcome"] != "pass":
            row.update(verdict=None, why="the common base is not green under the "
                                         "toolchain used here")
            rows.append(row)
            continue
        la, why_a = lane(base, a["tip"], "a")
        lb, why_b = lane(base, b["tip"], "b")
        if not (la and lb):
            row.update(verdict=None, why=why_a or why_b)
            rows.append(row)
            continue
        sa, sb = at(la), at(lb)
        row.update(a_alone=sa["outcome"], b_alone=sb["outcome"])
        if sa["outcome"] != "pass" or sb["outcome"] != "pass":
            row.update(verdict=None, why="a lane is red on its own branch")
            rows.append(row)
            continue
        git(root, "checkout", "--quiet", "--force", la)
        merged = git(root, "merge", "--no-edit", "--no-ff", lb, check=False, env=STAMP)
        if merged.returncode != 0:
            paths = sorted({p for p in git(root, "diff", "--name-only",
                                           "--diff-filter=U", check=False)
                            .stdout.split() if p})
            git(root, "merge", "--abort", check=False)
            cls, why = classify("conflict", None, True)
            row.update(merge="conflict", conflicted_paths=paths, verdict=cls, why=why)
            rows.append(row)
            continue
        combined = run_suite(root, args.test_command.format(venv=venv), args.suite_timeout)
        cls, why = classify("clean", combined["outcome"], True)
        row.update(merge="clean", combined=combined["outcome"], verdict=cls, why=why)
        if cls == "semantic":
            semantic += 1
            row["combined_tail"] = combined["tail"]
            log(f"  SEMANTIC {a['merge'][:8]} + {b['merge'][:8]}: "
                f"{a['subject'][:40]} | {b['subject'][:40]}")
        rows.append(row)
        if n % 10 == 0:
            out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
            log(f"  {n}/{len(cands)} pairs, {semantic} semantic")

    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    log(f"done: {len(rows)} pair(s), {semantic} semantic -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
