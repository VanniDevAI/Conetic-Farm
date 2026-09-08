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


def _last_counted_detail(ep: dict) -> dict | None:
    """The last counted attempt's full record, from the episode's own manifest.

    The campaign index carries only attempt_id/status/label/cost per attempt;
    the agents, the classification evidence and the patch paths live beside
    the episode.
    """
    ca = counted_attempts(ep)
    if not ca:
        return None
    mp = ep.get("manifest_path")
    if not mp or not Path(mp).exists():
        return None
    try:
        detail = json.loads(Path(mp).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    want = ca[-1].get("attempt_id")
    for a in reversed(detail.get("attempts", [])):
        if a.get("attempt_id") == want:
            return a
    return None


def _new_files_in_patch(text: str) -> set[str]:
    """Paths a unified diff introduces as NEW files: `--- /dev/null` then `+++ b/X`."""
    new: set[str] = set()
    prev = ""
    for line in text.splitlines():
        if prev.startswith("--- /dev/null") and line.startswith("+++ b/"):
            new.add(line[len("+++ b/"):].strip())
        prev = line
    return new


def merge_evidence(ep: dict) -> dict:
    """The merge outcome and, for a conflict, WHAT conflicted.

    Appendix B.2 warned that diffing whole working trees lets two agents create
    same-named scratch files and manufacture a conflict unrelated to either
    feature.  So every conflicted path is classified from the corpus itself:
    *scratch* if either agent's patch introduces it as a new file, *source* if
    the patch modifies a file that existed at the task base.  Exact, offline,
    and never a filename heuristic.
    """
    att = _last_counted_detail(ep) or {}
    ev = (att.get("classification") or {}).get("evidence") or {}
    merge = ev.get("merge") or {}
    paths = list(merge.get("conflicted_paths") or [])
    new: set[str] = set()
    for ag in att.get("agents") or []:
        pth = (ag.get("patch") or {}).get("path")
        if pth and Path(pth).exists():
            new |= _new_files_in_patch(Path(pth).read_text(errors="replace"))
    scratch = [x for x in paths if x in new]
    source = [x for x in paths if x not in new]
    return {"outcome": merge.get("outcome"), "conflicted_paths": paths,
            "source": source, "scratch": scratch,
            "scratch_only": bool(paths) and not source}


def backfill_ungradeable(detail: dict | None, ep: dict) -> dict | None:
    """Fill in `ungradeable` for a corpus graded before the field existed.

    `c03` and earlier recorded the grader's verdict but not *why* an `error`
    happened, so the reason has to be read back from the grader's own detail
    file (`results/<side>_alone_own.json`).  From `c04` on the classifier writes
    it directly and this is a no-op -- which is the point: one number, whichever
    campaign it comes from.
    """
    if not detail:
        return detail
    ev = (detail.get("classification") or {}).get("evidence") or {}
    if any((ev.get(s) or {}).get("ungradeable") is not None for s in ("a", "b")):
        return detail
    mp = ep.get("manifest_path")
    if not mp:
        return detail
    res = Path(mp).parent / "attempts" / str(detail.get("attempt_id") or "") / "results"
    for side in ("a", "b"):
        r = ev.get(side)
        if r is None:
            continue
        f = res / f"{side}_alone_own.json"
        why = None
        if f.exists():
            try:
                d = json.loads(f.read_text()).get("detail") or {}
                if d.get("patch_apply_failed"):
                    why = ("ungradeable: the test patch could not be applied over the "
                           f"agent's edit ({d.get('reason') or 'patch did not apply'})")
            except (OSError, json.JSONDecodeError):
                why = None
        r["ungradeable"] = why
    return detail


def gradeability(details: list[dict]) -> dict:
    """Split graded patches from ungradeable ones, and report `p` both ways.

    `p` -- the share of patches that pass their own tests alone -- is the
    quantity the whole experiment turns on (Appendix E.2), and it is a ratio of
    *graded* patches.  `c03` found 5 of 30 where the dataset's test patch could
    not be applied over the agent's edit, because the agent had edited the file
    that grades it.  The grader never ran, so those carry no evidence either
    way: counting them as failures depresses `p` with non-observations.

    Both figures are emitted.  `p_graded` excludes them, `p_all` treats them as
    failures the way the classifier's label does, and the report prints both so
    the flattering one is never the only one on the page.

    Takes resolved attempt records rather than episodes: the caller already has
    them via `_last_counted_detail`, and keeping the arithmetic free of disk
    lets it be checked directly.
    """
    graded = passed = ungradeable = 0
    for det in details:
        if not det:
            continue
        ev = (det.get("classification") or {}).get("evidence") or {}
        for side in ("a", "b"):
            r = ev.get(side) or {}
            if not r.get("has_patch"):
                continue
            if r.get("ungradeable"):
                ungradeable += 1
                continue
            graded += 1
            if r.get("own_tests") == "pass":
                passed += 1
    total = graded + ungradeable
    return {
        "graded": graded, "passed": passed, "ungradeable": ungradeable,
        "patches": total,
        "p_graded": (passed / graded) if graded else 0.0,
        "p_all": (passed / total) if total else 0.0,
    }


def cost_per_eligible(ledger: dict, eligible: list) -> float | None:
    """Settled spend divided by eligible episodes; undefined when there are none.

    Settled spend is provider-metered from c02 on (farm/provider.py), so this
    is what the account was actually charged per episode that could have
    answered the question.
    """
    if not eligible:
        return None
    return round(float(ledger.get("settled_usd", 0.0)) / len(eligible), 4)


def both_patches_present(ep: dict) -> bool:
    """Did this episode retain a non-empty patch from BOTH agents?

    This is the real denominator for the headline metric.  A genuine
    integration failure requires both patches to exist and pass alone
    (docs/EXPECTATIONS.md 1), so an episode that lost one agent's patch --
    because the agent wrote nothing, or because the harness discarded what it
    wrote (reports/c02_instrument_notes.md 2) -- could not have produced one
    however the two features interact.
    """
    att = _last_counted_detail(ep)
    if att is None:
        return False
    agents = att.get("agents") or []
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

    grad = gradeability([backfill_ungradeable(_last_counted_detail(e), e) for e in episodes])
    if grad["patches"]:
        w("## Gradeability, and the pass rate `p`\n")
        w("`p` -- the share of patches that pass their own tests alone -- is the "
          "quantity this design turns on: a genuine integration failure needs both "
          "patches to pass first, so the reachable rate scales with `p`&sup2;. It is a "
          "ratio of *graded* patches, and not every patch gets graded: an agent that "
          "edits the test file grading it makes the dataset's test patch unappliable, "
          "so the grader never runs and the patch is shown nothing either way.\n")
        w("| | |")
        w("|---|---:|")
        w(f"| Patches with content | {grad['patches']} |")
        w(f"| **…graded** | **{grad['graded']}** |")
        w(f"| …ungradeable (agent edited its own grading test) | {grad['ungradeable']} |")
        w(f"| …that passed alone | {grad['passed']} |")
        w(f"| **`p` over graded patches** | **{grad['p_graded']:.3f}** |")
        w(f"| `p` counting ungradeable as failures | {grad['p_all']:.3f} |")
        w(f"| implied `p`&sup2; | {grad['p_graded'] ** 2:.3f} |")
        w("")
        w("Both figures are given. The classifier's labels use the second — an "
          "unrunnable patch is not a passing one — but the first is what the "
          "evidence supports, and reporting only one of them would be a choice "
          "about which number flatters.\n")
    w("## Eligibility, integration failures, and conflicts\n")
    w("An episode is *eligible* when it retained a non-empty patch from both "
      "agents; only an eligible episode can show a genuine integration failure. "
      "Conflicted paths are classified from the corpus: **source** if the patch "
      "modifies a file that existed at the task base, **scratch** if either "
      "agent's patch introduces the path as a new file (Appendix B.2).\n")
    evs = [(e, merge_evidence(e)) for e in eligible]
    conflicts = [(e, ev) for e, ev in evs if ev["outcome"] == "conflict"]
    on_source = [x for x in conflicts if x[1]["source"]]
    scratch_only = [x for x in conflicts if x[1]["scratch_only"]]
    cpe = cost_per_eligible(ledger, eligible)
    w("| | |")
    w("|---|---:|")
    w(f"| **Eligible episodes** (both patches retained) | **{len(eligible)}** |")
    w(f"| **Genuine integration failures** | **{len(genuine)}** |")
    w(f"| Merge conflicts among eligible episodes | {len(conflicts)} |")
    w(f"| …touching at least one real source file | {len(on_source)} |")
    w(f"| …confined to agent scratch files | {len(scratch_only)} |")
    w(f"| Spend as settled in the ledger | ${ledger['settled_usd']:.2f} |")
    w(f"| **Cost per eligible episode** | **"
      f"{'undefined (no eligible episodes)' if cpe is None else f'${cpe:.2f}'}** |")
    w("")
    if eligible:
        w("| Episode | Stratum | Label | Merge | Conflicted paths |")
        w("|---|---|---|---|---|")
        for e, ev in evs:
            paths = ", ".join([f"`{x}` (source)" for x in ev["source"]]
                              + [f"`{x}` (scratch)" for x in ev["scratch"]]) or "—"
            w(f"| `{e['episode_id']}` | {e.get('stratum')} | `{final_label(e)}` | "
              f"{ev['outcome'] or '?'} | {paths} |")
        w("")

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
