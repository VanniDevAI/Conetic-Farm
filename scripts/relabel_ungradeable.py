#!/usr/bin/env python3
"""Correct `a_broken`/`b_broken` to `ungradeable_*` in finished archives.

The `s02` control found the corpus asserting *"agent A's patch fails its own
tests in isolation"* for a patch that was never graded: the dataset's test patch
could not be applied over the agent's edit. That claim is in `c01`-`c03` and the
sweeps as well, written before `ungradeable` existed as a label.

This rewrites the label where the evidence says the grader never ran, and
**keeps the original beside it** (`label_original`). A correction that erases
what it corrected cannot itself be audited, and these are finished experiments.

Deliberately narrow, matching `farm.classify.ungradeable_reason`: only a test
patch that would not apply counts. A collection or import failure is a grader
that ran and rejected the patch -- a measurement -- and keeps saying so.

    scripts/relabel_ungradeable.py --data-root DIR [--apply]

Without `--apply` it reports what would change and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farm.classify import Label, ungradeable_reason      # noqa: E402

RATIONALE = {
    Label.UNGRADEABLE_A: ("agent A's patch could not be graded: the test patch "
                          "would not apply over its edit"),
    Label.UNGRADEABLE_B: ("agent B's patch could not be graded: the test patch "
                          "would not apply over its edit"),
    Label.UNGRADEABLE_BOTH: ("neither patch could be graded: the test patch would "
                             "not apply over either agent's edit"),
}


def target_label(details: dict) -> Label | None:
    """Which ungradeable label the grader details imply, or None."""
    ua = ungradeable_reason(details.get("a"))
    ub = ungradeable_reason(details.get("b"))
    if ua and ub:
        return Label.UNGRADEABLE_BOTH
    if ua:
        return Label.UNGRADEABLE_A
    if ub:
        return Label.UNGRADEABLE_B
    return None


def correct_attempt(att: dict, details: dict) -> dict | None:
    """Correct one attempt in place. Returns the change, or None if unchanged."""
    want = target_label(details)
    if want is None:
        return None
    # The classifier ranks a missing patch above an ungraded one: "produced
    # nothing" is a stronger statement than "was not measured". The migration
    # obeys the same order, or it invents a correction the live classifier would
    # never make and the archive stops matching the code. Found by the dry run
    # over c02, where three episodes would have gone no_patch_* -> ungradeable_*.
    ev = ((att.get("classification") or {}).get("evidence") or {})
    if any(not (ev.get(side) or {}).get("has_patch", True) for side in ("a", "b")):
        return None
    cls = att.get("classification") or {}
    # The episode manifest carries the label under `classification`; the campaign
    # index carries it at the top level. Read whichever is present.
    cur = att.get("label") or cls.get("label")
    if cur == want.value:
        return None                      # already corrected; idempotent
    change = {"from": cur, "to": want.value}
    att["label_original"] = cur
    att["label"] = want.value
    if cls:
        cls["label_original"] = cls.get("label")
        cls["label"] = want.value
        cls["rationale"] = RATIONALE[want]
        cls["individually_broken"] = False
        cls["genuine_integration_failure"] = False
        for side in ("a", "b"):
            r = (cls.get("evidence") or {}).get(side)
            if isinstance(r, dict):
                r["ungradeable"] = ungradeable_reason(details.get(side))
    return change


def grader_details(episode_dir: Path, attempt_id: str) -> dict:
    out: dict = {}
    res = episode_dir / "attempts" / attempt_id / "results"
    for side in ("a", "b"):
        f = res / f"{side}_alone_own.json"
        try:
            out[side] = json.loads(f.read_text()).get("detail") if f.exists() else None
        except (OSError, json.JSONDecodeError):
            out[side] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    index_path = args.data_root / "manifest.json"
    index = json.loads(index_path.read_text())
    changes = []

    for ep in index.get("episodes", []):
        mp = ep.get("manifest_path")
        if not mp or not Path(mp).exists():
            continue
        ep_manifest = json.loads(Path(mp).read_text())
        ep_dir = Path(mp).parent
        touched = False
        for att in ep_manifest.get("attempts", []):
            if att.get("status") != "completed":
                continue
            ch = correct_attempt(att, grader_details(ep_dir, att.get("attempt_id", "")))
            if ch:
                touched = True
                changes.append({"episode": ep_dir.name, "attempt": att.get("attempt_id"), **ch})
                for ia in ep.get("attempts", []):        # mirror into the index
                    if ia.get("attempt_id") == att.get("attempt_id"):
                        ia["label_original"] = ch["from"]
                        ia["label"] = ch["to"]
        if touched and args.apply:
            Path(mp).write_text(json.dumps(ep_manifest, indent=2) + "\n")

    if args.apply and changes:
        index_path.write_text(json.dumps(index, indent=2) + "\n")

    for c in changes:
        print(f"  {c['episode'][:52]:54s} {str(c['from']):16s} -> {c['to']}")
    print(f"{'applied' if args.apply else 'would change'}: {len(changes)} attempt(s) "
          f"in {args.data_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
