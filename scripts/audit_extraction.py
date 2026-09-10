#!/usr/bin/env python3
"""Audit a campaign's archives for work the instrument lost.

This is the before/after proof for the container-teardown race
(`reports/c02_instrument_notes.md` §2, `docs/EXPECTATIONS.md` Appendix D).
Run it on `c02`'s published archives and it must FAIL; run it on a campaign
made after the fix and it must PASS.  It reads only what was written during
the run, so it cannot disagree with the corpus.

Three findings, each a way an agent's work can vanish between the agent
finishing and the campaign recording it:

  lost_work        an agent exited LimitsExceeded -- it pushed nothing and could
                   not (Appendix B.1) -- yet its recorded patch is EMPTY.  Its
                   work existed in a working tree nobody read.
  no_bundle        a container the snapshotter attached to has no exported
                   checkpoint bundle: the fallback record is missing too.
  container_gone   extraction reported "No such container": the harness had
                   already destroyed it when we came to read it.

Exit status 1 if any finding is present.

    scripts/audit_extraction.py --archives results/campaigns/c02/artifacts
    scripts/audit_extraction.py --data-root /home/user/farm-data-c03
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from collections import Counter
from pathlib import Path


def _load_from_archive(path: Path) -> tuple[dict | None, dict | None]:
    """(episode manifest, run_info of the manifest's last attempt) from a tar.gz."""
    manifest = run_infos = None
    with tarfile.open(path, "r:gz") as tf:
        members = {m.name: m for m in tf.getmembers() if m.isfile()}
        # Episode manifest sits one level down: <episode_id>/manifest.json.
        mf = [n for n in members if n.count("/") == 1 and n.endswith("/manifest.json")]
        if mf:
            manifest = json.loads(tf.extractfile(members[mf[0]]).read().decode("utf-8", "replace"))
        run_infos = {}
        for n, m in members.items():
            if n.endswith("/run_info.json") and "/attempts/" in n:
                attempt = n.split("/attempts/")[1].split("/")[0]
                run_infos[attempt] = json.loads(tf.extractfile(m).read().decode("utf-8", "replace"))
    if manifest is None:
        return None, None
    return manifest, run_infos


def _load_from_dir(ep_dir: Path) -> tuple[dict | None, dict | None]:
    mf = ep_dir / "manifest.json"
    if not mf.exists():
        return None, None
    manifest = json.loads(mf.read_text())
    run_infos = {}
    for ri in ep_dir.glob("attempts/attempt-*/run_info.json"):
        run_infos[ri.parent.name] = json.loads(ri.read_text())
    return manifest, run_infos


def _exported(ck: dict) -> bool:
    """Did the checkpoint bundle actually reach the host?

    `bundle_created` only says `git bundle create` succeeded *inside* the
    container; the `docker cp` that follows is recorded separately.  A container
    removed between the two leaves `{"bundle_created": true,
    "checkpoints.bundle": false}` and no file on disk -- and reading only the
    first made that episode audit `clean`.  Since this audit is the before/after
    proof for the teardown fix, that would have let a campaign lose every bundle
    and still print PASS.

    Archives written before `exported` existed are judged by the same rule,
    derived from the two keys they do carry.
    """
    if "exported" in ck:
        return bool(ck["exported"])
    if "checkpoints.bundle" in ck:
        return bool(ck.get("bundle_created") and ck.get("checkpoints.bundle"))
    return bool(ck.get("bundle_created"))


def audit_episode(manifest: dict, run_infos: dict) -> list[tuple[str, str]]:
    """Findings for one episode: [(kind, detail)], empty when nothing was lost."""
    completed = [a for a in manifest.get("attempts", []) if a.get("status") == "completed"]
    if not completed:
        return []          # a harness error lost nothing the agent produced
    last = completed[-1]
    findings: list[tuple[str, str]] = []

    for ag in last.get("agents", []):
        if ag.get("exit_status") == "LimitsExceeded" and (ag.get("patch") or {}).get("bytes", 0) == 0:
            findings.append(("lost_work", f"agent {ag.get('role')} exited LimitsExceeded with an empty patch"))

    ri = run_infos.get(last.get("attempt_id"), {}) if run_infos else {}
    for cid, ck in (ri.get("checkpoints") or {}).items():
        if not ck or not _exported(ck) or not ck.get("checkpoints"):
            findings.append(("no_bundle", f"container {cid[:12]} has no exported checkpoint bundle"))
    for name, ex in (ri.get("extracted_patches") or {}).items():
        for w in (ex or {}).get("warnings") or []:
            if "No such container" in w:
                findings.append(("container_gone", f"{name}: {w[:80]}"))
                break
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--archives", type=Path, help="directory of <episode>.tar.gz archives")
    g.add_argument("--data-root", type=Path, help="live $FARM_DATA_ROOT")
    args = ap.parse_args()

    episodes: list[tuple[str, dict | None, dict | None]] = []
    if args.archives:
        for p in sorted(args.archives.glob("*.tar.gz")):
            m, r = _load_from_archive(p)
            episodes.append((p.name.removesuffix(".tar.gz"), m, r))
    else:
        for d in sorted((args.data_root / "episodes").iterdir()):
            if d.is_dir():
                m, r = _load_from_dir(d)
                episodes.append((d.name, m, r))

    totals: Counter[str] = Counter()
    audited = affected = 0
    print(f"{'episode':56s} findings")
    for eid, m, r in episodes:
        if m is None:
            print(f"{eid[:56]:56s} (no manifest)")
            continue
        audited += 1
        f = audit_episode(m, r or {})
        if f:
            affected += 1
            for kind, _ in f:
                totals[kind] += 1
        label = ", ".join(sorted({k for k, _ in f})) or "clean"
        print(f"{eid[:56]:56s} {label}")
        for _, detail in f:
            print(f"{'':56s}   - {detail}")

    print()
    print(f"audited {audited} episode(s); {affected} with findings, "
          f"{totals.get('lost_work', 0)} with work definitely lost")
    for kind in ("lost_work", "no_bundle", "container_gone"):
        print(f"  {kind:15s} {totals.get(kind, 0)}")
    if affected:
        print("\nFAIL: the instrument lost work it had no reason to lose")
        return 1
    print("\nPASS: every agent that worked has its work recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
