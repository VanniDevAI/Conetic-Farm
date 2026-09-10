# Next week: pairs from history, not from CooperBench

CooperBench is closed for the semantic class. Its pairs are one pull request cut
into features that shipped together, co-authored to fit, and 50 of 50 scoreable
pairs pass. That is not a power problem and more grading will not move it: the
condition the class requires — two changes authored independently, neither
author having seen the other's — does not exist in that corpus by construction.

This design sources pairs from places where the condition really occurred.

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

**A's constraint is supply, and it is severe.** See
`reports/history_mining.md` for the measured yield.

## Method B: replay two changes that were written at the same time

B does not need the merge to have broken. It needs only that the two authors
were working concurrently, which git can establish from branch points alone, and
then it *constructs* the merge that branch protection prevented.

Supply here is not the problem — click alone offers 736 concurrent pairs in
twelve months. What B lacks is ground truth: a red combined tree is evidence,
but nobody at the time confirmed it was a real interaction rather than a stale
base. Every B hit needs the same reading that CE-006 and CE-007 needed.

**So A and B are complements, and the design uses both:** A for a small number
of episodes with ground truth attached, B for volume.

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

For method A the floor is different and much lower, because each episode carries
ground truth: a single A episode where the agent pair reproduces a historically
real interaction is a *demonstration*, not a sample. Ten of those are worth more
than forty of B's.

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

* **If A's yield is zero or near it** — branch protection has already removed
  the class from well-run repositories, and the interesting question moves to
  where that hygiene is absent rather than to more mining.
* **If B's semantic rate is under 2%** — 736 candidates at 2% is 15 episodes of
  real signal, which is workable; under 1% the selection rules are not selecting
  and need to be tightened before anything is paid for.
* **If the claim map names the mechanism in fewer than half of the hits** — that
  is already the pattern in CE-006 and CE-007, and it means the engine's
  demonstrated ability is relating two changes rather than explaining them. A
  claim about the engine should then be made at that altitude and no higher.
