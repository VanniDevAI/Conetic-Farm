# `c02` instrument notes — written during the run

A running record of instrument behaviour observed while `c02` executes, kept
separate from `docs/EXPECTATIONS.md` so the frozen document is not edited
mid-run. Anything here that survives to the end folds into a dated appendix.

---

## 1. Patch extraction works, and the two sources are complementary

The `c01` failure (every patch empty) is fixed. Observed across the first
episodes of `c02`:

| Episode | Agent A | Agent B |
|---|---|---|
| `typst/6554` | `Submitted` → harness patch, 1,445 B | `LimitsExceeded` → **extracted**, 41,019 B |
| `pallets_click/2800` | `LimitsExceeded` → **extracted**, 121,079 B | `LimitsExceeded` → lost |
| `react_hook_form/153` | `Submitted` → harness patch, 908 B | `LimitsExceeded` → lost |

Two mechanisms, and each covers what the other cannot:

* An agent that reaches `Submitted` has committed and pushed, so the harness's
  own `git diff <base> origin/<agent>` returns its work.
* An agent that exits `LimitsExceeded` has pushed nothing — and, per
  `EXPECTATIONS.md` B.1, *cannot*, because the submit nudge is unreachable after
  a step-limit exit. Only working-tree extraction recovers it.

`typst/6554` is the proof that both paths are needed at once: one agent came back
through each of them, and the episode graded `b_broken` — a real label, on real
patches, which `c01` could not have produced at all.

## 2. The remaining loss: a container-teardown race

**One agent's work per episode is still lost, and the cause is timing, not
extraction.**

Extraction runs when the harness process returns. By then the harness has
already destroyed the container of whichever agent finished first:

```
git add failed: Error response from daemon: No such container: d4bb11b97878...
```

Exactly one container survives to be read — the last one the harness cleans up.
The checkpoint fallback does not cover the gap either: the destroyed container
consistently reports `checkpoints: 0, bundle_created: false`, so the snapshotter
left nothing to fall back to, while the surviving container reports 12–28
checkpoints and a good bundle.

So per episode:

* the surviving agent is always recovered;
* the other agent is recovered **only if it reached `Submitted`**, via the
  harness patch;
* an agent that exits `LimitsExceeded` *and* whose container was torn down first
  is lost.

That third case is the loss. It is not silent — `patch_source`, the extraction
warnings, and the checkpoint counts identify it per agent — but it does bias the
corpus, and in the direction that matters most.

### Why this matters more than a normal defect

A genuine integration failure needs **both** patches to exist and pass alone
(`EXPECTATIONS.md` §1). Losing one agent's patch forces the episode to
`no_patch_a` / `no_patch_b`, which is exactly the `p → 0` suppression §2.1
warns about. Observed so far: **1 of 3** billed episodes retained both patches.

This is a weaker version of the `c01` failure rather than a repeat of it. `c01`
retained *no* patches, so the headline metric was unmeasurable in principle.
`c02` retains both patches in a minority of episodes, so the metric is
measurable but on a reduced effective sample — roughly a third of the episodes
run. Any result must be reported against that reduced denominator, never against
the number of episodes started.

### The fix, for a later run

Extraction must happen when a container **dies**, not when the harness returns.
`farm/checkpoints.py` already watches `docker events`, so the hook exists: on a
`die` event, `docker cp` the working tree (or the shadow checkpoint repo) out
before Docker's `--rm` removes it. `docker exec` is not available at that point,
so the `git add -A && git diff` form has to become a copy-then-diff-on-the-host
form. Not attempted mid-campaign: changing the instrument underneath a running
measurement is how results become uninterpretable.

Also unexplained and worth fixing alongside it: the destroyed container reports
`checkpoints: 0` with **no attach error**, so the snapshotter reported a
successful attach and then recorded nothing. Whatever kills it is silent, and a
silent failure in the fallback path is why the fallback was not there when it
was needed.

## 3. Cost reconciliation is doing real work

The `c01` finding is confirmed repeatedly and is larger than first measured.
Per-episode, token-derived versus the provider's meter:

| Episode | from tokens | from provider | ratio |
|---|---:|---:|---:|
| `typst/6554` | $0.1556 | $0.5763 | **3.7×** |
| `pallets_click/2800` | $0.1002 | $1.3275 | **13.3×** |
| `react_hook_form/153` | $0.1082 | $1.2012 | **11.1×** |

Had the ledger still billed from token counts, `c02` would have believed it had
spent about $0.36 after three episodes while the account had actually been
charged $3.10. The $20 prepaid balance would have been exhausted with the ledger
reporting roughly $1.50 of a $50 cap — the campaign would have stopped on a
provider error rather than on a ceiling, mid-episode, with the spend already
gone.

The ratio is not constant (3.7× to 13.3×), so it cannot be corrected with a
multiplier; only the provider's own meter is usable.
