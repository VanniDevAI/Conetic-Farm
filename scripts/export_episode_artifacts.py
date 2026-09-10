#!/usr/bin/env python3
"""Copy an episode's complete evidence into the repository.

`farm/episodes/CE-004.json` records what happened and points at
`/home/user/farm-c05a/...` for the proof. That path is in an ephemeral
container: the record survives a rebuild and everything it cites does not. A
citation nobody can follow is a claim, not evidence.

So the artifacts move into the repository, whole, beside the record:

    farm/episodes/artifacts/<id>/
        patches/          both lanes' patches, and the graded test patches
        results/          every suite run: a alone, b alone, integrated, a full
        trajectories/     what each agent actually did, step by step
        provider_build/   the built provider package the consumer installed
        cost.json         what it billed, and where that number comes from
        MANIFEST.md       what each file is and how to reproduce the result

Nothing is filtered and nothing is summarised, because the point of an archive
is that a reader can disagree with the summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST_ROOT = REPO_ROOT / "farm" / "episodes" / "artifacts"

# What the run tree calls things, and what the archive calls them.
LAYOUT = {
    "patches_provider": "patches",
    "patches_consumer": "patches",
    "results": "results",
    "provider_build": "provider_build",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dest: Path, index: list[dict]) -> None:
    for item in sorted(src.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        index.append({"path": str(target.relative_to(DEST_ROOT)),
                      "bytes": target.stat().st_size,
                      "sha256": digest(target),
                      "from": str(item)})


def is_seam_run(run_dir: Path) -> bool:
    """A seam run has a provider and a consumer in different repositories.

    The two layouts are genuinely different runs, not a naming accident: a seam
    episode has `patches_provider/`, `patches_consumer/` and a `pair_result.json`
    summarising one provider against one consumer; a two-lane episode has
    `patches/lane*.patch`, `merge_<tag>/` and an `episode.json`. Detect by what
    is on disk rather than by the id, so a new campaign does not silently export
    nothing.
    """
    return (run_dir / "pair_result.json").exists()


def export_two_lane(run_dir: Path, out: Path, index: list[dict]) -> None:
    """A same-repository episode: N lanes, one merge, one set of graded runs."""
    for src, into in (("patches", "patches"), ("results", "results"),
                      ("merge_initial", "merge"), ("merge_after_repair", "merge")):
        d = run_dir / src
        if not d.is_dir():
            continue
        for item in sorted(d.iterdir()):
            if not item.is_file():
                continue
            prefix = "after_repair_" if src == "merge_after_repair" else ""
            target = out / into / f"{prefix}{item.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            index.append({"path": str(target.relative_to(DEST_ROOT)),
                          "bytes": target.stat().st_size,
                          "sha256": digest(target), "from": str(item)})
    for item in sorted(run_dir.glob("lane*_*.json")):
        target = out / "trajectories" / item.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        index.append({"path": str(target.relative_to(DEST_ROOT)),
                      "bytes": target.stat().st_size,
                      "sha256": digest(target), "from": str(item)})
    for full in sorted(run_dir.glob("logs/*/solo/*/*/*/solo_full_traj.json")):
        lane = full.parts[len(run_dir.parts) + 1].rsplit("-", 1)[-1]
        target = out / "trajectories" / f"{lane}_solo_full_traj.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, target)
        index.append({"path": str(target.relative_to(DEST_ROOT)),
                      "bytes": target.stat().st_size,
                      "sha256": digest(target), "from": str(full)})
    for name in ("episode.json", "room.md"):
        item = run_dir / name
        if item.exists():
            shutil.copy2(item, out / name)
            index.append({"path": str((out / name).relative_to(DEST_ROOT)),
                          "bytes": (out / name).stat().st_size,
                          "sha256": digest(out / name), "from": str(item)})


def export(run_dir: Path, out: Path, *, role: str) -> list[dict]:
    index: list[dict] = []
    if not is_seam_run(run_dir):
        export_two_lane(run_dir, out, index)
        return index
    for name, into in LAYOUT.items():
        src = run_dir / name
        if not src.exists():
            continue
        prefix = ""
        if name.startswith("patches_"):
            prefix = name.removeprefix("patches_") + "_"
        for item in sorted(src.iterdir()):
            if not item.is_file():
                continue
            target = out / into / f"{prefix}{item.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            index.append({"path": str(target.relative_to(DEST_ROOT)),
                          "bytes": target.stat().st_size,
                          "sha256": digest(target),
                          "from": str(item)})
    # The full trajectory, where one exists. A lane whose context was
    # compacted has its segments only in `solo_full_traj.json`; the top-level
    # `agent_*_solo_traj.json` is the trimmed view and drops the earlier
    # segments entirely. CE-004's lane A is such a lane.
    for full in sorted(run_dir.glob("logs/*/solo/*/*/*/solo_full_traj.json")):
        lane = full.parts[len(run_dir.parts) + 1].rsplit("-", 1)[-1]
        target = out / "trajectories" / f"agent_{lane}_solo_full_traj.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, target)
        index.append({"path": str(target.relative_to(DEST_ROOT)),
                      "bytes": target.stat().st_size, "sha256": digest(target),
                      "from": str(full)})
    # Trajectories: the copies under logs/ are duplicates of the top-level
    # ones, so take the top-level pair and the agent result summaries.
    for item in sorted(run_dir.glob("agent_*")):
        if item.is_file():
            target = out / "trajectories" / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            index.append({"path": str(target.relative_to(DEST_ROOT)),
                          "bytes": target.stat().st_size,
                          "sha256": digest(target),
                          "from": str(item)})
    # The run's own summary, verbatim.
    pr = run_dir / "pair_result.json"
    if pr.exists():
        shutil.copy2(pr, out / "pair_result.json")
        index.append({"path": str((out / "pair_result.json").relative_to(DEST_ROOT)),
                      "bytes": pr.stat().st_size, "sha256": digest(pr),
                      "from": str(pr)})
    # The merge, stated rather than left to be inferred. Both lanes of a seam
    # episode live in different repositories, so git has no shared path to
    # conflict on and "clean" is a property of the layout, not a result. A
    # reader who takes it for a measurement would read the episode backwards.
    pr_data = json.loads((run_dir / "pair_result.json").read_text())
    (out / "merge.json").write_text(json.dumps(pr_data["merge"], indent=2) + "\n")
    index.append({"path": str((out / "merge.json").relative_to(DEST_ROOT)),
                  "bytes": (out / "merge.json").stat().st_size,
                  "sha256": digest(out / "merge.json"),
                  "from": str(run_dir / "pair_result.json") + " [merge]"})
    # The agent configs, which say what model and what ceiling each lane ran under.
    for cfg in sorted(run_dir.glob("logs/*/config.json")):
        lane = cfg.parent.name.rsplit("-", 1)[-1]
        target = out / "config" / f"lane_{lane}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cfg, target)
        index.append({"path": str(target.relative_to(DEST_ROOT)),
                      "bytes": target.stat().st_size, "sha256": digest(target),
                      "from": str(cfg)})
    return index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True,
                    help="JSON: [{id, run_dir, role, billed_usd, note}]")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text())

    for entry in spec:
        run_dir = Path(entry["run_dir"])
        if not run_dir.exists():
            print(f"MISSING: {run_dir}", file=sys.stderr)
            return 1
        out = DEST_ROOT / entry["id"]
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        index = export(run_dir, out, role=entry["role"])
        (out / "cost.json").write_text(json.dumps(entry["cost"], indent=2) + "\n")
        (out / "FILES.json").write_text(json.dumps(index, indent=2) + "\n")
        total = sum(f["bytes"] for f in index)
        print(f"{entry['id']}: {len(index)} files, {total/1e6:.2f} MB -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
