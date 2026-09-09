# Step 3 — both pairs fired, and the census cannot move

Two results, one spend of **$2.0260** against a $10 ceiling enforced against the
OpenRouter meter.

1. With the coop channel off and the ownership boundary enforced by the
   sandbox, **both seeded pairs produced a semantic integration failure**.
   Under identical briefs and identical grading, both had come back
   `both_pass_merge_passes` in `s03`.
2. Resolving symbols through an identity graph **cannot change the census**,
   and the reason is not the classifier: no CooperBench pair has disjoint
   files, so the semantic branch is never reached. 0 before, 0 after.

## 1. The isolated rerun

### Result

| | pair 1 — query-core | pair 2 — zod |
|---|---|---|
| A alone, own tests | pass | pass |
| B alone, own tests | pass | pass |
| A alone, partner's tests | fail | fail |
| B alone, partner's tests | fail | fail |
| merge | **clean**, `conflicted_paths: []` | **clean**, `conflicted_paths: []` |
| merged, A's tests | pass | pass |
| merged, B's tests | **fail** | **fail** |
| label | `integration_failure_tests` | `integration_failure_tests` |
| **class** | **semantic** | **semantic** |
| cost | $0.1057 | $1.8189 |

Integration failures this run, by class: **textual 0, semantic 2.**

### Would the claim map have flagged it

Both, from the gold pair, before either agent ran:

| pair | claim chain | anchor line | diff-only verdict |
|---|---|---|---|
| 1 | `isStaleByTime` → `timeUntilStale` | `packages/query-core/src/utils.ts:136` | `independent` |
| 2 | `$ZodCheckMultipleOf` → `floatSafeRemainder` | `packages/zod/src/v4/core/util.ts:327` | `independent` |

The chain is the whole point: in both pairs the provider's name appears only
inside the body of the consumer's existing definition, so no diff prints it and
the changed-line test reports `independent`. Resolved against the repository,
the hop is one edge long and the anchor is a line number a claim id can carry.

### What changed, and what did not

Changed, and only this:

* **No channel.** Each feature ran as its own `--setting solo` invocation.
  CooperBench's solo path passes `messaging_enabled=False`, `git_enabled=False`
  and no server URL, and its own comment records the consequence: "Solo runs
  have no shared server ... a bare repo inside the agent's own sandbox." Each
  agent got a private `/tmp/team.git` in its own container. No mailbox, no
  partner branch to fetch.
* **A cannot see the consumer.** A ran in an image where the consumer module
  and every file reaching it through a runtime import had been removed and
  committed away — 201 files for query-core, 275 for zod — with a build-time
  leak check asserting the consumer's method name appears nowhere.
* **B cannot edit the provider.** B ran in the full image with the provider's
  source bind-mounted read-only at the base commit. A read-only bind mount is
  enforced by the kernel and holds against root inside the container, verified
  before the run.

Unchanged: both briefs verbatim, both graded test patches, the grading triad,
the merge, the classifier, the model.

### Why it fired: the audit came back empty

The suppressor `s03` identified was the provider agent auditing its own call
sites and repairing the consumer. It ran the same audit here. It just found
nothing.

Pair 1, agent A, in its own words:

> Now let's check callers to see if any rely on the clamped behavior.

The grep returned one line — its own definition — and it concluded:

> No other callers currently.

Pair 2, agent A, went twice, and said why:

> no other callers exist currently that depend on that behavior (grep confirmed
> only definition, no usages elsewhere - but let's double check where it's used,
> maybe imported elsewhere with different name or via util namespace)

The second check returned the definition again. In `s03` this same agent had
repaired `checks.ts` **and** found `compile.ts`, a consumer the seed had not
identified. Here its patch touches `util.ts` alone.

That grep result is also the proof the boundary was in force: in the full image
those greps return the call sites, as `s03` showed.

Neither B wrote to the provider. Pair 1's B touched `query.ts`; pair 2's B
touched `checks.ts` and `errors.ts`, adding the issue field's type.

### Cost, and one honest note about it

| | s03 (coop) | s04 (isolated) |
|---|---|---|
| pair 1 | $2.5662 | $0.1057 |
| pair 2 | $4.1057 | $1.8189 |
| total (meter) | $6.6719 | **$2.0260** |

The isolated agents are much cheaper, and not only because A had less to read:
coop mode's prompt requires each agent to fetch and merge its peers' branches
before submitting, which is work solo mode does not ask for. The cost drop is a
consequence of removing the channel, not an independent finding. Ceiling
enforcement was by the provider meter read before every agent, as specified;
the $13.60 harness hold was not used at all.

### What this does and does not establish

It establishes that the pair shape is sound and that the suppressor was real
and removable: two pairs, two repositories, both fired, both semantic, both
with a merge git called clean.

It does not establish that semantic integration failures are common. The
boundary here was constructed. Two agents in one package with a shared channel
did not produce this class; two agents with no channel and no sight of each
other's module did, twice. The honest reading is that the class is a function
of the isolation, which is the premise the product assumes rather than a
property of this benchmark.

The `s03` limitation still stands and is unchanged by this run: under the gold
patches, A alone is red on each repository's own suite (query-core 7 of 683,
zod 4 of 5366), so these pairs reproduce the class but not its stealth.

## 2. The census, resolved

`farm/identity.py` builds an identity graph from each task's repository at its
pinned base commit — every top-level definition, where it lives, and the
identifiers its body mentions — and `classify_overlap` now takes that graph
instead of reading symbols off changed lines. All 31 non-seeded task
repositories were cloned at their pinned commits, indexed, and measured; none
were skipped.

### New count beside the old

| | old (changed-line symbols) | new (resolved through the graph) |
|---|---|---|
| textual | 564 | 564 |
| same_file | 82 | 82 |
| **semantic** | **0** | **0** |
| independent | 0 | 0 |
| total | 646 | 646 |

**The count does not move, and the classifier is not why.** Every pair in the
corpus shares at least one file, so `classify_overlap` returns `textual` or
`same_file` before it ever asks about symbols. The semantic branch is
unreachable on this corpus for any symbol test whatsoever. Precedence is
deliberate and unchanged — a pair git will refuse must not be filed under a
class git cannot see — and a test pins it.

So the one-hop blindness was never what produced the zero. It was what produced
the **misses on the seeded pairs**, which do have disjoint files, and there the
fix is decisive:

| | old | new |
|---|---|---|
| seeded pair 1 | `independent` | **`semantic`**, chain `isStaleByTime → timeUntilStale` |
| seeded pair 2 | `independent` | **`semantic`**, chain `$ZodCheckMultipleOf → floatSafeRemainder` |
| recall on confirmed positives | 0 of 2 | **2 of 2** |

### The number that is new

Asked of every pair regardless of class — is there a resolved chain of named
definitions from one patch's changed code to the other's, within three hops:

| | count | share |
|---|---|---|
| pairs with a resolved link | **497** | 77% of 646 |
| of which already `textual` | 435 | |
| of which already `same_file` | 62 | |
| pairs with a link and disjoint files | **0** | |

Read carefully: 77% of the corpus is coupled by symbol as well as by file. None
of it is *only* coupled by symbol. Every linked pair is one git already sees,
so the link adds no detection git does not already provide. The claim map's
distinctive value needs the last row, and on this corpus that row is zero.

### One reconciliation

Reproducing the census turned up 652 pairs whose gold patches both apply to the
base tree, against the earlier figure of 646. The six are all in
`react_hook_form_task/task85`, and they are exactly the pairs drawn from
features 2–5, which read as alternative implementations of one feature rather
than as independent work. The earlier run excluded them; this one, applying the
stated criterion literally, does not. On the earlier denominator the diff-only
classes reproduce exactly — 564 textual, 82 same_file — which is the check that
matters. The semantic count is 0 on both denominators, so nothing downstream
turns on it. Both are reported above on the 646 denominator for comparability;
`results/census_resolved.json` carries all 652.

## Artifacts

| what | where |
|---|---|
| per-pair results, patches, transcripts | `/home/user/farm-seed-s04/` |
| spend ledger against the meter | `/home/user/farm-seed-s04/spend.json` |
| every census pair with its class and chain | `results/census_resolved.json` |
| the isolation mechanism and its limits | `dataset/seeded/isolation/README.md` |
| the runner | `scripts/run_isolated_pair.py` |
| the census | `scripts/census_overlap.py` |
| the identity graph | `farm/identity.py` |
