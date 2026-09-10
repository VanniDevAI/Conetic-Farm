# Mining real history for the semantic class: both methods return zero

No spend. No model was called and no GitHub API either — git history plus the
repository's own test suite. Predictions were frozen and pushed in
`config/history_mining.json` before any of it ran.

**Both methods found nothing, and the two nulls have different causes.** Method
A says the class does not survive to a merge commit in a well-run project.
Method B says that even when you construct the condition branch protection
removes, two genuinely concurrent changes in a mature library do not interact.

## Supply first, because it is the binding constraint

The request was for the top five census repositories. **One is walkable.**

| repo | two-parent merges, 12 months | walkable | why not |
|---|---:|---|---|
| pallets/click | **227** | **yes** | suite runs in 1.5 to 9 seconds |
| python-pillow/Pillow | 353 | no | C extension rebuilt on every checkout, about a minute a run |
| stanfordnlp/dspy | 6 | no | no full-suite invocation available here is green at base |
| pallets/jinja | 0 | no | last commit 2025-06-14; the 12-month window is empty |
| go-chi/chi | **0** | no | squash-merges |
| huggingface/datasets | **0** | no | squash-merges |
| run-llama/llama_index | **0** | no | squash-merges |
| dottxt-ai/outlines | **0** | no | squash-merges |

**Four of eight repositories produce zero two-parent merges.** They squash, and
a squash discards the second parent — the pull request branch as its author
wrote it. The experiment is destroyed at merge time and no amount of walking
recovers it. That is not a limitation of this pass; it is a fact about where the
evidence can exist at all.

I predicted 1 of 8 walkable. That was right, and it is the least comfortable
correct prediction in this report.

## Method A: 227 merges, 681 suite runs, zero failures

| | |
|---|---:|
| two-parent merges examined | **227** |
| distinct commits tested | 423 |
| suite runs | 681 |
| first parent green | 227 of 227 |
| second parent green | 227 of 227 |
| merge green | **227 of 227** |
| **coordination failures** | **0** |

The suites really ran: 681 runs, durations from 2.3 to 9.3 seconds, median 7.4,
not one zero. A green that came from collecting no tests would have exited
non-zero and shown as a failure.

### The predicted mechanism explains only half of it

I predicted near-zero and gave a reason: click requires a branch to be current
before merging, so the second parent already contains the first parent's
changes and the interaction is tested before the merge button appears.

That is true for **118 of 227** merges — the first parent is an ancestor of the
second, so the merge is not two independent changes meeting at all.

**It is false for the other 109.** In those the branch was stale: main moved
while the pull request was open, by a median of 4 files, and the merge really
was the first time the two changes met. All 109 came out green. In **44** of
them main and the branch had touched *the same file* and git merged them anyway.

So the null is stronger than my explanation for it. It is not only that hygiene
removes the condition. In 109 measured cases where the condition was present,
nothing broke.

## Method B: 140 pairs replayed, zero failures

B constructs what A can only find where it survived. Every branch has a
merge-base with main — the commit its author started from. Where both branch
points precede both merges, neither author saw the other's work; replay each
branch's own diff onto the older base and grade the combined tree.

| | |
|---|---:|
| pull-request merges with a derivable branch point | 227 |
| concurrent pairs within seven days | **736** |
| …with disjoint file sets | 352 (48%) |
| …of those, with a one-edge claim-map chain | 90 (26%) |
| …with a chain at three edges | 150 |
| …with no chain at all | 202 |
| pairs replayed | **140** |
| clean merges with both lanes green | **101** |
| textual conflicts | 39 |
| **semantic failures** | **0** |

Supply is not B's problem. 736 candidates in one repository in one year, against
my predicted 20 to 80 — the count was wrong by an order of magnitude, and wrong
in the useful direction.

### The filters matter, and the first 20 pairs proved it

Replaying unfiltered, 17 of the first 20 pairs were textual conflicts. Filtering
to disjoint file sets — git needs a shared file to conflict — moved that to 13
of 80. That is selection rule 1 from the design document, now measured rather
than argued.

Applying rule 2 as well, a directed one-edge chain between the two sides'
changed definitions:

| | |
|---|---:|
| replayed, disjoint **and** linked | 27 |
| of those, clean merge with both lanes green | **20** |
| **semantic failures** | **0** |

**Zero of 20 on the fully-filtered subset**, against a predicted 2% to 10%.

### Why disjointness alone is the wrong filter

202 of 352 disjoint pairs have no claim-map chain at any hop, and **187 have one
side with no indexed definitions at all** — changelog entries, documentation,
`pyproject.toml`. Disjointness selects for pairs that cannot conflict *and*
cannot interact. It is necessary and nowhere near sufficient, and running B
without rule 2 spends most of its episodes on pairs with nothing to find.

### And the chains it does find are noisy — filed as ENGINE-001

The claim map's output on real diffs is visibly worse than on the constructed
corpus. Among the 90 one-edge chains:

    showtype -> isolated_filesystem        from "Add `shtab` to third-party contrib list"
    format_completion -> f                 a definition named `f`

A documentation change linked to a test helper, and a chain terminating in a
single-letter local. This is the same pattern as `mechanism_named_by_claim_map`
in CE-006 and CE-007: the map relates two patches and does not explain them. On
real history it also relates patches that are not related.

Filed for the Intelligence session as
`docs/engine/ENGINE-001-claim-map-noise-on-real-diffs.md`, with all 90 chains and
both sides' commit subjects in `docs/engine/claim_map_chains_click_sample.json`.
Not the Farm's fix. Of the 90: 6 chains end in a one-character name, 20 have a
documentation-shaped side, and `-> f` appears six times, five of them from a
single refactor that split test utilities into one file per function.

## Prediction against observation

| | predicted | observed | |
|---|---|---|---|
| walkable repos | 1 of 8 | **1 of 8** | right |
| A: both parents green, merge red | 0 to 2 of 227 | **0** | right, at the floor |
| A: red merges of any kind | 5 to 20 of 227 | **0** | wrong — no drift at all |
| A: mechanism is branch currency | the explanation | true for 118 of 227, false for 109 | **half right** |
| B: concurrent pairs | 20 to 80 | **736** | wrong, by an order of magnitude |
| B: semantic rate | 2% to 10% | **0 of 101 clean merges** | **wrong** |
| claim map names the mechanism in under half the hits | — | no hits to name | untested |

The A drift prediction is the interesting miss in the other direction. I
expected 5 to 20 merges to be red today purely from dependency drift, and pinning
`pytest<9` removed all of it. Click's twelve months are reproducible under one
toolchain, which is not what the census pass found for click's own 2024 base
commits.

## The finding of the week

**Coordination failure of the semantic kind is produced by isolated cheap agents
at roughly one episode in ten, and is not produced by human authors in released
history at all — 0 in 328 measured opportunities. That claim rests on one
repository (pallets/click), one cheap model (`qwen3-coder`), and about twenty
Farm episodes, so what it supports is "between isolated cheap agents", not
"between agents".**

The limits belong in the sentence, not in a footnote after it. A single
repository cannot speak for a corpus; a single cheap model cannot speak for
models; twenty episodes with two hits cannot carry a rate to two figures. What
the evidence does support is a direction and an asymmetry, both large enough to
survive the caveats: three independent sources at zero against a source that
fires repeatedly.

Everything below is the detail behind that paragraph.

## What this means

**The class is rarer in released history than in a two-agent sandbox, and that
is a real asymmetry, not a measurement failure.** Three independent sources now
agree:

| source | pairs | semantic failures |
|---|---:|---:|
| CooperBench, co-authored from one PR | 50 scored | 0 |
| click merge history, method A | 227 merges | 0 |
| click concurrent replay, method B | 101 clean merges | 0 |
| **the Farm's own episodes** | **~20 episodes** | **2 (CE-006, CE-007)** |

The Farm produces the class at roughly one in ten episodes. Real history in a
mature library produces it in none of 328 opportunities. The difference is not
that history is safer — it is that a human author on a stale branch still reads
the code around their change, and two agents in separate containers do not. That
is the thing being measured, and it does not exist in a repository's history
because a repository's history was written by people.

Which changes what next week is for. It is not to source the class from history;
history does not have enough of it. It is to run the Farm's own pairs on a
corpus where a failure is *checkable* — and click qualifies: 227 merges of green
history, a 7-second suite, one toolchain, and 736 known-concurrent pairs to base
episodes on.

## What is banked

| path | |
|---|---|
| `farm/history/A_merge_history_click.jsonl` | 227 merges, three suite outcomes each |
| `farm/history/A_stale_branch_merges_click.json` | the 109 stale-branch merges, with file overlap |
| `farm/history/B_concurrent_click.jsonl` | 60 unfiltered replays |
| `farm/history/B_concurrent_click_disjoint.jsonl` | 80 disjoint-filtered replays |
| `farm/history/B_disjoint_chains_click.json` | chain status for all 352 disjoint candidates |
| `farm/history/summary.json` | every count in this report |
