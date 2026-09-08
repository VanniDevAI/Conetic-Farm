# Model sweep `s01` — report

Run 2026-09-08 against `config/sweep_s01.json`, frozen before any episode, with
per-model `p` predictions frozen in `docs/SWEEP_S01_PREDICTIONS.md`. Slice: 8
`react_hook_form` (TypeScript) pairs, 2 agents each. Costs are the provider's
own meter, never a token estimate.

## Result

| | `qwen/qwen3-coder` | `anthropic/claude-sonnet-5` |
|---|---:|---:|
| Episodes run | 8 of 8 | **3 of 8** |
| Patches with content | 16 | 6 |
| …graded | 14 | 5 |
| …ungradeable | 2 | 1 |
| …passed alone | 4 | 3 |
| **observed `p`** | **0.286** | **0.600** |
| 95% CI (Wilson) | 0.117 – 0.546 | 0.231 – 0.882 |
| `p²` | 0.0816 | 0.3600 |
| Total cost | $3.11 | $11.84 |
| **cost per episode** | **$0.389** | **$3.946** |
| **both-pass episodes per $** | **0.2100** | 0.0912 |
| Integration failures — textual | **1** | 0 |
| Integration failures — semantic | **0** | **0** |

**The Sonnet arm is incomplete: 3 episodes of 8.** Its `p` rests on 5 graded
patches, and its interval is correspondingly wide. It is reported as a ceiling
probe, not as an equal arm.

## Predictions versus outcome

Both frozen `p` predictions held.

| | predicted `p` | 80% interval | actual | inside? |
|---|---:|---|---:|:--:|
| `qwen3-coder` | 0.20 | 0.10–0.35 | 0.286 | yes |
| `claude-sonnet-5` | 0.65 | 0.45–0.85 | 0.600 | yes |

**The decision metric came out the other way round.** The prediction was that
the candidates would land close with Sonnet ~35% ahead (0.121 vs 0.089
both-pass per dollar). Actual: the control wins by **2.3×**.

Nothing about `p` caused that. Two smaller misses compounded:

* the control's `p` landed at the top of its interval (0.286 against 0.20), which
  is squared in the metric — `p²` came in at 0.0816 against a predicted 0.040,
  twice as good;
* the control was cheaper than predicted ($0.389 against $0.45) and Sonnet was
  dearer ($3.946 against $3.50), widening the price ratio to **10.15×**.

`p²` rose 4.4× from control to Sonnet; price rose 10.15×. Cost outran quality.

## What would have to be true for Sonnet to win

At a 10.15× price ratio, Sonnet needs `p > 3.185 × p_control`.

| Holding fixed | Threshold | Observed | Verdict |
|---|---:|---:|---|
| control at 0.286 | Sonnet needs `p > 0.910` | 0.600 (CI to 0.882) | **loses even at its CI upper bound** |
| Sonnet at 0.600 | control needs `p > 0.188` | 0.286 (CI from 0.117) | control wins unless its true `p` is below 0.188 |

So the conclusion is **robust to Sonnet's uncertainty and sensitive to the
control's**. The control's interval reaches down to 0.117, and the band
0.117–0.188 would flip the result. Two independent readings put it above that
band — 0.286 here and 0.200 in `c03` — but 14 graded patches is not many, and
this is the honest limit of the claim.

## Recommendation for `c04`

**Use `qwen/qwen3-coder`.** It buys 2.3× more both-pass episodes per dollar,
and Sonnet cannot close a 10.15× price gap on a quality gap that squares to
4.4×. At $0.389 an episode, the same money that bought 3 Sonnet episodes buys
30 control episodes.

Three things qualify that, and the third is the one that matters:

1. **The Sonnet arm is 3 episodes.** Completing it to 8 (~$32) would tighten its
   interval. It would not change the recommendation unless its `p` rose above
   0.910, which its own CI excludes.
2. **Cheap both-pass episodes may be easier episodes.** The metric rewards
   reaching the both-pass state cheaply, but a weaker model reaches it only on
   pairs it can solve — plausibly the pairs where features interact least. More
   episodes of a weaker model may therefore buy a *biased* sample of the state
   we care about. Nothing here measures that, and it cannot be dismissed.
3. **Neither arm produced a semantic integration failure.** Zero, in 11
   episodes across two models, on top of zero in `c01`–`c03`. The one genuine
   failure found is textual — a refused merge, which `git` already reports for
   free.

## The head-to-head, and what it does to the bridge candidate

Episode 2 of both arms is `react_hook_form/153 f1+f2`, the pair that produced
the project's first genuine integration failure.

| | `qwen3-coder` | `claude-sonnet-5` |
|---|---|---|
| A alone | pass | pass |
| B alone | **pass** | **fail** |
| Merge | **conflict** on `src/logic/createFormControl.ts` | **clean**, no conflicted paths |
| Label | `integration_failure_merge` | `b_broken` |

Both models' agents reached for `handleSubmit` inside `createFormControl.ts`,
so a claim map would flag the contested symbol in both runs. Only one run's
edits actually collided.

That narrows what this bridge-replay candidate can demonstrate: **that a claim
map would correctly identify the contested symbol, not that a collision was
inevitable.** A replay here should be judged on whether it surfaces the shared
claim, not on whether it "prevents" a conflict a different model never
produced. Recorded as `counter_evidence` on the banked entry.

Also settled by the same comparison: Sonnet's B edited the graded test file too
and still failed, so editing the grading test is not the mechanism behind
`qwen3-coder`'s passes.

## The finding that outranks the model choice

Four campaigns and a sweep — 71 episodes, two models — have produced **one**
genuine integration failure, and it is textual.

The semantic class, where the merge is clean and the combined tests fail, is
what a claim-map engine exists to catch, and it has not been observed once.
Choosing a model to buy more both-pass episodes per dollar is the right move
for the sample size problem, but it is worth being explicit that no amount of
the *current* design has yet produced an instance of the phenomenon the engine
targets. That is a statement about this benchmark and this task selection, not
about whether the phenomenon is real — but it is the thing to fix next, ahead
of any further model tuning.
