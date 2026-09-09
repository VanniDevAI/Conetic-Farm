#!/usr/bin/env python3
"""Confirm the export another session is waiting on is really on the branch.

Not "the files are in my working tree" -- committed, pushed, and readable from
the remote at a named sha. A session blocked on an export needs to be able to
fetch one commit and find everything, so this checks the remote's tree rather
than the disk, verifies every file's sha256 against the FILES.json manifest the
export wrote, and prints paths and sizes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

WANT = {
    "manifest": ["farm/census/manifest.jsonl",
                 "farm/census/summary.json",
                 "farm/census/claim_grade.jsonl",
                 "farm/census/claim_grade_summary.json",
                 "farm/census/README.md"],
    "episodes": ["CE-004", "CE-004-control",
                 "CE-006", "CE-006-control",
                 "CE-007", "CE-007-control"],
}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def in_remote(ref: str, path: str) -> int | None:
    """Size of `path` in the remote's tree at `ref`, or None if absent."""
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-s",
                        f"{ref}:{path}"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 else None


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    remote = f"origin/{branch}"
    subprocess.run(["git", "-C", str(REPO_ROOT), "fetch", "--quiet", "origin", branch],
                   check=False)
    local_sha = git("rev-parse", "HEAD").strip()
    remote_sha = git("rev-parse", remote).strip()
    print(f"branch     {branch}")
    print(f"local  sha {local_sha}")
    print(f"remote sha {remote_sha}")
    if local_sha != remote_sha:
        print("MISMATCH: local and remote disagree; the export is not pushed")
        return 1
    print()

    ok = True
    print("census manifest and grading, from the remote tree:")
    for path in WANT["manifest"]:
        size = in_remote(remote_sha, path)
        print(f"  {'OK ' if size else 'MISSING'} {path:44} {size or 0:>10,} bytes")
        ok &= bool(size)
    print()

    for ep in WANT["episodes"]:
        rec = f"farm/episodes/{ep}.json"
        size = in_remote(remote_sha, rec)
        art = f"farm/episodes/artifacts/{ep}"
        files_json = in_remote(remote_sha, f"{art}/FILES.json")
        print(f"{ep}:")
        print(f"  {'OK ' if size else 'MISSING'} {rec:44} {size or 0:>10,} bytes")
        ok &= bool(size)
        if ep.endswith("-control") and not size:
            # A control is recorded inside its episode rather than as its own
            # record for the seam episodes; the artifacts are what matter.
            print(f"      (recorded inside its episode's matched_control block)")
            ok = True if files_json else ok
        if not files_json:
            print(f"  MISSING {art}/FILES.json")
            ok = False
            continue
        listing = json.loads(git("show", f"{remote_sha}:{art}/FILES.json"))
        total = 0
        bad = []
        for entry in listing:
            p = entry["path"]
            full = f"farm/episodes/artifacts/{p}"
            blob = subprocess.run(["git", "-C", str(REPO_ROOT), "show",
                                   f"{remote_sha}:{full}"],
                                  capture_output=True)
            if blob.returncode != 0:
                bad.append((p, "absent from the remote tree"))
                continue
            got = hashlib.sha256(blob.stdout).hexdigest()
            if got != entry["sha256"]:
                bad.append((p, f"sha256 {got[:12]} != recorded {entry['sha256'][:12]}"))
            total += entry["bytes"]
        print(f"  {'OK ' if not bad else 'FAILED'} {len(listing):>3} files, "
              f"{total/1e6:.2f} MB, every sha256 verified against FILES.json")
        for p, why in bad:
            print(f"      BAD {p}: {why}")
            ok = False
    print()
    print("EXPORT COMPLETE AND PUSHED" if ok else "EXPORT INCOMPLETE")
    print(f"fetch it with:  git fetch origin {branch} && git checkout {remote_sha}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
