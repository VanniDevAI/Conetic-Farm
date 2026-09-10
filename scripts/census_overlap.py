#!/usr/bin/env python3
"""Re-run the pair census with symbols resolved through the identity graph.

The first census read symbols off changed lines, which is blind by one hop and
therefore blind to the shape the Farm is looking for. This one builds an
identity graph from each task's repository at its pinned base commit and asks
the question of the code instead of the diff.

Two numbers come out, and both are reported:

* the **class**, under unchanged precedence. A pair git will refuse is
  `textual` whatever the symbols say, so resolution can only move pairs whose
  files are disjoint.
* the **link**, asked of every pair regardless of class: is there a chain of
  named definitions from one patch's changed code to the other's? That is the
  question a claim map answers, and it is not gated by precedence.

A pair is `usable` when both gold patches apply to the base tree, which is the
same criterion the first census used.

Each repository is cloned blobless, indexed, measured and deleted before the
next one, because the whole corpus does not fit on this disk at once.
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
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.identity import build_index                      # noqa: E402
from farm.overlap import classify_overlap, parse_patch, semantic_link  # noqa: E402

_URL = re.compile(r"https://github\.com/[^\s\"']+")
_SHA = re.compile(r"git checkout ([0-9a-f]{7,40})")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def task_source(task_dir: Path) -> tuple[str, str] | None:
    text = (task_dir / "Dockerfile").read_text()
    url = _URL.search(text)
    sha = _SHA.search(text)
    if not url or not sha:
        return None
    return url.group(0), sha.group(1)


def clone_at(url: str, sha: str, dest: Path) -> bool:
    for attempt in (1, 2, 3):
        try:
            subprocess.run(["git", "clone", "--filter=blob:none", "--no-tags",
                            "--quiet", url, str(dest)], check=True, timeout=1800)
            subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", sha],
                           check=True, timeout=1800)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            log(f"    clone attempt {attempt} failed: {e}")
            shutil.rmtree(dest, ignore_errors=True)
            time.sleep(2 ** attempt)
    return False


def applies(root: Path, patch: Path) -> bool:
    r = subprocess.run(["git", "-C", str(root), "apply", "--check",
                        "--ignore-whitespace", str(patch)],
                       capture_output=True)
    if r.returncode == 0:
        return True
    r = subprocess.run(["git", "-C", str(root), "apply", "--check", "--3way",
                        str(patch)], capture_output=True)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="/home/user/work/CooperBench/dataset")
    ap.add_argument("--out", default=str(REPO_ROOT / "results" / "census_resolved.json"))
    ap.add_argument("--exclude", action="append", default=["tanstack_query_task", "zod_task"],
                    help="repos seeded by the Farm, measured separately")
    ap.add_argument("--max-hops", type=int, default=3)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    dataset = Path(args.dataset)
    work = Path(args.workdir or tempfile.mkdtemp(prefix="census-"))
    work.mkdir(parents=True, exist_ok=True)

    tasks: dict[str, list[Path]] = {}
    for task_dir in sorted(dataset.glob("*_task/task*")):
        repo = task_dir.parent.name
        if repo in args.exclude:
            continue
        tasks.setdefault(repo, []).append(task_dir)

    rows: list[dict] = []
    skipped: list[dict] = []
    for repo, dirs in sorted(tasks.items()):
        for task_dir in dirs:
            src = task_source(task_dir)
            if src is None:
                skipped.append({"task": f"{repo}/{task_dir.name}", "why": "no url/sha"})
                continue
            url, sha = src
            checkout = work / f"{repo}-{task_dir.name}"
            shutil.rmtree(checkout, ignore_errors=True)
            log(f"{repo}/{task_dir.name}: cloning {url} @ {sha[:10]}")
            if not clone_at(url, sha, checkout):
                skipped.append({"task": f"{repo}/{task_dir.name}", "why": "clone failed"})
                continue
            idx = build_index(checkout)
            feats = sorted(int(p.name.removeprefix("feature"))
                           for p in task_dir.glob("feature*") if p.is_dir())
            log(f"    indexed {idx.files_indexed} files, {len(idx.by_name)} names; "
                f"{len(feats)} features -> {len(list(combinations(feats, 2)))} pairs")
            for f1, f2 in combinations(feats, 2):
                pa = task_dir / f"feature{f1}" / "feature.patch"
                pb = task_dir / f"feature{f2}" / "feature.patch"
                if not pa.exists() or not pb.exists():
                    continue
                usable = applies(checkout, pa) and applies(checkout, pb)
                a, b = parse_patch(pa.read_text()), parse_patch(pb.read_text())
                row = {
                    "repo": repo, "task": task_dir.name, "f1": f1, "f2": f2,
                    "usable": usable,
                    "class_diff_only": classify_overlap(a, b),
                    "class_resolved": classify_overlap(a, b, idx),
                }
                chain = semantic_link(a, b, idx, max_hops=args.max_hops)
                row["link"] = chain
                row["has_link"] = bool(chain)
                rows.append(row)
            shutil.rmtree(checkout, ignore_errors=True)

    usable = [r for r in rows if r["usable"]]
    def tally(key):
        out: dict[str, int] = {}
        for r in usable:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))

    summary = {
        "generated": time.strftime("%Y-%m-%d"),
        "scope": "every CooperBench pair whose gold patches both apply, "
                 "excluding the Farm's own seeded repos",
        "pairs_total": len(rows),
        "pairs_usable": len(usable),
        "class_diff_only": tally("class_diff_only"),
        "class_resolved": tally("class_resolved"),
        "link_found": sum(1 for r in usable if r["has_link"]),
        "link_found_by_class": {},
        "max_hops": args.max_hops,
        "skipped": skipped,
    }
    for r in usable:
        if r["has_link"]:
            k = r["class_resolved"]
            summary["link_found_by_class"][k] = summary["link_found_by_class"].get(k, 0) + 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "pairs": rows}, indent=2))
    log(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
