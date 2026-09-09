#!/usr/bin/env python3
"""Check the ablation against the transcripts of the lanes that motivated it.

No agent runs. The claim being checked is narrow and static: **in the prompt a
roomed lane actually received, the last instruction was to start editing, and
under the ablated assembly it is not.** Whether that changes behaviour is c07's
job; this only establishes that the thing blamed is really there and is really
gone.

For every roomed lane of c06b it reconstructs both prompts from the same inputs
the runner used -- the lane's brief file and the room stored beside the episode
-- prints the last instruction each one ends on, and sets that against what the
lane did: did it run a git command, and did it submit a patch or have one taken
from its container.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RUN = Path("/home/user/farm-c06b")
def final_block(text: str) -> str:
    """The last paragraph of the prompt: what the model reads last.

    A line is the wrong unit. The room's closing instruction wraps across three
    lines and ends on "prevent all look small from inside one branch", which
    reads as prose on its own and is the tail of "Do not skip step 1".
    """
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return blocks[-1] if blocks else ""


def ends_on_edit_now(text: str) -> bool:
    """Does the prompt close on an instruction to start editing?

    Checked against the room's own closing block rather than a guess at what
    an imperative looks like: `farm.room_brief.PROTOCOL` is the exact text, and
    its last two sentences are the ones that land last.
    """
    from farm.room_brief import PROTOCOL
    tail = final_block(text)
    return tail and tail in PROTOCOL.strip()


def lane_behaviour(ep_dir: Path, lane: str) -> dict:
    """What the lane did, from its own result and trajectory."""
    out = {"ran_git": None, "patch_lines": None, "salvaged": None}
    res = ep_dir / f"{lane}_result.json"
    if res.exists():
        agent = json.loads(res.read_text())["agent"]
        out["patch_lines"] = agent.get("patch_lines")
        out["salvaged"] = agent.get("patch_salvaged")
    traj = list(ep_dir.glob(f"logs/*-{lane}/solo/*/*/*/solo_full_traj.json")) or \
           list(ep_dir.glob(f"logs/*-{lane}/solo/*/*/*/solo_traj.json"))
    if traj:
        blob = traj[0].read_text(errors="replace")
        out["ran_git"] = ("To /tmp/team.git" in blob
                          or re.search(r"\[solo [0-9a-f]{7}\]", blob) is not None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(REPO_ROOT / "config" / "c06b_rerun.json"))
    args = ap.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "runner", REPO_ROOT / "scripts" / "run_room_episode.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    plan = json.loads(Path(args.plan).read_text())
    as_run = {**runner.ROOM_DEFAULTS, **plan.get("room", {})}
    ablated = dict(runner.ROOM_DEFAULTS)
    print(f"as run : {as_run['placement']}, closing protocol "
          f"{'on' if as_run['closing_protocol'] else 'off'}")
    print(f"ablated: {ablated['placement']}, closing protocol "
          f"{'on' if ablated['closing_protocol'] else 'off'}")
    print()

    rows = []
    for ep in plan["episodes"]:
        if ep["arm"] != "roomed":
            continue
        room_path = RUN / ep["id"] / "room.md"
        if not room_path.exists():
            print(f"{ep['id']}: no room.md on disk; skipping")
            continue
        room = room_path.read_text()
        for lane in ep["lanes"]:
            was = runner.assemble(lane["brief"], room, as_run)
            now = runner.assemble(lane["brief"], room, ablated)
            # The ablated room has no protocol block, so rebuild it that way.
            now = runner.assemble(
                lane["brief"],
                room.split("### Before you write anything")[0].rstrip() + "\n",
                ablated)
            rows.append({
                "episode": ep["id"], "lane": lane["id"],
                "as_run_ends": final_block(was),
                "ablated_ends": final_block(now),
                "as_run_edit_now": ends_on_edit_now(was),
                "ablated_edit_now": ends_on_edit_now(now),
                **lane_behaviour(RUN / ep["id"], lane["id"]),
            })

    width = max(len(f"{r['episode']} {r['lane']}") for r in rows)
    print("what each roomed lane's prompt ended on, and what the lane did:\n")
    for r in rows:
        tag = f"{r['episode']} {r['lane']}"
        print(f"  {tag:{width}}  ran_git={str(r['ran_git']):5} "
              f"patch_lines={str(r['patch_lines']):5} salvaged={str(r['salvaged']):5}")
        one = lambda t: " ".join(t.split())[:96]
        print(f"  {'':{width}}  as run  ends on: {one(r['as_run_ends'])!r}"
              f"  edit-now={r['as_run_edit_now']}")
        print(f"  {'':{width}}  ablated ends on: {one(r['ablated_ends'])!r}"
              f"  edit-now={r['ablated_edit_now']}")
    print()

    ends_imperative_before = sum(1 for r in rows if r["as_run_edit_now"])
    ends_imperative_after = sum(1 for r in rows if r["ablated_edit_now"])
    skipped = [r for r in rows if r["ran_git"] is False]
    print(f"prompts ending on an edit-now imperative: "
          f"{ends_imperative_before} of {len(rows)} as run, "
          f"{ends_imperative_after} of {len(rows)} ablated")
    print(f"lanes that never ran a git command: {len(skipped)} of {len(rows)}"
          + (f" ({', '.join(r['lane'] + ' of ' + r['episode'] for r in skipped)})"
             if skipped else ""))
    print()
    if ends_imperative_after == 0 and ends_imperative_before == len(rows):
        print("VERIFIED: every roomed prompt used to end on an instruction to start "
              "editing, and none does now.")
    else:
        print("NOT VERIFIED: the assembly does not do what the ablation claims.")
        return 1
    print("Not established here: that this changes behaviour. c07's roomed arm "
          "is the test, and its submit-skip rate is the number to read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
