# c06b — the same six briefs, a fixed harness, and the arms come out identical

**$2.1170 billed of a $10 cap.** Six episodes, twelve lanes, arm order
counterbalanced, the same three tasks and six briefs as c06.

Two results, and the second is the larger one.

1. **The arms are indistinguishable.** Own-tests pass 0.83 in both. Both-pass
   0.67 in both. c06's 0.50-to-1.00 gap was the harness discarding roomed
   lanes, not the room making agents worse. That was the load-bearing frozen
   prediction and it came out at the strong end.
2. **The first unseeded semantic integration failure the Farm has produced**,
   stealthy, in the bare arm — and it exists only because of a harness fix made
   hours before the run.

## The two-column table

| | **bare** | **roomed** |
|---|---|---|
| own-tests pass | **5 of 6 (0.83)** | **5 of 6 (0.83)** |
| both-pass | **2 of 3 (0.67)** | **2 of 3 (0.67)** |
| semantic failures shipped | **1** | **0** |
| convention hits | **0** | **0** |
| cost per passing lane | **$0.1229** | **$0.2664** |

Supporting rows:

| | bare | roomed |
|---|---|---|
| lanes reaching the grader | 6 of 6 | 6 of 6 |
| lanes rescued by a salvage path | 2 | 3 |
| of those, published nothing at all | 1 | 3 |
| passes on under 10 changed lines | 0 | 0 |
| changed lines shipped | 920 | 626 |
| merge: clean / conflict | 2 / 1 | 1 / 2 |
| billed, attributed to lanes | $0.6145 | $1.3322 |
| mean run position | 3.67 | 3.33 |

Fisher two-sided on own-tests pass: **p = 1.000**. On both-pass: **p = 1.000**.
The arms are not merely statistically inseparable at this size, which was
already guaranteed — they are numerically identical.

## Prediction against observation

Frozen in `config/c06b_rerun.json` and committed before a dollar was spent.

| | predicted | observed | |
|---|---|---|---|
| **gap in own-tests pass** | **≤ 0.17** | **0.00** | **right** |
| roomed, own-tests pass | 5 of 6 (0.83) | 5 of 6 (0.83) | **exact** |
| roomed, both-pass | 2 of 3 (0.67) | 2 of 3 (0.67) | **exact** |
| convention hits | 0 in both arms | 0 in both arms | **right** |
| order effect | none | none visible | right |
| bare, own-tests pass | 6 of 6, or 5 of 6 if a lane wedges | 5 of 6 | the named alternative |
| bare, both-pass | 3 of 3 | 2 of 3 | **wrong** |
| cost per passing lane | $0.10–$0.20, roomed higher | $0.1229 / $0.2664 | direction right, roomed above range |
| merge outcome | textual conflict in every episode | 3 of 6 merged cleanly | **wrong** |

The merge prediction is the interesting miss. I expected every pair to collide
textually because both briefs touch one table. Half of them merged, and the
clean merges are where the failure that matters lives.

## The semantic failure

`c06b-pair1-bare`. Clean merge, both lanes green on their own branches,
combined tree broken. Stealth flag true.

* **lane1**, asked for "a single author's posts", added an `Author` model and
  an `authorId` field, and tightened `post.add`'s input schema with
  `authorId: z.string()` — required. It updated every call site it could see,
  which were its own.
* **lane2**, asked for "posts from a given stretch of time", added three new
  `caller.post.add({title, text})` calls to `post.test.ts`. Correct against the
  contract on its branch, where no `authorId` exists.

git merges them without a murmur — lane1 changed `post.ts` and its own test
regions, lane2 added new cases elsewhere in the same file. The merged tree
fails with `ZodError: expected string, received undefined` at `authorId`.
Neither branch's CI would have said a word.

Three things about it are worth more than the episode itself.

**It only exists because of the capture fix.** lane1 ran 79 steps, wrote a full
summary of what it had built, exited `Submitted` — and never ran a single git
command. Its 242 changed lines were taken from the container's working tree.
Under the harness as it stood that morning, lane1 submits nothing, the episode
grades one lane, no merge is attempted, and this failure does not exist.

**The diff-only classifier calls this pair `textual`.** git merged it. It is
the same shape as the 65 textual-but-clean pairs the census manifest surfaced
the same day: a semantic failure hiding inside the bucket the classifier is
most confident about. The claim chain it found — `postRouter` →
`defaultPostSelect` — was right there.

**Lane1 contradicted itself and passed anyway.** `authorId` is `String?`,
optional, in the Prisma schema, and `z.string()`, required, in the tRPC input.
Its own suite is green on that inconsistency; only a second lane's call site
exposes it.

n = 1. Not reproduced, not a rate.

## A correction to my own grading rule, which cost a headline number

The run first reported **two** semantic episodes. One was mine, not the agents'.

`c06b-pair3-bare` also merged cleanly with a failing combined suite, so the
rule as written labelled it `semantic`. But lane2's own `author.test.ts` was
already failing on its own branch and simply went on failing after the merge.
Nothing interacted. Counting it would have doubled the campaign's rarest and
most load-bearing finding on the strength of one broken branch.

The rule now requires every lane green alone before a clean merge with a broken
tree can be called `semantic` — `farm/failure_class.py`, pinned by
`tests/test_failure_class_rule.py`, applied to the banked corpus by
`scripts/regrade_failure_class.py`. Exactly one record changed. The re-grade
script's dry run also caught that the seam episodes record a different product
outcome shape, and re-grading them blindly would have stripped the class off
CE-004; they are skipped by name of their keys, not by id.

## What the salvage path did, and the one arm difference left standing

Five of twelve lanes reached the grader through a salvage path:

| | bare | roomed |
|---|---|---|
| published nothing; working tree graded | 1 | 3 |
| killed at the wall clock; container diffed | 1 | 0 |

Without those, this run grades 4 bare lanes and 3 roomed, no semantic failure,
and the roomed arm looks worse again — the c06 result, reproduced as an
artifact.

The one difference that survives is not about code. Roomed lanes skip the
submit step more often: 3 of 6 here, 2 of 6 in c06, against 1 of 6 and 0 of 6
bare. Pooled that is **5 of 12 roomed against 1 of 12 bare, Fisher two-sided
p = 0.155** — suggestive, not significant, and consistent with the mechanism
proposed after c06: the room is appended after the task brief and its closing
numbered list ends at "Only then start editing", so the last instruction the
model reads is to begin rather than to submit. With capture fixed this costs
nothing but a container diff.

Roomed also costs **2.17× more per passing lane**, from the room's prompt
overhead plus a repair pass that only ever runs on the roomed arm, for no
measured benefit on any primary endpoint.

## Still unmeasured after twelve episodes

The convention graders have now logged **zero hits in twelve episodes across
two runs and both arms** — no duplicate migration ordinal, no duplicate route
path, no duplicate config key. The briefs were written to vary within a domain
precisely to make collisions possible. Agents keep choosing disjoint names.

The room's actual thesis is that naming what is already claimed prevents
collisions. Nothing in either run has tested it, because nothing has collided.
Until a collision happens, the room is being evaluated on endpoints it was not
built for, and it is losing on cost.

## Harness state after this run

Everything fixed this morning is now verified against live lanes rather than
against a re-reading of old logs:

* the working-tree fallback captured four lanes that published nothing, all
  four graded, none trivial (72 to 242 changed lines);
* the ledger recorded `salvaged_lines: 252` for the wall-clock lane, the exact
  bug that read as 0 in c06, and that lane passed alone;
* the billed-cost ceiling was the only money ceiling and no lane tripped it;
* `patch.txt` stayed out of the salvaged diffs.

## What to do next

1. **Make a collision possible on purpose.** Twelve episodes have produced no
   convention hit. Either seed one or accept that this corpus cannot test the
   room's thesis and pick one that can.
2. **Grade the 147 merge-clean census pairs.** `farm/census/manifest.jsonl`
   gives each a base commit, two lane commits and a head commit. c06b just
   showed the class occurs spontaneously and that the classifier files it under
   `textual`; those 147 are the cheapest place to look for more.
3. **Ablate the room's closing protocol block** from its factual blocks. The
   only measured effect of the room is on whether the model remembers to
   commit, and the trailing imperative list is the obvious suspect.
4. **Do not spend on more bare-versus-roomed episodes at this size.** Two runs,
   twelve episodes, identical rates, p = 1.000. Another three episodes an arm
   cannot say anything this one has not.
