# c07 — how often the semantic class fires on one pair of briefs

**$2.3460 billed of a $5 cap.** Ten episodes, five per arm, the same two briefs
that produced CE-006, no seed, arms alternating through the run order.

| | **bare** | **roomed** (ablated room) |
|---|---|---|
| **semantic failures shipped** | **0 of 5** | **1 of 5** |
| textual conflicts | 3 of 5 | 3 of 5 |
| no class | 2 of 5 | 1 of 5 |
| clean merges | 1 of 5 | 1 of 5 |
| own-tests pass | 9 of 10 lanes | 8 of 10 lanes |
| lanes that published nothing | 4 of 10 | 2 of 10 |
| convention hits | 0 | 0 |
| billed | $0.7139 | $1.0044 |

Fisher two-sided on the endpoint: **p = 1.000**. At five episodes an arm the
smallest achievable p is 0.008, so this design *could* have shown something; it
did not.

## The one that fired

`c07-ep05-roomed`. Clean merge, both lanes green alone, combined tree red,
**stealth flag true**. And the mechanism is not CE-006's.

* **lane1** ("a single author's posts") added `authorId`, a `byAuthor`
  procedure, and tests that create three posts and expect `byAuthor` to return
  two of them.
* **lane2** ("posts from a given stretch of time") added an `archive`
  procedure and a test file that opens with
  `beforeEach(async () => { await prisma.post.deleteMany({}) })`.

Neither touched the other's procedure. git merged them without a murmur. In the
merged tree lane1's `get posts by author` expects 2 and receives 0.

**The shared thing is the database, not a contract.** `vitest.config.ts` sets no
`fileParallelism`, so test *files* run in parallel workers, and `.env` points
every one of them at the same `file:/workspace/repo/prisma/dev.db`. lane2's
`beforeEach` wipes the posts table out from under lane1's fixtures.

Two consequences worth stating.

**It is a race, so it may be intermittent.** Of lane1's two author tests, one
failed and one passed in the same run. A deterministic contract break would
have taken both. This is one observation of a racy failure, not a reproducible
one.

**The claim map does not describe it.** The chain recorded for this pair is
`postRouter → defaultPostSelect`, which is a true statement about the two
patches and says nothing about the mechanism. The shared resource is the
database, and no static analysis of TypeScript identifiers was going to find
"these two test files race on one sqlite file". CE-006 was a contract the claim
map could in principle have named. This one is not.

**And the repair pass did not fix it.** The engine flagged exactly the right
symptom — "the two branches merge cleanly but the combined tree fails the
repository's own checks" — the roomed arm's repair round ran, and the merged
tree failed identically afterwards. One repair round given the correct
diagnosis was not enough.

## Prediction against observation

| | predicted | observed | |
|---|---|---|---|
| **roomed ships the same, not fewer** | same | **1 vs bare's 0** | **right** |
| roomed semantic | 1 or 2 of 5 | 1 of 5 | **right** |
| arm difference | \|bare − roomed\| ≤ 1 | 1 | **right** |
| bare semantic | 1 or 2 of 5 | **0 of 5** | wrong, just under |
| convention hits | 0 both arms | 0 both arms | right |
| cost | ~$3.50 | $2.35 | right, under |
| roomed submit-skip | ≤ 1 of 10 | **2 of 10** | wrong |
| clean merges | 4 to 6 of 10 | **2 of 10** | **wrong** |

The load-bearing one held. The room is generated from the base tree before
either lane starts, so it cannot describe what the other lane is doing right
now; it did not prevent the failure, and the arm that shipped one was the
roomed arm.

I keep getting merge outcomes wrong in both directions — "conflict everywhere"
in c06b when 3 of 6 merged, "4 to 6 clean" here when 2 of 10 did. Whether two
patches collide textually is apparently not something I can predict from the
briefs.

## What the ablation did

The room's closing "only then start editing" block was removed and the facts
moved in front of the task, on the hypothesis that a prompt ending on an
instruction to begin was suppressing the submit step.

| | roomed | bare |
|---|---|---|
| c06 + c06b (protocol present, room last) | 5 of 12 | 1 of 12 |
| c07 (protocol ablated, facts first) | **2 of 10** | **4 of 10** |

The roomed rate fell and the bare rate rose, and the arms swapped places.
Neither movement is significant — roomed across runs p = 0.381, arms within
c07 p = 0.628 — so the honest reading is that **the ablation removed a
difference rather than created one**, and the underlying rate is somewhere
around a quarter to a third of lanes in either arm.

That is not nothing. Two to four lanes in ten doing the work and never
publishing it is a large tax, and it is now visibly a property of the model and
the harness rather than of the room. It costs nothing because the working tree
is captured; it would have cost the entire episode a week ago.

## What this run does not support

**A rate.** One semantic failure in ten episodes of one task pair. The number
generalises to these two briefs and no further, and the design was chosen to
answer "does it recur", not "how often".

**A difference between arms.** p = 1.000 on the endpoint.

**That CE-006's mechanism recurs.** It did not. CE-006 was a contract
tightening; c07's failure was a shared-database race. Two clean merges in ten
episodes produced two different ways for correct-alone branches to be wrong
together, which is a more interesting result than either alone: the class is not
one bug shape.

## Costs and the ledger

$2.3460 billed against a $5 cap; $1.7183 attributed to lanes, $0.6277 not. The
gap is episode 1's two repair lanes, whose costs were lost when the runner
crashed before writing its record, plus the usual settlement lag. The recovered
record says so rather than reporting $0.1351 as what that episode cost.

Episode 1 crashed after being paid for: c07 keys its predictions by endpoint
(`bare_semantic`) and the runner read `plan["predictions"][arm]`. Both lanes and
both repair lanes had run and been graded twice. The lookup is now tolerant, a
test checks every shipped plan resolves for every arm it contains, and the
episode's record was rebuilt from the artifacts on disk instead of being paid
for twice.

## Two things worth doing next, neither of them more of this

1. **Grade the 30 census pairs whose graded test patches apply to the merged
   tree.** No agents, no spend. c07 cost $2.35 to observe one failure; those 30
   pairs are already built and already have tests on both sides.
2. **Fix the corpus's test isolation, or decide not to.** Every episode on this
   repository shares one sqlite file across parallel test workers. That makes
   shared-resource races findable, which is real, but it also means any future
   semantic failure here has to be checked against it before being called a
   contract failure. c07-ep05 needed that check and passed it; the next one
   might not.
