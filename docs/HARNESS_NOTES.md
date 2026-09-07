# Harness and model notes that would bias later measurement

Findings from setting up CooperBench, each verified against the source or by
running it. Ordered by how much they would distort a measurement of integration
failure. Nothing here is speculation about what might go wrong; each item was
observed.

---

## 1. CooperBench's own eval scores a conflicted merge as a pass

**Severity: would invert the headline metric.**

The documented eval policy is `identical → naive merge → lead's patch alone`
(`docs/BENCHMARK_RESULTS.md`). The final fallback tests **one agent's patch
alone** against both feature suites, and scores a pass if it satisfies them —
*even though the merge conflicted*.

Its effect in their own published table:

| Framework | Reported pass | Passes that were actual merge passes |
|---|---|---|
| `mini_swe_agent_v2` | 6/10 | 5/10 |
| `codex` | 5/10 | 3/10 |
| `claude_code` | 5/10 | 2/10 |
| `openhands_sdk` | 4/10 | **1/10** |

For `openhands_sdk` the policy turns 1 into 4. That policy is reasonable for
"did the team ship the features"; it is precisely wrong for "did integration
fail", because it converts an integration failure into a success.

**Mitigation:** we do not use `cooperbench eval`'s verdict for labelling. We
compute our own A-alone / B-alone / merged triad (`farm/grade.py`) and label from
that (`farm/classify.py`). CooperBench's `eval.json` is still retained per
episode so the two can be compared, and the disagreement rate is reported.

---

## 2. No pair in the dataset has disjoint gold patches — there are no true controls

**Severity: blocks part of the requested design.**

The brief asks for "safe controls where no conflict is expected". Measured across
all 652 pairs:

```
pairs whose two gold patches share no file:              0 / 652
pairs whose two gold patches share no top-level module:  0 / 652
```

This is by construction, not a defect: a CooperBench task pairs two features
drawn from the *same upstream pull request*, so both features edit the same
file(s). The benchmark exists to study interference and is built to guarantee
the opportunity for it.

**Consequence:** a control in the strict sense cannot be drawn from CooperBench.
The plan uses a **separation control** instead — a compatible pair whose nearest
changed hunks are ≥150 lines apart in every shared file, at most 2 per task.
Only 6 such pairs exist dataset-wide; 4 are used.

A separation control still has both agents editing one file. It controls for
*textual* proximity, not for semantic independence, so a failure in this stratum
is weaker evidence of a harness or model problem than a true disjoint control
would have given. If genuine controls matter, they have to be constructed
outside CooperBench.

## 2b. Hunk separation is small almost everywhere

Across the 147 compatible pairs, the median distance between the two gold
patches' nearest hunks is **7 lines**; the maximum in the whole dataset is 519.
Even the "clean merge" stratum is mostly near-adjacent edits, so a clean gold
merge is a weak predictor that two *agent* patches will not collide.

---

## 3. Six pairs are mislabelled as clean merges in the source data

`dataset/gold_conflict_report.json` marks 153 pairs `has_conflict: false`. Six of
those also carry `patch1_apply_failed` or `patch2_apply_failed`: they are
"clean" only because one gold patch never applied, so no merge was attempted.

All six are `react_hook_form_task/task85` — which is the TypeScript slice.
Taking the file at face value would suggest TypeScript has 6 clean pairs when it
has **zero**. `farm/plan.py` excludes them from every stratum.

---

## 4. The TypeScript slice is very small and entirely conflicting

`react_hook_form_task` is the only TypeScript repo:

* 2 tasks (`task153`, `task85`), 25 feature pairs.
* 19 conflicting (both gold patches apply), 6 excluded as above.
* **0 genuinely clean pairs.**

So the TypeScript slice can supply conflicting episodes and nothing else. The
plan applies a floor of 4 TypeScript conflicting episodes and draws
compatible/control episodes from Python repos. Any language comparison in the
final report is descriptive only; the design does not support attributing a
difference to language.

Also relevant: `react_hook_form/153` is the only TypeScript task in the `core`
subset, and **all four** frontier frameworks failed it
(`docs/BENCHMARK_RESULTS.md`). TypeScript episodes should be expected to skew
toward `a_broken`/`b_broken` rather than toward integration failures.

---

## 5. Genuine integration failures are suppressed quadratically by model quality

**Severity: determines the yield of the whole campaign.**

A genuine integration failure requires *both* patches to pass alone. If a single
agent solves a single feature with probability `p`, eligible episodes arrive at
about `p²`.

Halving `p` quarters the yield while the campaign still pays for every episode.
A weaker model does not produce "the same result, noisier" — it produces a
corpus of individually broken patches with almost no integration failures in it.

The practical implication is counterintuitive: **for harvesting integration
failures, a stronger and more expensive agent model is likely cheaper per
verified failure.** With `p = 0.45`, roughly 4 of 20 episodes are eligible; with
`p = 0.7`, roughly 10 of 20 are.

---

## 6. The qwen adapter profile changes the agent, not just the weights

`docs/QWEN_LOCAL.md` shows `claude_code/adapter.py` matching the substring
`qwen` (case-insensitive) against the model name and applying a small-context
profile: `max_output_tokens=4096`, `file_read_max_tokens=4000`,
`mcp_max_output_tokens=2000`, plus a stripped tool surface
(`SMALL_CONTEXT_DISALLOWED_TOOLS`).

Any model whose *name* contains "qwen" gets this, including a large
Qwen3-Coder that does not need it. What gets measured is that configuration, not
the model at full strength. The adapter and its resolved profile are recorded in
every episode manifest.

This applies to the `claude_code` adapter. We default to `mini_swe_agent_v2`
(§8), which does not apply the profile — worth stating because a run comparing
the two adapters is not comparing like with like.

---

## 7. The sandbox base image is not the upstream one

Registry blob downloads are blocked in this environment
(`production.cloudfront.docker.com` → 403), so `FROM node:22-slim` cannot be
pulled. The base layer is imported from the host rootfs instead: same Node major
(22.22.2), but Ubuntu 24.04 userland rather than Debian slim. The `apt-get`
layer is replaced by an assertion, and `CYPRESS_INSTALL_BINARY=0` and friends
suppress binary downloads from blocked CDNs.

Recorded per episode in `base/image.json`. A test sensitive to the base distro,
to a system library version, or to a browser binary would behave differently here
than in a run reproduced from the upstream image. The graded suites in the
TypeScript slice are pure jest unit tests, so the exposure is low but not zero.

---

## 8. Adapter choice decides whether the API key enters the container

| Adapter | LLM call runs | Key in container? |
|---|---|---|
| `mini_swe_agent_v2` | host process, via LiteLLM | **no** — container only runs `docker exec` shell commands |
| `claude_code` | inside the container | **yes** — `adapter.py:167-171` forwards `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` |

We use `mini_swe_agent_v2`. The agent under test runs arbitrary shell commands
in its sandbox; it should not be doing so next to a live credential.

---

## 9. The harness's published numbers came from a debugging process, not a clean run

`docs/BENCHMARK_RESULTS.md` documents that five reruns and four re-evals were
needed to reach the published table, and that intermediate runs scored 0/10, 1/10
and 2/10 due to harness bugs (a Modal sandbox terminating on first exec, a
`normalize_patch` `.strip()` eating trailing context lines and breaking hunks
across the board, a 120s `docker run` startup timeout at concurrency 10).

Two things follow:

* **A low score is a harness hypothesis before it is a model result.** Our
  taxonomy has a `harness_error` label that is excluded from rates and reported
  separately, and every attempt is retained so a later-discovered harness bug can
  be re-graded rather than re-run.
* **Concurrency is a confound.** Container-startup timeouts at concurrency 10
  produced 0/10 twice. We run at low concurrency and record it per episode.

---

## 10. Cost anchors, and what is still unverified

From `docs/BENCHMARK_RESULTS.md`: `mini_swe_agent_v2` + gpt-5.5 cost **$13.37 for
10 pairs** in team mode (~$1.34/pair), at roughly 400k input tokens per agent per
task. `codex` recorded **$0.00** because gpt-5.5 was not in LiteLLM's local
pricing table while doing 400k+ input tokens of real work.

That last one is a live trap: **LiteLLM silently reports zero cost for a model
missing from its registry.** `farm/cost.py` therefore records a `cost_source`
per settlement (`provider_reported` / `computed_from_tokens` / `estimate`) and
computes from token counts against a pinned price table rather than trusting a
reported figure. A zero-cost settlement with non-zero tokens is treated as a
missing price, not as free inference.

**Unverified:** OpenRouter's live price for Qwen3-Coder could not be read —
openrouter.ai is blocked from this environment. The cost estimate in
`docs/EXPECTATIONS.md` (~$0.55/episode) rests on assumed pricing and must be
corrected against the first three real episodes before continuing.
