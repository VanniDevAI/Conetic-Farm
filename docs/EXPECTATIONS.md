# Frozen expectations — first 20 episodes

**Written before any agent has been run. Not to be edited after the first run
starts.** Amendments, if any, go in a dated appendix at the bottom with the
reason; the original numbers stay untouched.

Frozen: 2026-09-07, before campaign `c01`.

---

## 1. The headline prediction

> **Genuine integration failures from the first 20 episodes: 2.**
> 80% interval: **0 to 5**. 95% interval: **0 to 8**.

"Genuine integration failure" means what `docs/DESIGN.md` §6 defines and nothing
looser: **agent A's patch passes A's tests alone, agent B's patch passes B's
tests alone, and the merge of the two fails** — either by conflicting
(`integration_failure_merge`) or by failing tests once merged
(`integration_failure_tests`).

Sub-predictions, same freeze:

| Quantity | Point | 80% interval |
|---|---:|---|
| Genuine integration failures (total) | **2** | 0 – 5 |
| …of which merge conflicts | 1 | 0 – 3 |
| …of which semantic (merged tests fail) | 1 | 0 – 3 |
| Episodes where **both** patches pass alone | 4 | 2 – 8 |
| Episodes with ≥1 individually broken patch | 15 | 11 – 18 |
| Episodes with no patch from ≥1 agent | 2 | 0 – 5 |
| Harness errors (excluded from rates) | 2 | 0 – 6 |
| Total campaign cost | $14 | $6 – $34 |
| Cost per verified integration failure | $7 | $3 – ∞ (if zero found) |

---

## 2. Where these numbers come from

### 2.1 The binding constraint is `p²`, not the conflict rate

A genuine integration failure requires *both* patches to be individually
correct. If a single agent solves a single feature with probability `p`, then
episodes eligible to show an integration failure arrive at roughly `p²`.

That squaring is the whole story. It means a weaker agent does not merely find
fewer integration failures — it suppresses them **quadratically**, while still
costing a full episode to run. Most episodes will end as
`a_broken` / `b_broken` / `both_broken`: real data, retained, but not the signal.

### 2.2 Estimating `p` for Qwen3-Coder

Anchors from the harness's own `docs/BENCHMARK_RESULTS.md` (10-pair `core`
subset, team setting, frontier models):

| Framework + model | Reported pass | Passes that were *merge* passes |
|---|---|---|
| `mini_swe_agent_v2` + gpt-5.5 | 6/10 | 5/10 |
| `codex` + gpt-5.5 | 5/10 | 3/10 |
| `claude_code` + claude-sonnet-4-5 | 5/10 | 2/10 |
| `openhands_sdk` + gpt-5.5 | 4/10 | 1/10 |

(The second column strips the `lead-alone` fallback — see §4.1. It is the column
that corresponds to what we measure.)

CooperBench's paper reports ~25% two-agent success against ~50% solo, so
per-feature `p` for a frontier model is around 0.5–0.65.

Qwen3-Coder is a strong open-weight coder model but below that frontier on
agentic SWE work, and it is being run through an adapter tuned for *small*
context (`docs/QWEN_LOCAL.md` caps qwen profiles at `max_output_tokens=4096`
and strips part of the tool surface). Estimate:

> **`p` ≈ 0.45**, with real uncertainty 0.25 – 0.60.

So `p²` ≈ **0.20**, range 0.06 – 0.36 → **4 of 20 episodes** eligible, range 1–7.

### 2.3 Conditional failure probability, given both patches pass alone

Per planned stratum (§3), the probability the merge then fails:

| Stratum | n | P(merge fails \| both pass alone) | Reasoning |
|---|---:|---:|---|
| `conflicting` | 10 | 0.55 | Gold patches textually conflict, so both features live in the same code region. Agent patches will usually overlap too — but not always: agents write differently-shaped patches than the gold. |
| `compatible` | 6 | 0.15 | Gold patches merge cleanly. Residual risk is semantic: shared state, a shared helper, or one agent refactoring something the other depends on. |
| `control` | 4 | 0.05 | Features hand-checked as touching disjoint modules. Anything here is a signal about the agents or the harness, not the task. |

Combining with `p² = 0.20`:

```
conflicting  10 × 0.20 × 0.55 = 1.10
compatible    6 × 0.20 × 0.15 = 0.18
control       4 × 0.20 × 0.05 = 0.04
                        total ≈ 1.32
```

Round up to **2** to account for the harness's naive-merge step being stricter
than a careful human merge, and because `p` may be higher than estimated on the
easier tasks in the plan. The interval is wide and asymmetric because the whole
quantity is a product of three uncertain factors.

### 2.4 Cost

`mini_swe_agent_v2` + gpt-5.5 cost **$13.37 for 10 pairs** (~$1.34/pair). Token
volume is roughly 400k input + ~50k output per agent per task.

Qwen3-Coder via OpenRouter is materially cheaper per token than gpt-5.5.
At ~2 agents × 400k input + 50k output, and assuming OpenRouter list pricing for
Qwen3-Coder, an episode should land near **$0.40–$0.90**, plus the A-alone,
B-alone and merged test runs (compute only, no tokens).

> 20 episodes × ~$0.55 ≈ **$11**, plus retries and discarded attempts ≈ **$14**.

**This figure is unverified.** OpenRouter is not reachable from this environment,
so its live price table could not be read. The first three episodes will be run
with per-episode cost printed and this estimate corrected before continuing.

---

## 3. The frozen task plan

20 episodes, stratified, seeded, and written to `config/task_plan.json` before
the first run:

* **10 `conflicting`** — gold patches textually conflict, neither gold patch
  fails to apply.
* **6 `compatible`** — gold patches merge cleanly.
* **4 `control`** — hand-checked as touching disjoint modules.

Strata are interleaved in execution order, so stopping early (budget, failure)
still leaves a balanced sample rather than 10 conflicting episodes and nothing else.

### 3.1 A constraint on language coverage, recorded up front

The task asked to start from the TypeScript slice. The TypeScript slice is
`react_hook_form_task`, and it is small and lopsided:

* 2 tasks, 25 feature pairs total.
* 19 pairs conflict at gold level.
* 6 pairs are labelled "clean" **only because a gold patch failed to apply** —
  they are not clean merges and are excluded.
* **Genuinely clean TypeScript pairs: 0.**

So the TypeScript slice cannot supply `compatible` or `control` episodes at all.
The plan therefore draws conflicting episodes from TypeScript where possible and
takes compatible/control episodes from the Python repos, and every episode
records its language. Any cross-language comparison in the final report is
descriptive only — the design does not support attributing a difference to
language.

---

## 4. Known biases, recorded *before* they can be rationalised away

### 4.1 CooperBench's own eval would inflate the pass rate

The harness's documented eval policy is `identical → naive merge → lead's patch
alone` (`docs/BENCHMARK_RESULTS.md`). The last step scores an episode as a
**pass** when the merge *conflicted*, provided one agent's patch alone happens
to satisfy both feature suites.

That policy is defensible for measuring "did the team ship the features". It is
exactly wrong for measuring integration failure: it converts a merge conflict
into a pass. In the results table above, it turns 1/10 into 4/10 for
`openhands_sdk`.

**Mitigation:** we do not use `cooperbench eval`'s verdict. We compute our own
A-alone / B-alone / merged triad (`farm/grade.py`, `farm/classify.py`) and label
from that. CooperBench's own `eval.json` is still retained per episode, so the
two can be compared — and the disagreement rate is itself reported.

### 4.2 The gold conflict labels are textual, not semantic

`dataset/gold_conflict_report.json` marks 499/652 pairs (76.5%) as conflicting.
That is `git merge` on the two **gold** patches. It predicts textual conflict
between *gold* patches, not between *agent* patches, and it says nothing about
semantic interference. It is used to stratify and never as ground truth.

### 4.3 Six pairs carry a mislabel in the source data

Six pairs are recorded as `has_conflict: false` while also carrying
`patch1_apply_failed` or `patch2_apply_failed`. They are not clean merges; one
gold patch simply never applied. All six are in `react_hook_form_task/task85`.
They are excluded from every stratum (`farm/plan.py`).

### 4.4 The sandbox base image is not the upstream one

Registry blob downloads are blocked in this environment, so the base layer is
imported from the host rootfs rather than pulled as `node:22-slim`, and the
Dockerfile's `apt-get` layer is replaced by an assertion (see
`scripts/build_task_image.sh`). Node major version matches; the rest of the
userland is Ubuntu 24.04 rather than Debian slim. Recorded per episode in
`base/image.json`. A test that depends on the base distro would behave
differently here.

### 4.5 Small-context profile changes the agent, not just the model

`docs/QWEN_LOCAL.md` shows the `claude_code` adapter applying a reduced tool
surface and a 4096-token output cap to any model whose name contains `qwen`.
Whatever we measure is that *configuration*, not Qwen3-Coder at full strength.
The adapter and its profile are recorded in every episode manifest.

### 4.6 `react_hook_form/153` failed for all four frontier frameworks

It is the only TypeScript task in the `core` subset, and every framework failed
it. TypeScript episodes should be expected to skew toward
`a_broken`/`b_broken` rather than toward integration failures.

---

## 5. What would make this prediction wrong

Written down now so it cannot be reinterpreted later:

* **If `p` is much higher than 0.45** (Qwen3-Coder is better at these tasks than
  assumed), both-pass-alone episodes rise sharply and integration failures could
  reach 6–8. This is the most likely way the point estimate is too low.
* **If `p` is much lower than 0.25**, we may see **zero** integration failures
  from 20 episodes, and the corpus will consist almost entirely of individually
  broken patches. In that case cost-per-verified-integration-failure is
  undefined, and the honest report says so rather than quoting a large number.
* **If the naive three-way merge is harsher than expected**, conflict-type
  failures rise relative to semantic ones.
* **If the two agents coordinate effectively over Redis**, conflicts fall — the
  benchmark exists precisely because they mostly do not.

---

## Appendix A — 2026-09-07, before any run: cost inputs corrected

§2.4 flagged the cost figure as resting on assumed pricing, and said it would be
corrected. It is corrected here, before the campaign starts. **No prediction
about integration failures has changed** — only the cost inputs, which §2.4
explicitly marked unverified. The original numbers above stand as written.

**What changed.** LiteLLM's registry does carry `openrouter/qwen/qwen3-coder`,
so the price could be read locally without reaching openrouter.ai:

| | assumed in §2.4 | verified |
|---|---:|---:|
| prompt | $0.30 / Mtok | **$0.30 / Mtok** |
| completion | $1.20 / Mtok | **$1.00 / Mtok** |

Pinned in `config/pricing.json` with provenance and the LiteLLM version
(1.100.0). Recomputing an episode at 2 agents × (400k prompt + 50k completion):

```
prompt      800,000 × $0.30/Mtok = $0.240
completion  100,000 × $1.00/Mtok = $0.100
                          episode ≈ $0.34
```

| | frozen estimate | corrected |
|---|---:|---:|
| per episode | $0.55 | **$0.34** |
| 20 episodes + retries | $14 | **$9** |
| cost per verified integration failure (at 2) | $7 | **$4.50** |

**Still unverified:** LiteLLM's table can lag OpenRouter's live prices, and
openrouter.ai remains unreachable, so this could not be cross-checked against
the provider. Re-verify against https://openrouter.ai/models before trusting
the totals. The ledger computes from token counts against the pinned table, so
a repricing changes the *recorded* number only if the table is updated —
deliberately, so a campaign's totals mean the same thing on every episode.

**One risk this closed.** The harness's default `cost_tracking: ignore_errors`
(`coop.yaml:224`) sets cost to `0.0` on any pricing failure *and* suppresses the
warning — how CooperBench's own table came to record $0.00 for `codex` while it
burned 400k+ billable tokens per agent. Under a hard cap, silently free
inference is the worst possible failure. Two changes: `config/agent_config.yaml`
sets `cost_tracking: default` so errors surface, and `farm/cost.py` raises
`ZeroCostWithUsage` rather than recording a $0 settlement that carries real
token usage.
