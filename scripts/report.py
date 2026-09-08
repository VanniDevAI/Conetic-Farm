#!/usr/bin/env python3
"""Produce the campaign report from the manifest and ledger.

Reads only what was written during the run -- it never re-derives a label or
re-runs a test, so the report cannot disagree with the corpus.

    scripts/report.py --campaign c01 > reports/campaign_c01.md
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm import env as farm_env          # noqa: E402
from farm.classify import Label           # noqa: E402

GENUINE = {Label.INTEGRATION_FAILURE_TESTS.value, Label.INTEGRATION_FAILURE_MERGE.value}
BROKEN = {Label.A_BROKEN.value, Label.B_BROKEN.value, Label.BOTH_BROKEN.value}
NO_PATCH = {Label.NO_PATCH_A.value, Label.NO_PATCH_B.value, Label.NO_PATCH_BOTH.value}


def load(data_root: Path, campaign: str) -> tuple[list[dict], dict]:
    index = json.loads((data_root / "manifest.json").read_text())
    episodes = [e for e in index["episodes"] if e.get("campaign") == campaign]
    ledger_path = data_root / "ledger.jsonl"
    settled, notes = 0.0, []
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                notes.append("ledger has a torn line (killed mid-write)")
                continue
            if rec.get("kind") == "settle":
                settled += float(rec.get("amount_usd", 0.0))
    return episodes, {"settled_usd": settled, "notes": notes}


def counted_attempts(ep: dict) -> list[dict]:
    return [a for a in ep.get("attempts", []) if a.get("disposition") == "counted"]


def final_label(ep: dict) -> str | None:
    """The last counted attempt decides the episode's label.

    An attempt that errored carries no classification at all -- run.py leaves
    `classification: None` and sets `status: "error"`.  Reading only the label
    reported such an episode as an ordinary unlabelled one and kept it in the
    rate denominators, silently inflating the number of episodes an outcome was
    "out of".  A harness error is an absence of measurement, not a measurement.
    """
    ca = counted_attempts(ep)
    if not ca:
        return None
    last = ca[-1]
    if last.get("status") == "error" or (
            last.get("label") is None and last.get("classification") is None):
        return Label.HARNESS_ERROR.value
    return last.get("label")


def both_patches_present(ep: dict) -> bool:
    """Did this episode retain a non-empty patch from BOTH agents?

    This is the real denominator for the headline metric.  A genuine
    integration failure requires both patches to exist and pass alone
    (docs/EXPECTATIONS.md 1), so an episode that lost one agent's patch --
    because the agent wrote nothing, or because the harness discarded what it
    wrote (reports/c02_instrument_notes.md 2) -- could not have produced one
    however the two features interact.
    """
    # The campaign index records only attempt_id/status/label/cost per attempt;
    # per-agent detail lives in the episode's own manifest, so read that.
    ca = counted_attempts(ep)
    if not ca:
        return False
    mp = ep.get("manifest_path")
    if not mp or not Path(mp).exists():
        return False
    try:
        detail = json.loads(Path(mp).read_text())
    except (OSError, json.JSONDecodeError):
        return False
    attempts = [a for a in detail.get("attempts", [])
                if a.get("attempt_id") == ca[-1].get("attempt_id")]
    if not attempts:
        return False
    agents = attempts[-1].get("agents") or []
    if len(agents) < 2:
        return False
    return all((a.get("patch") or {}).get("bytes", 0) > 0 for a in agents)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaign", default="c01")
    ap.add_argument("--data-root", default=os.environ.get("FARM_DATA_ROOT", "/home/user/farm-data"))
    ap.add_argument("--expected", type=int, default=2,
                    help="frozen prediction for genuine integration failures")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    episodes, ledger = load(data_root, args.campaign)
    if not episodes:
        print(f"no episodes for campaign {args.campaign!r} under {data_root}")
        return 1

    labels = Counter(final_label(e) for e in episodes)
    costs = [sum(a.get("cost_usd") or 0.0 for a in e.get("attempts", [])) for e in episodes]
    total_cost = sum(costs)
    genuine = [e for e in episodes if final_label(e) in GENUINE]
    broken = [e for e in episodes if final_label(e) in BROKEN]
    nopatch = [e for e in episodes if final_label(e) in NO_PATCH]
    harness = [e for e in episodes if final_label(e) == Label.HARNESS_ERROR.value]
    rateable = [e for e in episodes if final_label(e) != Label.HARNESS_ERROR.value]

    out: list[str] = []
    w = out.append
    w(f"# Campaign `{args.campaign}` — report\n")
    w(f"Generated {datetime.now(timezone.utc).isoformat().replace('+00:00','Z')} "
      f"from `{data_root}/manifest.json`. Labels are read from the corpus, never "
      f"recomputed.\n")

    w("## Headline\n")
    w("| | |")
    w("|---|---:|")
    eligible = [e for e in rateable if both_patches_present(e)]
    w(f"| Episodes attempted | {len(episodes)} |")
    w(f"| …of which harness errors (no measurement) | {len(harness)} |")
    w(f"| **Episodes that produced a measurement** | **{len(rateable)}** |")
    w(f"| **…of which retained BOTH patches** | **{len(eligible)}** |")
    w(f"| Total cost | ${total_cost:.2f} |")
    w(f"| Cost per episode (mean) | ${total_cost/len(episodes):.3f} |")
    if costs:
        w(f"| Cost per episode (median) | ${statistics.median(costs):.3f} |")
        w(f"| Cost per episode (max) | ${max(costs):.3f} |")
    w(f"| **Genuine integration failures** | **{len(genuine)}** |")
    if genuine:
        w(f"| Cost per verified integration failure | ${total_cost/len(genuine):.2f} |")
    else:
        w("| Cost per verified integration failure | undefined (none found) |")
    w(f"| Ledger settled total | ${ledger['settled_usd']:.2f} |")
    w("")

    w("## Expected versus actual\n")
    w(f"Frozen prediction (`docs/EXPECTATIONS.md`, written before any run): "
      f"**{args.expected}** genuine integration failures from the first 20 episodes, "
      f"80% interval 0–5.\n")
    w(f"Actual: **{len(genuine)}**.\n")
    w(f"**Against the right denominator.** The prediction is stated for 20 "
      f"episodes. This campaign produced a measurement in **{len(rateable)}** of "
      f"them, and only **{len(eligible)}** retained a patch from both agents. A "
      f"genuine integration failure is impossible without both, so the effective "
      f"sample is {len(eligible)}, not {len(episodes)}. Zero found in "
      f"{len(eligible)} episodes neither confirms nor refutes a prediction made "
      f"for 20.\n")
    delta = len(genuine) - args.expected
    if delta == 0:
        w("The point estimate was exact.\n")
    else:
        w(f"Difference: {delta:+d} against a point estimate of {args.expected}. "
          f"{'Within' if 0 <= len(genuine) <= 5 else 'Outside'} the frozen 80% interval.\n")

    w("## Outcome breakdown\n")
    w("| Label | Count | Meaning |")
    w("|---|---:|---|")
    meanings = {
        Label.BOTH_PASS_MERGE_PASSES.value: "clean cooperation",
        Label.INTEGRATION_FAILURE_TESTS.value: "**genuine integration failure** (semantic)",
        Label.INTEGRATION_FAILURE_MERGE.value: "**genuine integration failure** (merge conflict)",
        Label.A_BROKEN.value: "individually broken patch (A)",
        Label.B_BROKEN.value: "individually broken patch (B)",
        Label.BOTH_BROKEN.value: "individually broken patches (both)",
        Label.NO_PATCH_A.value: "agent A produced nothing",
        Label.NO_PATCH_B.value: "agent B produced nothing",
        Label.NO_PATCH_BOTH.value: "neither agent produced a patch",
        Label.HARNESS_ERROR.value: "infrastructure fault (excluded from rates)",
    }
    for lab, n in labels.most_common():
        w(f"| `{lab}` | {n} | {meanings.get(lab, '')} |")
    w("")
    w(f"Individually broken patches: **{len(broken)}** — these are *not* "
      f"integration failures, whatever the merge did.")
    w(f"Episodes with a missing patch: **{len(nopatch)}**.")
    w(f"Harness errors excluded from rates: **{len(harness)}** "
      f"(of {len(episodes)}); rates below are over {len(rateable)} episodes.\n")

    w("## By stratum\n")
    w("| Stratum | Episodes | Genuine integration failures | Rate |")
    w("|---|---:|---:|---:|")
    for stratum in ("conflicting", "compatible", "control"):
        rows = [e for e in rateable if e.get("stratum") == stratum]
        g = [e for e in rows if final_label(e) in GENUINE]
        rate = f"{len(g)/len(rows):.0%}" if rows else "—"
        w(f"| {stratum} | {len(rows)} | {len(g)} | {rate} |")
    w("")
    ctrl_fail = [e for e in rateable
                 if e.get("stratum") == "control" and final_label(e) in GENUINE]
    if ctrl_fail:
        w(f"**{len(ctrl_fail)} failure(s) in the control stratum.** Controls are "
          f"separation controls, not disjoint ones (no disjoint pair exists in this "
          f"dataset), so this is not automatically a harness fault — but it is the "
          f"first thing to investigate:\n")
        for e in ctrl_fail:
            w(f"* `{e['episode_id']}`")
        w("")

    w("## By language\n")
    w("| Language | Episodes | Genuine integration failures |")
    w("|---|---:|---:|")
    for lang in sorted({e.get("language") for e in rateable}):
        rows = [e for e in rateable if e.get("language") == lang]
        w(f"| {lang} | {len(rows)} | {len([e for e in rows if final_label(e) in GENUINE])} |")
    w("\nLanguage counts are descriptive. The plan was not designed to support "
      "attributing a difference to language.\n")

    w("## Manifest of episode folders\n")
    w("| # | Episode | Stratum | Lang | Label | Attempts | Cost | Directory |")
    w("|---:|---|---|---|---|---:|---:|---|")
    for i, e in enumerate(sorted(episodes, key=lambda x: x["episode_id"]), 1):
        c = sum(a.get("cost_usd") or 0.0 for a in e.get("attempts", []))
        w(f"| {i} | `{e['episode_id']}` | {e.get('stratum')} | {e.get('language')} "
          f"| `{final_label(e)}` | {len(e.get('attempts', []))} | ${c:.3f} "
          f"| `{e.get('episode_dir')}` |")
    w("")

    discarded = [(e["episode_id"], a) for e in episodes for a in e.get("attempts", [])
                 if a.get("disposition") != "counted"]
    w(f"Attempts retained but not counted: **{len(discarded)}**"
      + (" — all still on disk." if discarded else "."))
    for eid, a in discarded:
        w(f"* `{eid}` / {a['attempt_id']}: {a.get('disposition_reason') or 'no reason recorded'}")
    w("")

    unpriced = [(e["episode_id"], ag.get("role"), ag.get("cost_source"))
                for e in episodes for a in e.get("attempts", [])
                for ag in a.get("agents", [])
                if str(ag.get("cost_source", "")).startswith("UNPRICED")]
    if unpriced:
        w("## Cost integrity warnings\n")
        w("Agents whose spend could not be priced — their tokens are **not** in the "
          "totals above, so the real cost is higher than reported:\n")
        for eid, role, src in unpriced:
            w(f"* `{eid}` agent {role}: {src}")
        w("")
    for n in ledger["notes"]:
        w(f"> ledger note: {n}")

    print(farm_env.redact("\n".join(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
