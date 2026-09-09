# c06 — the room as prosthetic: what the two arms actually measured

**$1.79 billed of a $10 cap. Six episodes, twelve lanes, two arms.** The
headline number favours the bare arm two to one. It should not be read as a
result about rooms, and most of this report is why.

Three things are true at once, and the order matters:

1. The roomed arm shipped half as many usable lanes as the bare arm.
2. Two of the three roomed lanes it "lost" had **finished working code in the
   container** — feature written, `npx vitest run` green, `npx tsc --noEmit`
   clean — and the harness graded them as nothing because they never ran
   `git commit`.
3. The thing the room exists to prevent, a convention collision, **did not
   occur once in either arm**. The primary endpoint has zero events on both
   sides, so no arm could have differed on it.

## The two-column table

Lane counts are out of six per arm; episode counts out of three.

| | **bare** | **roomed** |
|---|---|---|
| own-tests pass | **6 of 6 (1.00)** | **3 of 6 (0.50)** |
| both-pass | **3 of 3 (1.00)** | **1 of 3 (0.33)** |
| semantic failures shipped | **0** | **0** |
| convention hits | **0** | **0** |
| cost per passing lane | **$0.1329** | **$0.2772** |

Supporting rows, because the four above are not self-explanatory:

| | bare | roomed |
|---|---|---|
| lanes whose work reached the grader | 6 of 6 | 3 of 6 |
| lanes that produced working code in the container | 6 of 6 | **5 of 6** |
| merges attempted | 3 | 2 |
| merge outcome | conflict, conflict, conflict | conflict, and two episodes with too few patches to merge |
| failure class | textual ×3 | textual ×1 |
| stealth | not applicable (no clean merge) | not applicable |
| changed lines shipped | 499 | 334 |
| billed, attributed to lanes | $0.7977 | $0.8317 |

`own-tests pass` counts a lane green on the grader's own run of `tsc --noEmit`
and `vitest run` against the task image. `both-pass` counts an episode where
every lane passed that check — **not** a merged-tree result: every merge in this
run conflicted, so no combined suite ever ran, in either arm.

### Prediction against observation

Frozen in `config/c06_room.json` before the first lane, as rates:

| | predicted | observed | |
|---|---|---|---|
| bare, own-tests pass | 0.50 | **1.00** | wrong, badly |
| bare, both-pass | 0.33 | **1.00** | wrong, badly |
| roomed, own-tests pass | 0.67 | **0.50** | wrong |
| roomed, both-pass | 0.67 | **0.33** | wrong |
| convention hits, bare | 1 to 3 | **0** | wrong |
| convention hits, roomed | fewer than bare | **0**, tied | untestable |

Four of six predictions missed, and the two large misses are on the **bare**
arm, not the roomed one. The prior was built from c05b, where qwen lanes on this
repository produced a working patch once in three tries; c06's bare arm went six
for six. The anomaly this run has to explain is bare's perfect score, not
roomed's ordinary one. The roomed arm landed exactly on the c05b base rate of
0.50.

## What the roomed arm's three missing lanes actually were

| episode | lane | what happened | captured |
|---|---|---|---|
| pair1 | lane1 | 68 steps. Added `author` to the Post model, wrote migration `20240909_add_author_to_post`, added a cursor-paginated `byAuthor` procedure and a new test file. Ran `npx vitest run` — 2 files, 2 tests, green. Ran `npx tsc --noEmit` — clean. Then wrote a prose summary. **Zero git commands, all 68 steps.** | nothing |
| pair1 | lane2 | 20 steps. Added `byDateRange`. `tsc --noEmit` clean. Same ending. **Zero git commands.** | nothing |
| pair3 | lane2 | Ran `npx prisma studio`, a foreground server, at 08:17:08 and wedged behind it for 49m41s until the wall clock. Salvage found a clean tree. | nothing, correctly |

Two of the three are a harness fault, not an agent fault, and I verified it
independently of the analysis that first flagged it: across all fourteen lane
trajectories, every lane whose transcript contains a `git commit` has a
non-empty patch and every lane without one has a zero-byte patch. Six of six
bare lanes committed and pushed. The two pair1 roomed lanes committed nothing.

The cause is a CooperBench rule doing the wrong job in solo mode. Grading is of
the **published** artifact — a pushed PR or branch — so that a colleague can
read what is coming. In coop that is the point of the benchmark. In a solo lane
there is no colleague and no channel, so the rule measures whether the model
remembered to commit. The containers run `--rm`, so the evidence is destroyed
before the runner sees the empty patch.

**Fixed, and the fix is in this commit.** A solo lane that publishes nothing now
has its working tree diffed against the task's base commit, and that is graded,
recorded as `patch_salvaged` so it is never mistaken for a push. Coop is
untouched. See `docs/HARNESS_NOTES.md` §16 and
`tests/test_solo_submission_capture.py`.

Counting the work that existed rather than the work that was captured, the
own-tests row reads **6 of 6 bare against 5 of 6 roomed** — with the caveat that
the two rescued lanes are green on the *agent's own* run of the same two checks
inside the container, not on the grader's run against a clean image. Nobody
should trust that number until the lanes are re-run under the fixed harness.

## The one roomed episode that completed, and what it cost

`c06-pair2-roomed` is the only episode in either arm that used the repair pass.
Lane 2 ran past the 50-minute wall clock; salvage took 261 lines out of its
container, which then passed the suite alone. The integration check flagged a
conflict, both lanes got one repair pass, and the episode finished with both
lanes green and a merge that still conflicted on three files. It is also the
only episode where the roomed arm shipped **more** than its bare twin: 302
changed lines against 180 on the identical task and image.

Two bookkeeping faults in that episode are fixed here:

* The ledger recorded `salvaged_lines: 0` for both timed-out lanes, because the
  timeout path's return value was discarded in favour of the cost-watchdog's
  counter, which only the ceiling path ever sets. The run log says 261; the
  ledger said 0. Anyone scoring from `spend.json` alone scored a passing
  261-line patch as a total loss.
* The repair pass rewrote `lane2.patch` in place, destroying the exact artifact
  that `initial_grade.json` had scored. The pre-repair patch is now kept
  alongside as `<lane>_initial.patch`.

## Why this design cannot answer the question it was built to ask

Stated plainly, because the table above will otherwise be read as a finding.

**The primary endpoint never fired.** Convention hits — duplicate migration
ordinals, duplicate route paths, duplicate config keys — are what the room
exists to prevent, and are `0, 0, 0` in all six episodes of both arms. The
briefs were varied within a domain specifically to make collisions possible, and
the lanes still picked disjoint names every time. Zero events on both sides
means the arm comparison rests entirely on patch presence, which is the thing
the harness was getting wrong.

**Arm is perfectly confounded with order.** Bare ran first in all three pairs,
roomed second. Both 50-minute stalls landed in the roomed arm; under a null of
two stalls placed at random among twelve lanes, that happens 23% of the time.
Nothing separates "the room caused it" from "the second lane of each pair caused
it" in this data.

**The sample cannot reach significance.** Six lanes an arm gives Fisher two-sided
p = 0.18 for 6/6 against 3/6, and 0.09 one-sided. At the episode level, which is
the honest unit since both lanes of a pair share a task, an image and a time
window, 3/3 against 1/3 is p = 0.40. With three paired episodes the smallest
p-value achievable under any outcome whatsoever is 0.125. The design could not
have produced a significant result even if every roomed lane had failed.

**No code-quality difference was measured at all.** Every graded lane in both
arms passed its own suite — nine for nine. Every merge in both arms conflicted.
The arms differ in whether patches existed, not in whether the code worked.

## A cost finding worth keeping

Agent-reported cost across the run totals **$0.1518**. The provider billed
**$1.7899**. That is a ratio of **11.8×**, against 1.75× and 6.5× measured
earlier in this campaign, and it is the widest gap yet. `result.json` reports
`input_tokens: 0` for every lane, so the self-reported figure is derived from a
token count that is simply missing. Any ceiling enforced against the agent's own
number is not a ceiling. c06's ceilings read the provider meter, which is why
this run finished at 18% of its cap instead of over it.

Per-lane attribution carries a known smear: lane costs sum to $1.6294 against a
meter delta of $1.7899, so $0.1605 of billing settled after the last lane's read
and belongs to no lane. The run total is authoritative; the per-lane split is
approximate, and the per-arm figures in the table inherit that.

## What would actually settle it

In order of what each one buys:

1. **Re-run the same six lanes under the fixed harness.** If the two zero-line
   pair1 lanes land 100–200 line patches that pass their own suites, the
   measured arm difference was capture, not capability, and this run says
   nothing about rooms. This is the cheapest experiment available and it should
   run before any new episodes.
2. **Counterbalance arm order within each pair,** so "roomed" stops meaning
   "second".
3. **Raise n to 12–15 episodes per arm.** At an effect size of 0.50 against 1.00
   that is roughly what 80% power needs. Three paired episodes cannot get there.
4. **Ablate the room into its two halves** — the factual blocks (assumes / who
   looks at it / already claimed) against the closing protocol block. The
   surviving roomed lanes shipped fine with the facts in front of them; the
   candidate mechanism for the missing commits is that the room is appended
   *after* the task brief and its final imperative list ends at "Only then start
   editing", so the last thing the model reads is an instruction to begin rather
   than to submit. That is n=2 and a hypothesis, not a finding — pair2's lane1
   read the identical text and committed normally.
5. **Make a collision possible on purpose.** Until the convention graders fire
   at all, the room's actual thesis is untested by any arm.

## Verdict

The room was not shown to help and was not shown to hurt. What this run
established is about the instrument: a solo lane's uncommitted work was being
destroyed silently, the salvage ledger under-reported a rescued 261-line patch
as zero, the repair pass overwrote the artifact it had just graded, and the
provider bills nearly twelve times what the agent thinks it costs. All four are
fixed here. The next ten episodes should start from the re-run in step 1, not
from this table.
