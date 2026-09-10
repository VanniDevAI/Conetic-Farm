#!/usr/bin/env python3
"""Grade the census pairs git will actually merge, with the claim map.

`farm/census/manifest.jsonl` says which of 652 pairs git merges: 147 of them.
That is the only part of the corpus where a semantic failure can live, because
a refused merge never reaches a test suite. This asks the claim map about those
147, and asks it the directed question the census did not:

* **Does a chain run from one lane's changed definitions to the other's**, and
  in which direction? `semantic_link` tries both ways and returns the first
  hit, which answers "are these two related" and not "which one provides".
  Provider and consumer are different roles and the engine has to name them.
* **Would the combined tree notice?** A chain is a relationship between two
  patches. Whether anything breaks depends on there being a test that runs the
  consumer's code against the provider's change, so this indexes the merged
  tree -- both feature patches and both graded test patches -- and asks which
  changed definitions the tests can reach at all.

Reaching is not asserting. A test that reaches both sides *could* observe a
disagreement; whether it checks the right thing is not a static question. The
number bounds the corpus's ability to demonstrate the class without new tests.

The base index is the right one for the chain: both gold patches are written
against the base, and `changed_definitions` maps old-side line positions. The
merged index is the right one for the tests, because that is the tree that runs.

Each pair's merge is rebuilt from its lane commits and the resulting sha is
checked against the manifest's `head_sha`. A mismatch is reported, not ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.identity import build_index, reaches                    # noqa: E402
from farm.overlap import changed_definitions, parse_patch          # noqa: E402

STAMP = {
    "GIT_AUTHOR_NAME": "conetic-farm census",
    "GIT_AUTHOR_EMAIL": "census@conetic-farm.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_NAME": "conetic-farm census",
    "GIT_COMMITTER_EMAIL": "census@conetic-farm.invalid",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
}

# What counts as a test file. Deliberately broad: a false positive here makes
# the "tests could observe it" number too generous, and being too generous is
# the safe direction for a bound that is about to be reported as an upper one.
TEST_PATH = re.compile(
    r"(^|/)(tests?|spec|__tests__|testing)(/|$)|"
    r"(^|/)(test_[^/]*|[^/]*_test|[^/]*\.test|[^/]*\.spec)\.[a-z]+$",
    re.I)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def git(root: Path, *args: str, check: bool = True, env: dict | None = None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=check, env=e)


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
    for extra in (["--ignore-whitespace"], ["--3way"]):
        if git(root, "apply", *extra, str(patch), check=False).returncode == 0:
            return True
    return False


def commit_all(root: Path, parent: str, message: str) -> str:
    git(root, "add", "-A")
    tree = git(root, "write-tree").stdout.strip()
    return git(root, "commit-tree", tree, "-p", parent, "-m", message,
               env=STAMP).stdout.strip()


def test_reachers(idx, targets: set) -> dict:
    """How close a test gets to `targets`, per hop budget.

    Hop count is the whole measurement here. Starting from the union of every
    definition in every test file and allowing three hops, almost everything in
    a library is reachable -- the first pass returned 100% and 92%, which is a
    fact about the metric and not about the corpus. One hop is the number with
    content: *a test's own body names the changed definition*, which is what a
    person means by "there is a test for it".
    """
    if not targets:
        return {"1": False, "2": False, "3": False}
    starts = {d for path, defs in idx.by_path.items() if TEST_PATH.search(path)
              for d in defs}
    if not starts:
        return {"1": False, "2": False, "3": False}
    return {str(h): reaches(idx, starts, targets, max_hops=h) is not None
            for h in (1, 2, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(REPO_ROOT / "farm" / "census" / "manifest.jsonl"))
    ap.add_argument("--dataset", default="/home/user/work/CooperBench/dataset")
    ap.add_argument("--out", default=str(REPO_ROOT / "farm" / "census" / "claim_grade.jsonl"))
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--only-repo", action="append", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.manifest).read_text().splitlines()]
    clean = [r for r in rows if r["head_sha"]]
    log(f"{len(clean)} merge-clean pairs of {len(rows)}")

    dataset = Path(args.dataset)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(args.workdir or tempfile.mkdtemp(prefix="claim-grade-"))
    work.mkdir(parents=True, exist_ok=True)

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in clean:
        by_repo[r["repo"]].append(r)

    written: list[str] = []
    if out.exists():
        written = out.read_text().splitlines()
        done = {json.loads(l)["repo"] for l in written}
        want = {r: len(v) for r, v in by_repo.items()}
        have: dict[str, int] = defaultdict(int)
        for l in written:
            have[json.loads(l)["repo"]] += 1
        done = {r for r in done if have[r] == want[r]}
        written = [l for l in written if json.loads(l)["repo"] in done]
        if done:
            log(f"resuming; complete: {sorted(done)}")
    else:
        done = set()

    for repo, pairs in sorted(by_repo.items()):
        if args.only_repo and repo not in args.only_repo:
            continue
        if repo in done:
            continue
        url = pairs[0]["upstream"]
        checkout = work / repo
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: cloning for {len(pairs)} merge-clean pair(s)")
        if not clone_blobless(url, checkout):
            log(f"{repo}: clone failed; skipping")
            continue

        rows_for_repo: list[str] = []
        for task in sorted({p["task"] for p in pairs}):
            task_dir = dataset / repo / task
            group = [p for p in pairs if p["task"] == task]
            base = group[0]["base_sha"]
            git(checkout, "checkout", "--quiet", "--force", base)
            git(checkout, "clean", "-qfdx", check=False)
            base_idx = build_index(checkout)
            log(f"    {repo}/{task}: base index {base_idx.files_indexed} files, "
                f"{len(base_idx.by_name)} names; {len(group)} pair(s)")

            # One rebuilt commit per feature, reused across every pair that
            # names it: a task with 5 features has 10 pairs but 5 lanes.
            lane_cache: dict[int, str | None] = {}
            facts: dict[int, object] = {}
            for p in group:
                for fid in p["features"]:
                    if fid not in facts:
                        fp = task_dir / f"feature{fid}" / "feature.patch"
                        facts[fid] = parse_patch(fp.read_text(errors="replace"))

            for p in group:
                f1, f2 = p["features"]
                d1 = changed_definitions(facts[f1], base_idx)
                d2 = changed_definitions(facts[f2], base_idx)
                row = {
                    "repo": repo, "task": task, "features": [f1, f2],
                    "base_sha": base, "head_sha": p["head_sha"],
                    "label": p["label"],
                    "changed_defs": {str(f1): len(d1), str(f2): len(d2)},
                }
                # Directed chains, per hop budget. `reaches(start, targets)`
                # walks OUT of start's bodies, so start is the consumer.
                for hops in (1, 2, 3):
                    a_provides = reaches(base_idx, d2, d1, max_hops=hops)
                    b_provides = reaches(base_idx, d1, d2, max_hops=hops)
                    row[f"chain_{hops}"] = {
                        f"{f1}_provides_{f2}": a_provides,
                        f"{f2}_provides_{f1}": b_provides,
                        "direction": ("mutual" if a_provides and b_provides
                                      else f"{f1}->{f2}" if a_provides
                                      else f"{f2}->{f1}" if b_provides
                                      else None),
                    }
                # The combined tree: both features and both graded test
                # patches. The manifest's lane commits were made in a clone
                # that has since been deleted, so they are rebuilt here by the
                # same procedure -- which is the point of stamping a fixed
                # identity and date on them. The shas are checked, not assumed.
                lane_shas = p["lane_sha"]
                rebuilt = {}
                for fid in (f1, f2):
                    if fid in lane_cache:
                        rebuilt[fid] = lane_cache[fid]
                        continue
                    git(checkout, "checkout", "--quiet", "--force", base)
                    git(checkout, "clean", "-qfdx", check=False)
                    fp = task_dir / f"feature{fid}" / "feature.patch"
                    sha = (commit_all(checkout, base, f"census lane: base + feature{fid}")
                           if apply_patch(checkout, fp) else None)
                    lane_cache[fid] = rebuilt[fid] = sha
                row["lane_sha_reproduced"] = {
                    str(fid): rebuilt[fid] == lane_shas.get(str(fid))
                    for fid in (f1, f2)}
                git(checkout, "checkout", "--quiet", "--force", base)
                git(checkout, "clean", "-qfdx", check=False)
                if not all(rebuilt.values()):
                    row["combined"] = {"built": False,
                                       "why": "a lane commit could not be rebuilt"}
                    rows_for_repo.append(json.dumps(row, sort_keys=True))
                    continue
                git(checkout, "checkout", "--quiet", "--force", rebuilt[f1])
                merge = git(checkout, "merge", "--no-edit", "--no-ff",
                            rebuilt[f2], check=False, env=STAMP)
                if merge.returncode != 0:
                    git(checkout, "merge", "--abort", check=False)
                    row["combined"] = {"built": False,
                                       "why": "the merge no longer applies"}
                else:
                    head = git(checkout, "rev-parse", "HEAD").stdout.strip()
                    row["head_sha_reproduced"] = head == p["head_sha"]
                    applied, refused = [], []
                    for fid in (f1, f2):
                        tp = task_dir / f"feature{fid}" / "tests.patch"
                        if not tp.exists():
                            continue
                        (applied if apply_patch(checkout, tp) else refused).append(fid)
                    merged_idx = build_index(checkout)
                    # Changed definitions are resolved against the base index,
                    # so ask the merged index for the same names in the same
                    # files rather than re-deriving spans that have moved.
                    def same(defs):
                        out_ = set()
                        for d in defs:
                            for cand in merged_idx.by_path.get(d.path, ()):
                                if cand.name == d.name:
                                    out_.add(cand)
                        return out_
                    m1, m2 = same(d1), same(d2)
                    row["combined"] = {
                        "built": True,
                        "tests_patches_applied": applied,
                        "tests_patches_refused": refused,
                        "files_indexed": merged_idx.files_indexed,
                        "test_files": sum(1 for path in merged_idx.by_path
                                          if TEST_PATH.search(path)),
                        "tests_reach": {
                            str(f1): test_reachers(merged_idx, m1),
                            str(f2): test_reachers(merged_idx, m2),
                        },
                        "defs_found_in_merged": {str(f1): len(m1), str(f2): len(m2)},
                    }
                git(checkout, "checkout", "--quiet", "--force", base)
                git(checkout, "clean", "-qfdx", check=False)
                rows_for_repo.append(json.dumps(row, sort_keys=True))
        written.extend(rows_for_repo)
        out.write_text("\n".join(written) + "\n")
        shutil.rmtree(checkout, ignore_errors=True)
        log(f"{repo}: {len(rows_for_repo)} row(s); total {len(written)}")

    log(f"done: {len(written)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
