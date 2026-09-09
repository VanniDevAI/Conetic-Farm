#!/usr/bin/env python3
"""Re-decide every episode's failure class from what is already on disk.

The rule changed: a clean merge with a failing combined suite is only
`semantic` when every lane was green on its own branch. Nothing about the runs
changed, so nothing is re-run -- the merge outcome, the combined suite and the
per-lane results are all banked, and the class is a function of the three.

Records that already agree are left alone, so the index does not grow a line
for an episode that did not change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.episode_record import EPISODES_DIR, write_episode   # noqa: E402
from farm.failure_class import classify, stealth              # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="", help="only ids starting with this")
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    changed = 0
    for path in sorted(EPISODES_DIR.glob(f"{args.prefix}*.json")):
        rec = json.loads(path.read_text())
        # Only records whose product outcome is "two lanes and a merged tree".
        # A seam episode records `a_alone`/`b_alone`/`integrated` instead: its
        # two lanes live in different repositories, there is no combined suite
        # in this sense, and reading a missing `merged_suite` as "not run" would
        # strip the class off CE-004, which is correct as it stands.
        po = rec["product_outcome"]
        if "merged_suite" not in po or "both_pass" not in po:
            print(f"{rec['id']}: skipped, not a two-lane merged-tree episode "
                  f"(keys: {sorted(po)})")
            continue
        merge = (rec.get("git_outcome") or {}).get("outcome")
        merged = rec["product_outcome"].get("merged_suite")
        green = bool(rec["product_outcome"].get("both_pass"))
        cls, why = classify(merge, merged, green)
        st = stealth(cls, merge, green)
        if cls == rec["failure_class"] and st["flag"] == rec["stealth"].get("flag"):
            continue
        print(f"{rec['id']}: class {rec['failure_class']!r} -> {cls!r}; "
              f"stealth {rec['stealth'].get('flag')!r} -> {st['flag']!r}")
        print(f"    because: {why}")
        if args.apply:
            rec["failure_class"] = cls
            rec["failure_class_why"] = why
            st["previously"] = {"flag": rec["stealth"].get("flag"),
                                "why": rec["stealth"].get("why")}
            rec["stealth"] = st
            write_episode(rec)
        changed += 1
    print(f"{changed} record(s) {'rewritten' if args.apply else 'would change'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
