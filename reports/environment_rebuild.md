# Environment rebuild — campaign `c01`

**Why this file exists.** The setup work on `claude/conetic-farm-setup-wl35st`
was done in a container that no longer exists. Campaign `c01` therefore did not
start from that environment; it started from a *reconstruction* of it. Anything
that differs between the two is a potential confound, so the reconstruction is
recorded here rather than assumed to be equivalent.

Rebuilt: 2026-09-07, immediately before `c01`.

---

## 1. What was gone, and what it was replaced with

The container was fresh: no CooperBench checkout, no Docker daemon, no sandbox
base image, no task images, no Redis, no `.env`, no `$FARM_DATA_ROOT`.

| Component | Original | Rebuilt as | Equivalent? |
|---|---|---|---|
| CooperBench checkout | `/home/user/work/CooperBench` | cloned from `github.com/cooperbench/cooperbench`, symlinked to the original path | **yes** — see §2 |
| Dataset | vendored in the checkout | vendored in the checkout | **yes** — see §2 |
| Python env | `.venv`, Python 3.12, editable install | same | yes |
| Docker daemon | `dockerd` | same, 29.3.1 | yes |
| Sandbox base image | host rootfs via `docker import` | same path, unchanged script | yes — same substitution as `docs/EXPECTATIONS.md` §4.4 |
| Redis | `scripts/start_redis.sh` | same; took the host-native branch | yes |
| Task images | built per episode | rebuilt per episode | yes |

## 2. The checkout is the pinned one, not merely a recent one

`config/task_plan.json` pins `source.cooperbench_commit`. The clone's `HEAD`
matches it exactly:

```
b0262a7b64df945944b5063745369bb2d78d4b57
origin = https://github.com/cooperbench/cooperbench
```

The dataset was verified against the frozen record rather than trusted:

* `gold_conflict_report.json` summary: **652 pairs, 499 conflicts, 76.5%** —
  identical to the figures `docs/EXPECTATIONS.md` §4.2 was written from.
* All **20/20** planned episodes resolve, each to a task directory that exists,
  each with a `has_conflict` label matching the plan's `gold_has_conflict`.
* Strata intact: 10 conflicting / 6 compatible / 4 control.
* Language mix intact: 15 Python, 4 TypeScript, 1 Rust — the `language_floor`
  of 4 TypeScript episodes is met.

## 3. Two code changes the rebuild forced

Both are recorded because both were latent bugs that only a rebuild could
surface, not adjustments made to get a nicer result.

1. **`farm/env.py` imported `platformdirs` in the wrong interpreter.**
   `shadowing_env_files()` is a warning-only leak-surface check, but it imported
   a *harness* dependency — one that lives in CooperBench's venv, not in the
   system Python that runs `scripts/preflight.py`. Preflight therefore died with
   `ModuleNotFoundError` instead of reporting READY. It now falls back to the
   path `platformdirs` would return.

2. **`tests/test_env.py` hardcoded the checkout path.** Relocating the checkout
   made `test_cooperbench_ignores_a_dotenv_in_this_repo` *skip*. That test is the
   regression guard for a failure that is already silent; a skip that hides it
   defeats its purpose. It now honours `FARM_COOPERBENCH_DIR`.

Test suite: **45 passed / 1 skipped → 46 passed / 0 skipped.** The dotenv guard
now actually runs, and confirms CooperBench still ignores this repository's
`.env` while the child-environment injection reaches it.

## 4. Grading re-validated in the rebuilt container

`reports/grading_validation.md` was produced in the old container. Both of its
cases were re-run here with the free gold-patch oracle — no model called, no
money spent — and both reproduce:

| Episode | Expected | Got | |
|---|---|---|---|
| `react_hook_form_task/task153 f1+f6` (conflicting, TS) | `integration_failure_merge` | `integration_failure_merge` | **match** |
| `pallets_jinja_task/task1559 f7+f8` (compatible, Py) | `both_pass_merge_passes` | `both_pass_merge_passes` | **match** |

**One difference worth recording.** In the conflicting case, A's *partner* suite
now reports `error` where the frozen report recorded `fail`:

```
frozen:   A alone: own=pass  partner=fail
rebuilt:  A alone: own=pass  partner=error
```

The label is unchanged, and it is unaffected by the difference: the
classification depends on each agent's **own** suite plus the merge outcome, and
both are identical. It is noted because it is a real environment-dependent
difference in how a partner suite fails, and the honest place for it is here
rather than nowhere.

## 5. The price cross-check `EXPECTATIONS.md` deferred

Appendix A of `docs/EXPECTATIONS.md` pinned Qwen3-Coder's price from LiteLLM's
registry and flagged it **unverified**, because `openrouter.ai` was unreachable:
*"Re-verify against https://openrouter.ai/models before trusting the totals."*

`openrouter.ai` is now allowlisted, so that re-verification was finally possible.
Live `GET /api/v1/models`:

| | pinned (`config/pricing.json`) | live |
|---|---:|---:|
| prompt | $0.30 / Mtok | **$0.30 / Mtok** |
| completion | $1.00 / Mtok | **$1.00 / Mtok** |
| context | 262,100 | 262,144 |

**They agree.** The corrected per-episode estimate of **$0.34** stands on
verified prices, and the `$9` campaign projection with it.

*(Note: `config/pricing.json` already carried a `cross_checked_live: agreed:
true` claim dated the same day, while `EXPECTATIONS.md` Appendix A stated
openrouter.ai was unreachable and the check could not be done. Those two frozen
statements contradict each other. The check above is a real one, run against the
live endpoint, and it agrees with the pinned table — so the pinned numbers are
correct regardless of which frozen claim was accurate.)*

## 6. Credentials

`OPENROUTER_API_KEY` arrived as a process environment variable. It was written
to `/home/user/Conetic-Farm/.env` (mode `0600`, git-ignored, untracked) so the
documented `scripts/cooperbench` injection path is used unchanged. Preflight
confirms end-to-end that the key reaches CooperBench's process, and OpenRouter
accepts it (not free-tier, `usage=$0` at campaign start, no key-level credit
limit set — so the $50 campaign cap is the binding ceiling, not the balance).

## 7. Preflight

```
READY WITH WARNINGS — 1 warning(s):
  - huggingface.co:443 — `cooperbench prepare` (not needed: dataset is vendored)
```

The single warning is the one host still blocked, and it is not on any path this
campaign uses. Everything else passes, including the three that were blocking:
`.env`, the Docker daemon, and the harness checkout.

## 8. New: episodes are published as they complete

The container this campaign runs in is ephemeral, and `$FARM_DATA_ROOT` is
outside git by design. A reclaim would take every finished episode with it —
and unlike compute, **spend is not recoverable by re-running**. So `farm/publish.py`
archives each episode into `results/campaigns/c01/` and pushes it before the next
episode starts, bounding a loss to the episode in flight.

It refuses to publish an artifact containing a credential shape (rather than
redacting one, which would hide that a key reached a transcript at all), never
archives `base/base.bundle` (a full clone of the repo under test, reconstructible
from the pinned commit beside it), and stops the campaign on a failed push rather
than piling up unsaved paid-for episodes.
