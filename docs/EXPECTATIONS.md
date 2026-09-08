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

---

## Appendix B — 2026-09-07, after `c01` was halted at 3/20: the harness was wrong, the predictions are not

`c01` started, ran three episodes, and was stopped deliberately. Nothing in §1–§5
changes. **Every prediction above stands exactly as frozen.** What changed is the
instrument: three defects were found that made the instrument incapable of
testing those predictions, and one of them would have produced a confident,
completely false answer.

This appendix records the corrections and, more importantly, the new biases they
introduce — before any of them can be rationalised away.

### B.1 The campaign was measuring nothing (the serious one)

`c01` episode 3 recorded `no_patch_both`. Both agents had in fact **written real
code**: the working-tree snapshotter caught `src/click/core.py` edited 18 times.
The patch was empty anyway, because `mini_swe_agent_v2` grades the *published*
artifact:

```
git --no-pager diff <base_sha> origin/<agent_id>     (connectors/git.py:247-251)
```

— a diff against **the remote-tracking ref of a branch the agent must push**,
wrapped in a bare `except Exception: pass` (`adapter.py:259-266`) so every failure
degrades to `""`.

**Correction to a first, wrong diagnosis.** It initially looked as though `gh`
was absent and `origin` pointed at the unpushable upstream
(`github.com/pallets/click`). That is the *fresh image* state, not the live agent
container. `GitConnector.setup()` creates a private bare repo at `/tmp/team.git`
inside each container, rewrites `origin` to it, installs a `gh` shim, and pushes
the base commit to `refs/heads/<agent_id>` (`connectors/git.py:117-147, 169-193`).
A working remote and a working `gh` were both present. The agents simply never
committed or pushed.

The branch therefore *exists* but sits at base, so the no-PR fallback
(`git.py:225-241`) diffs base against a ref identical to base and returns `""`
with `NO PR OPENED ... branch is at base: nothing to submit`.

**And the agent could not have recovered.** `query()` raises `LimitsExceeded`
*before* incrementing its step counter (`agents/default.py:386-396`). The run
loop sees the exit, appends the "you have not submitted anything" nudge, and
`continue`s straight back into `query()` — where the counter is still at the
limit, so the identical exception fires again. The trajectory shows it exactly:
`exit → nudge → exit → nudge → exit`, with **zero assistant turns in between**
(`raw/agent5_traj.json` messages 53-57). The nudge is dead code for a step-limit
exit, which is the common exit. So an agent that runs out of steps loses *all*
of its work, unconditionally — raising the step limit changes who it happens to,
not whether it happens.

That rule is defensible for CooperBench's own question — work nobody can see was
not shipped. It is **wrong for ours**, and wrong in a way that destroys the
measurement rather than merely biasing it. §2.1 says the binding constraint is
`p²`. An extraction that returns empty for every agent forces `p = 0`, therefore
`p² = 0`, therefore **zero integration failures are possible**. All 20 episodes
would have returned `no_patch_both` for ~$25.

The trap is that this is *indistinguishable from a result*. §5 predicts in advance
that a weak enough agent yields zero integration failures. The run would have
produced exactly that shape, and it would have been reported as a finding about
Qwen3-Coder rather than a broken instrument.

**Correction.** An agent's patch is now the diff between the task base and its
**final working tree**, read from its container while it is still alive
(`farm/patchgen.py`). This is the same move §4.1 already makes for the *verdict*:
we do not use `cooperbench eval`'s pass/fail, and now we do not use its patch
either, for the same class of reason. The harness's own patch is still retained
per agent as `patch_harness.diff`, so the two can be compared.

**Verified, not assumed.** Re-extracting the one archived `c01` episode that
reached the agent stage recovers **11 files and 110,935 bytes** where the harness
reported 0 bytes for both agents.

### B.2 New bias introduced by B.1 — recorded now, not later

The working tree is not the same artifact as a curated commit, and pretending
otherwise would be dishonest:

* **Scratch files count as work.** In `c01` episode 3 the agent left eight
  debugging files (`test_debug.py`, `test_trace.py`, …) in the repo root. They are
  in the extracted patch, because they are genuinely what the agent left behind.
* **They cannot corrupt A-alone or B-alone.** Every grader runs *named* test
  files — e.g. `pytest tests/test_shell_completion.py tests/test_context.py`
  (`pallets_click/task2800/run_tests.sh:67`) — so a stray root-level `test_*.py`
  is never collected. Checked across the plan's repos.
* **They can inflate merge conflicts.** If both agents independently create a
  scratch file with the same name, the three-way merge conflicts on a path that
  has nothing to do with either feature — a false `integration_failure_merge`,
  which is precisely the headline metric. **Mitigation:** the merge already
  records the conflicting paths, and they are retained per episode, so a
  conflict confined to scratch paths is identifiable in analysis instead of
  being silently counted. Any integration failure reported from `c02` must state
  its conflicting paths.
* `sed -i` leftovers (`src/click/sedXXXXXX`) are excluded: they are artifacts of
  the editing tool with random names, not changes the agent made.

### B.3 Two task images could not build (`$0` each, before any model call)

* **`typst_task/6554`** — `cargo: not found`. The sandbox base image is imported
  from the host rootfs (§4.4), and the Rust toolchain lives under `/root`, which
  that import deliberately excludes as host state. The toolchain is now copied in
  explicitly (`scripts/build_base_image.sh`); `cargo 1.94.1` runs in the image.
* **`llama_index_task/18813`** — `invalid peer certificate: UnknownIssuer`. `uv`
  links its own webpki roots and ignores the system trust store, so it fails
  behind this environment's TLS-intercepting gateway. This is the `uv`-shaped
  version of the Node problem already recorded in `docs/ENVIRONMENT.md` §3.
  `UV_NATIVE_TLS=1` is now injected (`scripts/build_task_image.sh`) and **fixes
  the TLS failure** — but the episode still cannot build, because the index it
  then reaches, `pypi.nvidia.com`, returns a genuine **403 from the egress
  gateway**. That index is declared by the *upstream* llama_index repository, not
  by CooperBench, so overriding it would change the task's own dependency
  sources. It is left failing and recorded as an environment limitation: one
  `compatible` episode is expected to be unavailable unless `pypi.nvidia.com` is
  allowlisted.

### B.4 The cap was not a cap

Also found in `c01` and corrected before `c02`, because it bears directly on the
cost figures in §2.4 and Appendix A. Three sources disagreed on one episode:

| source | episode cost |
|---|---:|
| OpenRouter, the actual biller | **$1.2228** |
| the harness's own LiteLLM figure | $0.9043 |
| our ledger, from trajectory token counts | **$0.2301** |

Appendix A's reasoning was right that the harness's figure cannot be trusted, but
our replacement was **also** wrong: the trajectory carries usage for ~60 requests
where the harness counted 200 steps, so the token sum covered about a fifth of
what was billed. A $50 cap enforced against a 5× low number permits ~$265.

Episodes are now billed from OpenRouter's own meter (`farm/provider.py`), read
before and after each episode, with the token-derived figure retained beside it.
The pre-run hold rose $0.78 → $1.84, having been sized by the same bad
assumption.

**This does not change any prediction, but it does change what the cost numbers
in §2.4 will be compared against.** The honest reading is that Appendix A's
**$0.34/episode** estimate was never tested — `c01`'s single billed episode cost
**$1.2228**, about 3.6× it. That episode was also pathological (both agents burned
100 steps submitting nothing), so it is an upper bound rather than a forecast, and
§2.4's estimate is left standing to be tested properly by `c02` rather than
retro-fitted to one bad data point.

### B.5 What `c02` runs under

Same frozen plan, same 20 episodes, same order, same strata, same seed. Fresh
campaign directory; no `c01` artifact is carried in. Two independent ceilings,
both checked against the provider rather than our own ledger, and an unreadable
meter stops the run rather than being treated as permission to spend:

* campaign cap **$50**, measured as the meter delta since `c02` began;
* prepaid balance **$20**, of which ~$18 remained at the start.

**The balance is the binding constraint, and it is expected to bind before 20
episodes.** At `c01`'s measured $1.22/episode, 20 episodes need ~$24.40 against
~$18 available. A short run is therefore the *expected* outcome, not a failure,
and the stopping point will be reported explicitly with the episode count reached.
Predictions in §1 are stated for 20 episodes; if `c02` stops early, they are
**not** thereby refuted or confirmed, and any comparison must be against the
number of episodes actually run.

---

## Appendix C — 2026-09-08: what `c02` actually measured

`c02` attempted all 20 planned episodes. The headline prediction cannot be
tested against it, and this appendix says why in the terms §1 was written in,
rather than quoting a number that would look like an answer.

### C.1 The result

| | |
|---|---:|
| Episodes attempted | 20 |
| …harness errors (no measurement) | 4 |
| Episodes that produced a measurement | **16** |
| …that retained a patch from **both** agents | **5** |
| Genuine integration failures | **0** |
| Spend (OpenRouter's meter) | **$13.28** of a $20 balance |

**The effective sample for the headline number is 5, not 20.** A genuine
integration failure requires both patches to exist and both to pass alone
(§1). Eleven of the sixteen measured episodes lost one agent's patch — some
because the agent produced nothing, most to the container-teardown race in
`reports/c02_instrument_notes.md` §2 — and those episodes could not have shown
an integration failure however the two features interact.

**Zero found in 5 neither confirms nor refutes a prediction made for 20.** The
frozen numbers stand untested. That is the honest reading, and it is the
reading the report generator now prints.

### C.2 The frozen estimate of `p` was close

§2.2 estimated **`p` ≈ 0.45** (range 0.25–0.60) with a paragraph of reasoning
about Qwen3-Coder and a small-context adapter profile. It is the one frozen
quantity `c02` can actually check, because every episode that retained both
patches also graded both agents alone:

```
agent-slots holding a patch:              10
...that passed their own suite alone:      4
observed p = 0.40        (frozen: 0.45, range 0.25-0.60)
```

Four of ten, against a prediction of 0.45 written before any agent ran. On ten
observations that is a weak check — the 95% interval on 4/10 spans roughly
0.17–0.69 — but it is a check, and the estimate is inside it comfortably.

The consequence follows directly from §2.1 rather than from anything new:

```
p² = 0.16  ->  expected both-pass-alone episodes among 5: 0.8
```

**So observing zero integration failures in five eligible episodes is exactly
what §2.1 predicts.** The squaring did the work it was said to do. The campaign
did not fail to find integration failures because the reasoning was wrong; it
found none because 5 eligible episodes at `p ≈ 0.4` are expected to yield
under one both-pass episode, and an integration failure needs one of those
*and* the merge to then break.

### C.3 One thing that points the other way, and is worth keeping

Of the 5 episodes that retained both patches, **2 merged with a conflict, both
on real source files** — not on the agent scratch files B.2 warned could
manufacture false conflicts:

| Episode | Stratum | Conflicted path |
|---|---|---|
| `react_hook_form/153 f2+f5` | conflicting | `src/logic/createFormControl.ts` |
| `typst/6554 f1+f7` | conflicting | `crates/typst/src/foundations/str.rs` |

Both are `conflicting`-stratum episodes, and both conflicted: 2 of 2. §2.3
assumed P(merge fails | both pass alone) = 0.55 for that stratum. Two of two is
far too small to confirm anything, and these merges were not conditioned on
both patches passing — they conflicted regardless. But it is the only evidence
`c02` produced about §2.3, it points toward the assumption being reasonable
rather than optimistic, and B.2's worry about scratch-file conflicts did **not**
materialise in either case.

### C.4 Where the 4 harness errors came from

| Episode(s) | Cause | Status |
|---|---|---|
| `llama_index/18813` | `pypi.nvidia.com` returns 403 at the egress gateway | **not fixable here** — the index is declared by the upstream repo, so overriding it would change the task's own dependency sources |
| `dottxt_outlines/1706` | build step fetches a model from `huggingface.co` | **not fixable here** — the one host preflight has always warned is blocked. Its warning was not cosmetic |
| `dspy/8563` ×2 | `Cannot uninstall PyYAML 6.0.1, RECORD file not found` | **fixable, not fixed** — same family as B.3: an apt-managed Python package has no RECORD, so pip cannot replace it. `pip install --upgrade pip` was fixed the same way; PyYAML needs the base image to own a pip-installed copy |

Four errors sits inside §1's predicted range for harness errors (2, range 0–6)
— but that agreement is a coincidence worth naming. The prediction anticipated
faults in the *harness*; these are faults in the *environment*, three of them
egress or base-image consequences of §4.4's substitution, and one of them
(`dspy`) simply not yet fixed.

### C.5 What would make this measurable

Not a longer campaign — a campaign that keeps both patches. At `p ≈ 0.4`,
`p² ≈ 0.16`, so about **1 in 6** eligible episodes should have both agents pass
alone, and only then can the merge decide anything. `c02` produced 5 eligible
episodes out of 20 attempted. Fixing the container-teardown race
(`reports/c02_instrument_notes.md` §2) should bring eligibility close to the
measured-episode count, which would have turned `c02`'s 16 measurements into
roughly 16 eligible episodes and ~2.6 expected both-pass episodes — the range
where §1's prediction of 2 integration failures starts to be testable at all.
