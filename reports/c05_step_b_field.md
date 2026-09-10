# c05 step B — one episode of three, and the cost model was wrong

**$10.47 spent against a $10 cap.** One episode produced a measurable result.
The second produced nothing from two lanes that between them billed $4.91, and
the third never started.

That is a poor return and the reasons are worth more than the result.

## What each episode did

| | ep1 engagement | ep2 feed | ep3 api |
|---|---|---|---|
| lanes with a patch | **3 of 3** | 0 of 2 attempted | not started |
| each lane alone | pass, pass, pass | — | — |
| merge | **conflict**, `prisma/schema.prisma` | — | — |
| merged suite | not reached | — | — |
| **class** | **textual** | none measured | — |
| stealth | not applicable | — | — |
| migration ordinals | **0** | 0 | — |
| route paths | **0** | 0 | — |
| config keys | **0** | 0 | — |
| billed | ~$4.5 | $4.91 | $0 |

### ep1, the one that worked

Three lanes, three ordinary features on one application, no channel between
them. Every lane produced a working feature that passes the repository's own
`tsc --noEmit` and unit suite on its own branch — 409, 381 and 137 lines.

`git` refused the merge on `prisma/schema.prisma`.

The convention graders fired **nothing**, and the per-lane detail says exactly
why: the three lanes claimed disjoint names in all three namespaces.

| lane | migration ordinal | routes claimed | config keys claimed |
|---|---|---|---|
| 1 | `20260909053000` | `comment`, `add`, `listByPostId` | `COMMENT_PAGE_SIZE_DEFAULT`, `COMMENT_PAGE_SIZE_MAX` |
| 2 | `20240909` | `react`, `getReactionTotals` | — |
| 3 | `20260909053947` | `getViewCount` | `RECORD_VIEWS` |

Three timestamps, no two the same. Three route names, no two the same. Three
config keys, no two the same. This is what "seeded overlap on the surfaces, not
on the names" produces when the briefs describe different domains: the lanes
share the *files* and collide in none of the *namespaces*. The collision was
textual, in the one file all three had to append to.

The claim map found a chain in all three pairs — `appRouter → postRouter`,
`postRouter → defaultPostSelect`, `PostViewPage → PostItem` — and classified
every pair `textual`, because they share files. None of the chain targets is on
`@trpc/server`'s published surface: they are the application's own symbols.
That is consistent with step A's rule and is the expected answer here, since
three lanes inside one application are not separated by a package boundary at
all.

### ep2, the one that burned the budget

Both attempted lanes exited `LimitsExceeded` with **zero patch lines**.

| lane | model | steps | agent-reported | billed | lines |
|---|---|---|---|---|---|
| 1 | claude-sonnet-5 | 59 | $2.51 | **$4.39** | 0 |
| 2 | qwen3-coder | 120 | $0.08 | **$0.52** | 0 |

The budget warning added before this run did fire, and did not save either lane.
It tells the agent to write `patch.txt` with what it has; both kept working
instead and were cut off. A nudge the agent can decline is not a mechanism.

## Prediction versus observed

| episode | frozen prediction | observed | verdict |
|---|---|---|---|
| ep1 | textual, on `_app.ts`; 0 ordinals, 0 route paths, ≤1 config key; stealth false | **textual**, on `prisma/schema.prisma`; 0, 0, 0 | **class right, file wrong** |
| ep2 | textual on `post.ts`, 0-1 route paths | nothing measured | not testable |
| ep3 | textual on `trpc.ts`, published surface true | not run | not testable |

The one testable prediction got the class right and the location wrong. I
expected the router table to be the conflict magnet; the schema is one layer
earlier and all three lanes reached it first. Worth keeping: on this corpus the
*first* shared file three lanes touch is the data model, not the route table.

## The three defects this campaign paid for

1. **The per-agent ceiling was $2**, set when a lane meant a one-line contract
   change. A whole feature does not fit. Raised to $2.50 for step B.
2. **An agent that hits any ceiling loses everything**, because `patch.txt` is
   written only when it decides it is done. The first lane spent $2.01 and
   returned nothing. A warning at 80% was added; ep2 shows it is not enough.
3. **The Prisma client was never regenerated** after a lane added a model, so
   every schema-touching lane failed alone with
   `Cannot read properties of undefined`. This one would have invalidated the
   campaign rather than a lane: the stealth flag is defined off the first
   lane's own branch, so a fault that reddens every schema branch reports every
   episode as non-stealthy whatever the agents did. Found because a lane whose
   409-line feature obviously worked was scored `fail`.

And one definition error, mine: the first episode came back `textual` with
`stealth=true`, which asserts that a refused merge escaped notice. Stealth now
applies only to the semantic class.

## The cost model was wrong by about 2x

Every estimate in `docs/C05_PLAN.md` was built on agent-reported cost. The
provider bills more:

| lane | agent-reported | billed | ratio |
|---|---|---|---|
| ep2 lane1 (sonnet) | $2.51 | $4.39 | **1.75x** |
| ep2 lane2 (qwen) | $0.08 | $0.52 | **6.5x** |
| c05a zod pair (earlier) | $1.88 | $4.11 | 2.18x |

The harness's own cost limit is enforced on the *agent-reported* number, so a
$2.50 ceiling is a $4.40 bill. Every forward estimate below is stated in
**billed** dollars.

## Spend

| | |
|---|---|
| step B budget | $10.00 |
| **spent** | **$10.47** |
| over cap | $0.47 |
| bought a measurable episode | ~$4.5 |
| bought nothing | ~$5.9 |

The overrun is a real defect in the runner: the meter is checked *before* a
lane starts, so a lane that begins at $4.92 under a $5.05 ceiling can still
finish above it. The guard needs a reserve equal to the worst observed lane,
not zero.

## The next ten

Same shape: three lanes, one Sonnet and two open-weight, own sandboxes, own
branches, no channel, unseeded, graded on the claim map plus the three
convention graders, with the stealth flag on every episode.

Three changes first, none of which need a decision:

* **Hard-stop the lane, not the agent.** Kill a lane at a billed-dollar ceiling
  read from the meter, and treat whatever is in the container as the
  submission, instead of asking the agent to submit and hoping.
* **Reserve before starting a lane.** The guard must refuse a lane unless the
  remaining budget exceeds the worst observed lane cost, not zero.
* **Vary the briefs within a domain.** ep1's three lanes collided in no
  namespace because the three briefs named three domains. Ten episodes should
  include some where two lanes are asked for *the same kind of thing* —
  two paginated list endpoints, two feature flags, two migrations on one table
  — which is where a convention collision actually lives.

Costed at billed rates, per episode: Sonnet $2.5–4.5, two open-weight lanes
$0.5–1.1, so **$3.0–5.6**, call it **$4.3 typical**.

| option | episodes | lanes | estimate | what it buys |
|---|---|---|---|---|
| **A. same shape** | 10 | 1 sonnet + 2 open-weight | **$30–56** | the frontier lane in every episode; the honest price of what was just run |
| **B. mixed** | 10 | sonnet in 4, open-weight in the other 6 | **$14–24** | the frontier lane where it matters, ten episodes for the rate |
| **C. open-weight only** | 10 | 3 open-weight | **$5–11** | ten episodes cheaply, no frontier lane, and ep2 shows open-weight lanes also stall |

Recommendation: **B**. The one thing ep1 established is that lanes collide on
files rather than names, and establishing a *rate* for that needs episodes more
than it needs a frontier model in each one. Four Sonnet episodes keep the
comparison honest.

Whichever option, the first two changes above should land before any of it, or
roughly half the money goes the way this campaign's did.
