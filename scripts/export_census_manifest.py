#!/usr/bin/env python3
"""Export the pair census as a manifest anyone can check against the sources.

`results/census_resolved.json` records what each of 652 pairs was classified as.
It does not record *what was measured*: the repository, the commit the sandbox
checks out, or the tree the pair's two gold patches produce. Without those a
label is an assertion. With them a reader can reconstruct either side of any
row and disagree with it.

One line per pair:

    repo        the CooperBench task family, and the upstream it clones
    base_sha    the commit the task image checks out, read from its Dockerfile
    head_sha    a real git commit: the base tree with both gold patches applied
    label       the resolved class, with the diff-only class beside it

`head_sha` needs a word, because the pair's head never existed upstream. The
two features of a pair come from one pull request and were never applied
together by anyone; the commit here is made locally, with a fixed identity and
a fixed date so the same base and the same two patches always produce the same
SHA. Anyone with the upstream repository can recompute it and get the same
forty characters, which is the property that makes it worth recording.

A pair whose patches do not both apply gets `head_sha: null` and a reason. The
census already marks those `usable: false`; this says why in the same row.

Clones are per repository rather than per task -- the census cloned once per
task, 30 times for 12 repositories -- and blobless, and each is deleted before
the next repository starts, because the corpus does not fit on this disk.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_URL = re.compile(r"https://github\.com/[^\s\"']+")
_SHA = re.compile(r"git checkout ([0-9a-f]{7,40})")

# A commit's SHA depends on its author, committer and dates. Fixing all of them
# is what makes head_sha reproducible rather than a per-run accident.
STAMP = {
    "GIT_AUTHOR_NAME": "conetic-farm census",
    "GIT_AUTHOR_EMAIL": "census@conetic-farm.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "conetic-farm census",
    "GIT_COMMITTER_EMAIL": "census@conetic-farm.invalid",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git(root: Path, *args: str, check: bool = True, env: dict | None = None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=check, env=e)


def task_source(task_dir: Path) -> tuple[str, str] | None:
    text = (task_dir / "Dockerfile").read_text()
    url, sha = _URL.search(text), _SHA.search(text)
    return (url.group(0), sha.group(1)) if url and sha else None


def clone_blobless(url: str, dest: Path) -> bool:
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
    """Apply, tolerantly, the same way the census checked applicability."""
    for extra in (["--ignore-whitespace"], ["--3way"]):
        if git(root, "apply", *extra, str(patch), check=False).returncode == 0:
            return True
    return False


def lane_commit(root: Path, base_sha: str, patch: Path) -> tuple[str | None, str]:
    """base + one gold patch, as a real commit. This is one lane's branch."""
    git(root, "checkout", "--quiet", "--force", base_sha)
    git(root, "clean", "-qfdx", check=False)
    if not apply_patch(root, patch):
        git(root, "reset", "--quiet", "--hard", base_sha)
        git(root, "clean", "-qfdx", check=False)
        return None, f"{patch.parent.name} does not apply to {base_sha[:10]}"
    git(root, "add", "-A")
    tree = git(root, "write-tree").stdout.strip()
    commit = git(root, "commit-tree", tree, "-p", base_sha,
                 "-m", f"census lane: base + {patch.parent.name}",
                 env=STAMP).stdout.strip()
    git(root, "reset", "--quiet", "--hard", base_sha)
    git(root, "clean", "-qfdx", check=False)
    return (commit or None), ""


def head_for_pair(root: Path, base_sha: str, lanes: list[str]
                  ) -> tuple[str | None, str, list[str]]:
    """The pair's head: the two lane commits merged, when git will merge them.

    Not "apply one patch then the other". Sequential application conflates two
    different outcomes -- a patch that is broken against the base, and a patch
    that is fine against the base and collides with its partner -- and the
    second is exactly the thing the census is counting. A pair git refuses has
    no head, and saying so is the measurement.
    """
    git(root, "checkout", "--quiet", "--force", lanes[0])
    r = git(root, "merge", "--no-edit", "--no-ff", lanes[1], check=False, env=STAMP)
    if r.returncode != 0:
        paths = sorted({l.split("\t")[-1] for l in
                        git(root, "diff", "--name-only", "--diff-filter=U",
                            check=False).stdout.splitlines() if l.strip()})
        git(root, "merge", "--abort", check=False)
        git(root, "checkout", "--quiet", "--force", base_sha)
        git(root, "clean", "-qfdx", check=False)
        return None, "git refuses the merge", paths
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "checkout", "--quiet", "--force", base_sha)
    git(root, "clean", "-qfdx", check=False)
    return (head or None), "", []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", default=str(REPO_ROOT / "results" / "census_resolved.json"))
    ap.add_argument("--dataset", default="/home/user/work/CooperBench/dataset")
    ap.add_argument("--out", default=str(REPO_ROOT / "farm" / "census" / "manifest.jsonl"))
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--only-repo", action="append", default=None)
    args = ap.parse_args()

    census = json.loads(Path(args.census).read_text())
    dataset = Path(args.dataset)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(args.workdir or tempfile.mkdtemp(prefix="census-manifest-"))
    work.mkdir(parents=True, exist_ok=True)

    # Resume: a repository already fully written is not cloned again.
    done_repos: set[str] = set()
    existing: list[str] = []
    if out.exists():
        existing = out.read_text().splitlines()
        counts = defaultdict(int)
        for line in existing:
            counts[json.loads(line)["repo"]] += 1
        want = defaultdict(int)
        for p in census["pairs"]:
            want[p["repo"]] += 1
        done_repos = {r for r, n in counts.items() if n == want[r]}
        if done_repos:
            log(f"resuming; already complete: {sorted(done_repos)}")

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for p in census["pairs"]:
        by_repo[p["repo"]].append(p)

    written = [line for line in existing
               if json.loads(line)["repo"] in done_repos]

    for repo, pairs in sorted(by_repo.items()):
        if args.only_repo and repo not in args.only_repo:
            continue
        if repo in done_repos:
            continue
        tasks = sorted({p["task"] for p in pairs})
        first = task_source(dataset / repo / tasks[0])
        if first is None:
            log(f"{repo}: no url in Dockerfile; skipping")
            continue
        url = first[0]
        checkout = work / repo
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: cloning {url} for {len(tasks)} task(s), {len(pairs)} pair(s)")
        if not clone_blobless(url, checkout):
            log(f"{repo}: clone failed; skipping")
            continue

        rows_for_repo = []
        for task in tasks:
            task_dir = dataset / repo / task
            src = task_source(task_dir)
            if src is None:
                continue
            _, base_sha = src
            # The Dockerfile may carry an abbreviated sha; the manifest records
            # the full one, which is what a reader needs to fetch it.
            full = git(checkout, "rev-parse", base_sha, check=False).stdout.strip()
            base_full = full if len(full) == 40 else base_sha
            # One lane commit per feature, reused across every pair that
            # names it: a task with 5 features has 10 pairs but 5 lanes.
            lane_cache: dict[int, tuple[str | None, str]] = {}

            def lane(fid: int):
                if fid not in lane_cache:
                    lane_cache[fid] = lane_commit(
                        checkout, base_full,
                        task_dir / f"feature{fid}" / "feature.patch")
                return lane_cache[fid]

            for p in [q for q in pairs if q["task"] == task]:
                (sha1, why1), (sha2, why2) = lane(p["f1"]), lane(p["f2"])
                if sha1 is None or sha2 is None:
                    head, why, paths = None, "; ".join(w for w in (why1, why2) if w), []
                else:
                    head, why, paths = head_for_pair(checkout, base_full, [sha1, sha2])
                rows_for_repo.append(json.dumps({
                    "repo": repo,
                    "upstream": url,
                    "task": task,
                    "features": [p["f1"], p["f2"]],
                    "base_sha": base_full,
                    "lane_sha": {str(p["f1"]): sha1, str(p["f2"]): sha2},
                    "head_sha": head,
                    "head_sha_note": why or ("the two lane commits merged; "
                                             "fixed identity and date, so the "
                                             "same inputs give the same sha"),
                    "conflicted_paths": paths,
                    "label": p["class_resolved"],
                    "label_diff_only": p["class_diff_only"],
                    "usable": p["usable"],
                    "has_link": p["has_link"],
                    "link": p["link"],
                }, sort_keys=True))
            log(f"    {repo}/{task}: {len([q for q in pairs if q['task']==task])} pair(s) done")
        written.extend(rows_for_repo)
        out.write_text("\n".join(written) + "\n")
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: written, {len(rows_for_repo)} row(s); manifest now {len(written)}")

    log(f"done: {len(written)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
