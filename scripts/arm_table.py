#!/usr/bin/env python3
"""The two-column table for a two-arm run, from the episode records only.

Reads what was banked, not what the run printed, so the table and the corpus
cannot drift apart. Everything it reports is a quantity the design can answer
at six lanes an arm; it prints the significance alongside so nobody has to
guess whether a difference at this size means anything (it does not).
"""

from __future__ import annotations

import argparse
import json
import sys
from math import comb
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EPISODES = REPO_ROOT / "farm" / "episodes"

TRIVIAL_LINES = 10   # below this a "pass" says nothing about the feature


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n, r1, c1 = a + b + c + d, a + b, a + c
    if not n:
        return 1.0
    def p(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
    obs = p(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs + 1e-12)


def load(prefix: str) -> list[dict]:
    eps = [json.loads(p.read_text()) for p in sorted(EPISODES.glob(f"{prefix}*.json"))]
    if not eps:
        sys.exit(f"no episode records match {prefix}*")
    return eps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True, help="episode id prefix, e.g. c06b-")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    eps = load(args.prefix)
    arms: dict[str, dict] = {}
    for ep in eps:
        arm = ep["corpus"]["arm"]
        a = arms.setdefault(arm, {
            "episodes": 0, "lanes": 0, "own_pass": 0, "both_pass": 0,
            "graded": 0, "salvaged": 0, "trivial_pass": 0, "cost": 0.0,
            "conv": 0, "semantic": 0, "textual": 0, "changed_lines": 0,
            "positions": [], "detail": [],
        })
        a["episodes"] += 1
        a["lanes"] += len(ep["lanes"])
        a["cost"] += (ep["cost"] or {}).get("usd") or 0.0
        a["both_pass"] += 1 if ep["product_outcome"]["both_pass"] else 0
        a["conv"] += sum(len(v) for v in ep["convention_graders"].values()
                         if isinstance(v, list))
        if ep["failure_class"] == "semantic":
            a["semantic"] += 1
        elif ep["failure_class"] == "textual":
            a["textual"] += 1
        a["positions"].append(ep.get("run_position"))
        for lane in ep["lanes"]:
            lines = lane.get("changed_lines", 0)
            a["changed_lines"] += lines
            if lane.get("salvaged"):
                a["salvaged"] += 1
            if lane.get("alone_suite") is not None:
                a["graded"] += 1
            if lane.get("alone_suite") == "pass":
                a["own_pass"] += 1
                if lines < TRIVIAL_LINES:
                    a["trivial_pass"] += 1
            a["detail"].append({
                "episode": ep["id"], "lane": lane["agent"],
                "alone": lane.get("alone_suite"), "changed_lines": lines,
                "salvaged": bool(lane.get("salvaged")),
                "run_position": ep.get("run_position"),
                "lane_position": lane.get("lane_position"),
            })

    names = sorted(arms)
    if args.json:
        print(json.dumps(arms, indent=2))
        return 0

    def rate(n, d):
        return f"{n} of {d} ({n/d:.2f})" if d else "—"

    rows = [
        ("own-tests pass", lambda a: rate(a["own_pass"], a["lanes"])),
        ("both-pass", lambda a: rate(a["both_pass"], a["episodes"])),
        ("cost per passing lane",
         lambda a: f"${a['cost']/a['own_pass']:.4f}" if a["own_pass"] else "—"),
        ("semantic failures shipped", lambda a: str(a["semantic"])),
        ("convention hits", lambda a: str(a["conv"])),
    ]
    extra = [
        ("lanes reaching the grader", lambda a: rate(a["graded"], a["lanes"])),
        ("patches salvaged, not pushed", lambda a: str(a["salvaged"])),
        ("passes on under 10 changed lines", lambda a: str(a["trivial_pass"])),
        ("changed lines shipped", lambda a: str(a["changed_lines"])),
        ("textual conflicts", lambda a: str(a["textual"])),
        ("billed", lambda a: f"${a['cost']:.4f}"),
        ("mean run position",
         lambda a: f"{sum(p for p in a['positions'] if p)/len(a['positions']):.2f}"
         if all(a["positions"]) else "—"),
    ]

    width = max(len(t) for t, _ in rows + extra)
    print(f"| {'':{width}} | " + " | ".join(f"**{n}**" for n in names) + " |")
    print(f"|{'-'*(width+2)}|" + "|".join("---" for _ in names) + "|")
    for title, fn in rows:
        print(f"| {title:{width}} | " + " | ".join(fn(arms[n]) for n in names) + " |")
    print()
    print(f"| {'':{width}} | " + " | ".join(names) + " |")
    print(f"|{'-'*(width+2)}|" + "|".join("---" for _ in names) + "|")
    for title, fn in extra:
        print(f"| {title:{width}} | " + " | ".join(fn(arms[n]) for n in names) + " |")

    if len(names) == 2:
        x, y = (arms[n] for n in names)
        p = fisher_two_sided(x["own_pass"], x["lanes"] - x["own_pass"],
                             y["own_pass"], y["lanes"] - y["own_pass"])
        gap = abs(x["own_pass"] / x["lanes"] - y["own_pass"] / y["lanes"])
        print(f"\nown-tests pass gap {gap:.2f}; Fisher two-sided p = {p:.3f} "
              f"at {x['lanes']} and {y['lanes']} lanes")
        pe = fisher_two_sided(x["both_pass"], x["episodes"] - x["both_pass"],
                              y["both_pass"], y["episodes"] - y["both_pass"])
        print(f"both-pass: Fisher two-sided p = {pe:.3f} at "
              f"{x['episodes']} and {y['episodes']} episodes")

    print("\nper lane:")
    for n in names:
        for d in arms[n]["detail"]:
            flag = " salvaged" if d["salvaged"] else ""
            print(f"  {n:7} {d['episode']:20} {d['lane']:6} "
                  f"alone={str(d['alone']):5} lines={d['changed_lines']:4} "
                  f"pos={d['run_position']}/{d['lane_position']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
