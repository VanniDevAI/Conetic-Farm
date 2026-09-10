# Next week: pairs from history, not from CooperBench

CooperBench is closed for the semantic class. Its pairs are one pull request cut
into features that shipped together, co-authored to fit, and 50 of 50 scoreable
pairs pass. That is not a power problem and more grading will not move it: the
condition the class requires — two changes authored independently, neither
author having seen the other's — does not exist in that corpus by construction.

This design set out to source pairs from history, where the condition really
occurred. **Both history methods returned zero**, and the design below is what
survives that: history qualifies *bases*, and the pairs still come from the Farm.

Three sources now agree on zero — 50 scoreable CooperBench pairs, 227 click
merges, 101 replayed concurrent clean merges — against the Farm's own two
failures in about twenty episodes. The asymmetry is the finding: a human author
on a stale branch still reads the code around their change, and two agents in
separate containers do not.

## What an episode is now

Unchanged in shape from c06b and c07, and different in where the pair comes from:

| | c06/c07 | next week |
|---|---|---|
| pair source | two briefs I wrote | two real changes from one repository's history |
| base | a pinned task commit | the commit both authors actually started from |
| ground truth | none; the grader decides | for method A, the historical merge and its fix commit |
| briefs | written by me | derived from each change's own commit message |
| lanes | 2, own containers, no channel | unchanged |
| grading | `farm.failure_class` | unchanged |

The briefs are the part that needs care. A brief must describe the *intent* of
the change without describing its implementation, or the episode measures
transcription rather than engineering. A commit message's subject and body are
the natural source, because that is what the author wrote before anyone saw the
diff. Where a message is a bare "fix typo", the pair is unusable and gets
dropped — recorded, not silently skipped.

## Method A: replay a merge that really broke

The mined merge already contains the answer. First parent green, second parent
green, merge red, and a later commit that makes it green again. That gives every
episode:

* two briefs, from the two changes' own commit messages;
* a base, the merge-base of the two branches;
* **a known-correct outcome**, because the historical fix commit says what the
  interaction was and how it was resolved;
* a grader that needs no seeding, because the repository's own suite already
  distinguishes the broken tree from the fixed one.

That last point is what makes A worth more per episode than anything the Farm
has run. Every previous episode needed me to decide whether a failure was real.
Here the project decided, at the time, in public.

**A's yield is zero, and the design changes because of it.** Measured on click's
twelve months: 227 two-parent merges, 681 suite runs, first parent green 227
times, second parent green 227 times, merge green 227 times.

It is not only branch-currency hygiene. In **109** of those merges the branch was
genuinely stale — main had moved a median of 4 files while the pull request was
open — and in **44** of those the two sides had touched the same file. All green.

Four of the eight census repositories squash-merge and produce **zero**
two-parent commits, so A cannot be run there at any price.

So A does not supply episodes. What it supplies is a **corpus qualification**:
227 merges of verified-green history under one pinned toolchain, with a
seven-second suite. That is what an episode needs as a base. See
`reports/history_mining.md`.

## Method B: replay two changes that were written at the same time

B does not need the merge to have broken. It needs only that the two authors
were working concurrently, which git can establish from branch points alone, and
then it *constructs* the merge that branch protection prevented.

Supply is not B's problem: click alone offers **736** concurrent pairs in twelve
months, and 352 of them have disjoint file sets. **B's semantic rate is also
zero** — 140 pairs replayed, 101 clean merges with both lanes green, and on the
fully-filtered subset (disjoint files *and* a one-edge chain) 0 of 20.

Two things B did establish, and both change the design:

* **Rule 1 alone is the wrong filter.** 202 of 352 disjoint pairs have no chain
  at any hop and 187 have one side with no indexed definitions — changelogs,
  docs, `pyproject.toml`. Disjointness selects for pairs that cannot conflict
  *and* cannot interact. Rules 1 and 2 must be applied together, or most
  episodes are spent on pairs with nothing to find.
* **What B is actually for is bases, not pairs.** A known-concurrent pair whose
  two sides are claim-linked, and whose replay merges clean with both sides
  green, is a *verified-safe base* for an episode: the two briefs can be derived
  from the two real changes, and anything the agents break is theirs.

**So neither A nor B supplies episodes with failures attached. Both supply
qualified bases.** The pair itself still has to come from the Farm, because that
is where the condition lives.

## Selection rules, applied statically before any spend

The rule from the last two campaigns is that textual conflicts consume episodes.
c07 spent 6 of 10 episodes on merge conflicts and reached the semantic endpoint
twice. That is the thing to fix, and it is fixable statically:

1. **Disjoint file sets.** `git diff --name-only base tip` for each side; reject
   any pair whose file sets intersect. This alone removes almost every textual
   conflict, because git conflicts need a shared file.
2. **Claim-map linked.** Require a directed one-edge chain between the two
   sides' changed definitions, via `farm.identity`. Disjoint files with no
   relationship cannot interact at all; disjoint files with a provider-consumer
   edge are exactly CE-006's shape.
3. **A test on each side.** Require a test body in the combined tree that names
   a changed definition on each side, at one edge. Without it a broken tree is
   invisible however wrong it is.
4. **Green base, green lanes.** The base commit's suite must pass under the
   toolchain chosen on the day, and each side replayed alone must pass. Anything
   else is unreadable and is dropped before an agent is paid for it.
5. **Both graded test patches must coexist**, the rule the census execution pass
   had to learn: judging a combined tree against test expectations that
   contradict the code it contains is not a measurement.

Rules 1 to 3 are free and run on every candidate. Rules 4 and 5 cost test runs,
which are also free. **Nothing reaches an agent until it has passed all five.**

## The significance floor

The endpoint is semantic failures shipped per arm, which is a proportion, and
the honest floor comes from what a paired design can distinguish.

At **5 episodes per arm** the smallest achievable two-sided p is 0.008 — the
design can in principle show something, which c07 established by getting
p = 1.000 with an actual difference of one episode.

To detect a difference of the size worth acting on, take the arms as 10% against
40% — a prosthetic that turns two failures in five into one in ten:

| episodes per arm | detectable at 80% power |
|---|---|
| 5 | nothing below a 60-point difference |
| 10 | about 45 points |
| **20** | **about 30 points** |
| 40 | about 20 points |

**20 per arm is the floor for a claim about the room**, and 40 for anything
subtle. Below 20, report counts and mechanisms and do not compute a rate. That
is what c06, c06b and c07 should have said and mostly did.

The hoped-for exemption does not apply. A single A episode carrying ground truth
would have been a demonstration rather than a sample, worth more than forty
ordinary ones — but A yielded no such episodes, so there is nothing to exempt.
Twenty per arm is the floor and it is the only floor.

## What twenty episodes from A cost

Measured, from the billed meter rather than agent self-report, per two-lane
episode with `qwen3-coder`:

| run | episodes | billed | per episode |
|---|---|---|---|
| c06 | 6 | $1.79 | $0.298 |
| c06b | 6 | $2.12 | $0.353 |
| c07 | 10 | $2.35 | $0.235 |

Mean **$0.29 per two-lane episode**, and note these are meter figures: the
per-lane ledgers understate by roughly a quarter because billing settles after
the last read.

| | episodes | cost |
|---|---|---|
| 20 from A, one arm, qwen3-coder | 20 | **$5.80** |
| 20 from A, two arms | 40 | $11.60 |
| 20 from A, one arm, Sonnet | 20 | ~$20 (c05b measured $3.92/episode at three lanes; ~$1.00 at two) |
| a repair pass on the roomed arm | — | adds about 60%, from c06b's $0.32 of $0.51 roomed |

**Against a remaining balance of $6.02**, twenty single-arm qwen episodes fit
with about twenty cents of headroom, which is not a margin. The honest options
are: 15 episodes at $4.35 with room to recover from a crash; or 20 episodes
after a top-up; or 20 episodes split 10 A and 10 B, which is what I would
choose, because A's ground truth is worth more than the extra statistical power
of a bigger single-source batch.

Preparation is free: mining, selection rules 1 to 5, image building, and brief
extraction call no model.

## What would make me stop

* **A's yield was zero and B's rate was zero.** Both stop conditions fired. The
  conclusion is not that the class is rare in the wild, but that it does not
  occur between *human*-authored changes at anything like the rate it occurs
  between agents. Three sources agree on zero — 50 CooperBench pairs, 227
  merges, 101 replayed clean merges — against the Farm's own 2 in about 20
  episodes. Mining is finished as a source of episodes.
* **Still live:** if the claim map keeps naming chains it cannot explain. On real
  diffs it produced `showtype -> isolated_filesystem` from a documentation
  change, and a chain terminating in a definition named `f`. That is worse than
  its behaviour on the constructed corpus, and any claim about the engine has to
  account for it.
* **If the claim map names the mechanism in fewer than half of the hits** — that
  is already the pattern in CE-006 and CE-007, and it means the engine's
  demonstrated ability is relating two changes rather than explaining them. A
  claim about the engine should then be made at that altitude and no higher.
