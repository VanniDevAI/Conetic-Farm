# DRAFT — not filed

Upstream issue draft for CooperBench (`akhatua2/CooperBench`, pinned here at
`b0262a7b64df945944b5063745369bb2d78d4b57`). **Do not file without a maintainer
check** — see *Before filing* at the bottom.

---

## Title

`_nudge_unsubmitted` cannot work on the `LimitsExceeded` path, which is the path
that needs it

## Summary

`DefaultAgent._nudge_unsubmitted()` exists to catch an agent that ends with
unshared work: it appends an instruction to submit and lets the loop continue.
On the `LimitsExceeded` exit path it can never have any effect, because the same
limit that ended the agent also blocks the model call that would let it comply.
The instruction is appended to the transcript and no model ever reads it.

That path is not an edge case. It is the ordinary ending for any agent given a
`step_limit` or `cost_limit`, and it is precisely the ending where work is most
likely to be unsubmitted — the agent ran out of budget mid-task rather than
deciding it was finished.

## Where

`src/cooperbench/agents/mini_swe_agent_v2/agents/default.py`

```python
# run(), ~line 194
while True:
    try:
        self.step()
    except InterruptAgentFlow as e:
        self.add_messages(*e.messages)
    ...
    if self.messages[-1].get("role") == "exit":
        if self._nudge_unsubmitted():
            continue                      # (1) ask the agent to submit
        break

# query(), ~line 386
def query(self) -> dict:
    if 0 < self.config.step_limit <= self.n_calls or 0 < self.config.cost_limit <= self.cost:
        raise LimitsExceeded(...)         # (2) raises before any model call
    ...
    self.n_calls += 1                     # (3) never reached on that path
```

`LimitsExceeded` subclasses `InterruptAgentFlow`, so it is caught at (1), its
`role: "exit"` message is appended, and `_nudge_unsubmitted()` runs. It returns
`True`, the loop `continue`s, `step()` calls `query()` — and (2) raises again
immediately, because `n_calls` was not incremented at (3) and `cost` did not
change. Two nudges later (`MAX_SUBMIT_NUDGES = 2`) the loop breaks.

Net effect: two "submit your work" messages in the transcript, zero model calls
in response to them, and an empty submission.

## Why it matters

Grading sees an empty patch, which is indistinguishable from an agent that never
wrote any code. The failure is silent and the transcript looks as though the
agent was told to submit and declined.

The comment on `_nudge_unsubmitted` records the motivating case — an agent that
did this "after 943 steps of real work" — so the intent is clearly to cover
exactly this situation.

## Reproduction

Any task, with a step limit low enough to hit:

```
step_limit = 5      # or any value the agent will reach
```

Expected: after the limit trips, the agent gets one chance to `git add` and
submit.
Actual: the transcript ends with the nudge text, `n_model_calls` unchanged from
before the nudge, `exit_status: "LimitsExceeded"`, `submission: ""`.

## Suggested fix

The nudge needs a budget the limit check will honour. Options, cheapest first:

1. **Grant a small allowance when nudging.** In `_nudge_unsubmitted`, before
   returning `True`, raise the effective ceiling by the number of calls the
   nudge needs (e.g. `self.config.step_limit = self.n_calls + 2`). Bounded by
   `MAX_SUBMIT_NUDGES`, so it cannot loop.
2. **Exempt nudge turns from the check.** A `self._in_nudge` flag that `query()`
   consults, cleared once the agent responds.
3. **Check the limit after the call rather than before it**, so the agent that
   reaches the limit still gets to act on the message it was just given. This
   changes the meaning of `step_limit` by one and would need a maintainer's
   view.

(1) is the smallest change and leaves `step_limit` semantics alone everywhere
except during an explicitly bounded nudge.

## Evidence from an external harness

Observed while running CooperBench in coop mode with Qwen3-Coder across three
20-episode campaigns:

- Agents ending `LimitsExceeded` with a non-empty working tree and an empty
  submission were common enough to dominate one campaign's results.
- Working around it externally — extracting each agent's patch from its final
  working tree rather than from what it submitted — moved eligible episodes
  (both agents' patches retained) from **5 of 16** to **15 of 16**.

That workaround is ours and lives outside CooperBench; it is mentioned only as
evidence for how much the defect changes measured outcomes, not as a proposed
fix.

---

## Before filing

- [ ] Re-check against upstream `main`, not our pinned commit — this may already
      be fixed.
- [ ] Confirm the reproduction on a clean checkout with no local patches.
- [ ] Search existing issues for `nudge`, `LimitsExceeded`, `step_limit`.
- [ ] Decide whether to offer a PR for option (1) rather than only an issue.
- [ ] Strip the campaign numbers if the maintainers would rather have a minimal
      report; they are supporting evidence, not the claim.
