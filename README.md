# Conetic-Farm

Produces a **verified corpus of two-agent coding episodes** for later replay.

Each episode runs two independent coding agents on two features of the same
repository, then grades three things separately: agent A's patch alone, agent B's
patch alone, and the merge of the two. That triad is what separates the result
we care about — **both patches are individually correct and combining them
fails** — from the far more common case of an agent that simply wrote a bad patch.

This repository holds **scripts, configs, reports and the manifest index**.
Episode data and credentials are never committed.

It is independent of the Forge repo and Conetic-agnostic: an episode is a
directory of files plus a JSON manifest, and the replay contract lives in
`docs/DESIGN.md` rather than in code.

## Status

Setup, sandboxes, grading and the campaign driver are built and verified.
`openrouter.ai` is now reachable, so the last environmental blocker is cleared.

| | |
|---|---|
| CooperBench harness | installed; dataset vendored (652 pairs, 12 repos, 4 languages) |
| Local sandboxes | **verified** — TypeScript slice runs; gold patch passes 17/17, negative control fails exactly 1 test |
| Harness plumbing | **verified** — `cooperbench run` starts two coop agent containers from locally-built images, no fork |
| OpenRouter | **reachable**; `qwen/qwen3-coder` confirmed at $0.30/$1.00 per Mtok, matching the pinned table |
| Task plan (20 episodes) | **frozen** — `config/task_plan.json` |
| Expectations | **frozen** — `docs/EXPECTATIONS.md`, written before any run |
| Checkpointing | **verified** in a live harness container; bundle replays writes in order |
| Campaign driver | built (`farm/run.py`), with hard cap, manifest, and full retention |
| Agent runs | **waiting on the API key** — not present on this container |

See `docs/RUNBOOK.md` to run one, and `docs/ENVIRONMENT.md` for credentials.

## Layout

```
config/task_plan.json      the frozen 20-episode plan (seeded, stratified)
config/agent_config.yaml   temperature/seed pinning and cost-tracking overrides
config/pricing.json        pinned model prices, with provenance
docs/DESIGN.md             episode format, checkpoint format, replay contract
docs/EXPECTATIONS.md       predictions, frozen before the campaign
docs/ENVIRONMENT.md        the .env file and variable name; the egress blocker
docs/HARNESS_NOTES.md      biases in the harness and dataset, with evidence
docs/RUNBOOK.md            how to run a campaign, and what to do when it breaks
farm/plan.py               task selection and stratification
farm/cost.py               USD ledger with a hard cap
farm/grade.py              A-alone / B-alone / merged triad, three-way merge
farm/classify.py           the failure taxonomy
farm/snapshotd.py          in-container working-tree snapshotter
farm/manifest.py           episode manifest and campaign index
farm/env.py                credential loading and injection (see ENVIRONMENT.md)
farm/run.py                campaign driver: runs the frozen plan under the cap
farm/episode.py            one episode: agents, collection, grading, manifest
farm/sandbox.py            container execution: base bundle, tests, three-way merge
scripts/cooperbench           run the harness with our .env injected
scripts/build_base_image.sh   sandbox base image, no registry needed
scripts/build_task_image.sh   per-task image from the dataset Dockerfile
scripts/make_plan.py          builds and freezes the task plan
scripts/preflight.py          verifies the environment; never prints a secret
scripts/oracle_dryrun.py      grades gold patches to validate the pipeline, free
scripts/start_redis.sh        Redis for coop-mode messaging
reports/                      verification reports and the manifest index
```

## Quick start

```bash
dockerd >/tmp/dockerd.log 2>&1 &        # not running by default here
scripts/build_base_image.sh
cp .env.example .env && chmod 600 .env  # set OPENROUTER_API_KEY
python3 scripts/preflight.py            # must be READY before a campaign
```

Always invoke the harness through the wrapper, never the bare command:

```bash
scripts/cooperbench run -n c01 -r react_hook_form_task -t 153 -f 1,6 ...
```

CooperBench's `load_dotenv()` walks up from its own `cli.py`, so it never reads
this repository's `.env` — silently, as an auth error. The wrapper injects the
values into the child environment, where they win. `docs/ENVIRONMENT.md` §1 has
the measurements.

## What is retained per episode

Everything, on disk under `$FARM_DATA_ROOT`, outside this repo:

* the base repository state, as a git bundle pinned to the base commit
* agent A's patch and agent B's patch
* the merged result, or the conflict output when the merge failed
* test results for A alone, B alone, and the merge
* full agent transcripts with timestamps
* **intermediate source checkpoints** — the working tree committed to a shadow
  git repo after every write, with a monotonic sequence number and timestamp, so
  the order in which each agent built its change can be replayed. Kept separate
  from the final patches in the manifest.
* every attempt, including failures and discarded runs. Nothing is filtered.

## The distinction the corpus is built on

`farm/classify.py` assigns exactly one label per attempt. A **genuine
integration failure** requires *both* patches to pass their own tests alone, and
the merge to then fail — either textually (`integration_failure_merge`) or
semantically (`integration_failure_tests`). An agent that wrote a broken patch is
labelled `a_broken` / `b_broken` / `both_broken` and is never counted as an
integration failure, whatever the merge does.

We deliberately do **not** use CooperBench's own eval verdict for this: its
documented policy falls back to testing one agent's patch alone and scores a
pass, which turns a conflicted merge into a success. See `docs/HARNESS_NOTES.md` §1.

## Tests

```bash
/home/user/work/CooperBench/.venv/bin/python -m pytest tests/ -q
```

## Spend cap

$50 hard cap, enforced in `farm/cost.py` by an append-only ledger that survives
restarts. Cost is reserved before an agent runs and settled from real token
counts afterwards; a reservation that would cross the cap raises rather than
proceeding. Cost per task and cost per verified integration failure are reported.
