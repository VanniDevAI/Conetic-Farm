# Frozen predictions — model sweep `s01`

**Written 2026-09-08, before any sweep episode ran.** Same discipline as
`docs/EXPECTATIONS.md`: predictions are frozen here and corrected only in dated
appendices, never edited in place.

## What this sweep is for

Appendix E.2 established that `p` — the share of patches that pass their own
tests alone — is the binding constraint, not episode count. A genuine
integration failure needs both patches to pass first, so the reachable rate
scales with `p²`. At `c03`'s measured `p = 0.200`, roughly one episode in 25
reaches the state where a merge can decide anything.

So the question for `c04` is not "how many episodes" but "which model", and the
decision metric is **expected both-pass episodes per dollar**:

```
both_pass_per_dollar  =  p² / cost_per_episode
```

A model twice as good at `p` is four times as good at reaching the measurable
state — which is why a more expensive model can still win, and why a cheaper
model with similar `p` wins decisively.

## The slice

`config/sweep_s01.json`, frozen: 8 `react_hook_form_task` pairs (TypeScript),
2 agents each, **16 patches per model**. Identical for every candidate.

**Caveat recorded up front:** all 19 usable pairs in this repo are
conflicting-stratum — the slice holds no clean-merge gold pairs. `p` is a
property of an individual patch, not of the merge, so this does not bias `p`.
It does mean the sweep says nothing about merge behaviour by stratum, and that
`p` here is measured on a single repository in a single language. `c03` found
`p` varies by repo; this is a slice, not a universal.

## Predictions, per model

`p` is over *graded* patches (Appendix E.3's convention: a patch whose grading
test could not be applied is ungradeable, not failed).

| Model | price in/out per Mtok | predicted `p` | 80% interval | predicted $/episode |
|---|---|---:|---|---:|
| `qwen/qwen3-coder` (incumbent control) | $0.30 / $1.00 | **0.20** | 0.10–0.35 | $0.45 |
| `qwen/qwen3-coder-plus` | $0.65 / $3.25 | **0.35** | 0.20–0.55 | $1.30 |
| `anthropic/claude-sonnet-5` | $2.00 / $10.00 | **0.65** | 0.45–0.85 | $3.50 |

### Where these come from

**Control, `p = 0.20`.** This is `c03`'s measured value on a mixed-language set.
Predicting the same number on a TypeScript-only slice is a real prediction, not
a restatement: `c03`'s four TS episodes produced 1 pass in 7 graded patches
(≈0.14), and the three-repo Python majority carried the rest. If the control
comes back far from 0.20 the slice differs from the campaign, and every other
arm's number has to be read against the control rather than against `c03`.

**`qwen3-coder-plus`, `p = 0.35`.** A larger model of the same family and
training lineage. Coding benchmarks typically separate a family's small and
large variants by less than people expect once an agent scaffold is involved —
the scaffold, tool use and step budget dominate. 0.35 is under a doubling.

**`claude-sonnet-5`, `p = 0.65`.** The ceiling probe. Frontier models solve a
substantial majority of single-feature tasks of this kind in agent harnesses.
The wide interval is honest: this harness's step limit, its submit path (see
`docs/upstream/cooperbench-step-limit-nudge.md`) and the ungradeable failure
mode of E.3 all cap what any model can score here, and none of them are about
model capability.

### What follows if these hold

| Model | `p` | `p²` | $/ep | both-pass per $ | $ per both-pass episode |
|---|---:|---:|---:|---:|---:|
| `qwen3-coder` | 0.20 | 0.040 | $0.45 | 0.089 | $11.3 |
| `qwen3-coder-plus` | 0.35 | 0.123 | $1.30 | 0.094 | $10.6 |
| `claude-sonnet-5` | 0.65 | 0.423 | $3.50 | 0.121 | $8.3 |

**The prediction is that these are close.** `p²` and price rise together, so the
metric does not separate them cleanly — Sonnet wins by ~35% over the incumbent,
not by an order of magnitude. If that holds, `c04` should use the *cheapest*
model whose `p` is not clearly worse, because the money is better spent on
episodes than on per-episode quality.

**What would overturn it:** `p` for Sonnet at or above 0.8 makes frontier the
obvious choice (`p² = 0.64`, $5.5 per both-pass episode). `p` for
`qwen3-coder-plus` at 0.20 — no better than the control — means the open-weight
ladder is flat here and the choice is between the incumbent and frontier only.

## Prediction about the sweep itself

Two of the 24 planned episodes will produce a harness error rather than a
measurement (80% interval 0–5). `react_hook_form` built cleanly in every c03
attempt, so the expected causes are agent-side or grading-side, not image build.

## Stopping rules

* Every arm runs the same 8 episodes or is reported as incomplete, naming which
  episodes are missing.
* Spend is bounded by the provider's own meter, per arm and in total.
* A model that cannot complete an arm within its cap is reported with the
  episodes it did complete and an explicit note that its `p` rests on fewer
  patches — never silently compared against a full arm.
