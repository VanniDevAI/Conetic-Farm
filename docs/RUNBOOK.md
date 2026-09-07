# Runbook — running a campaign

## Preconditions

```bash
# 1. Docker (not running by default in this environment)
dockerd >/tmp/dockerd.log 2>&1 &

# 2. Sandbox base image (no registry pull; built from the host rootfs)
scripts/build_base_image.sh

# 3. Redis, for coop-mode inter-agent messaging
scripts/start_redis.sh

# 4. Credentials
cp .env.example .env && chmod 600 .env     # set OPENROUTER_API_KEY

# 5. Verify — must print READY
python3 scripts/preflight.py
```

Preflight is the gate. It checks the credential file's permissions and
git-ignore status, that the key **reaches CooperBench's process** (it does not by
default — see `docs/ENVIRONMENT.md` §1), that OpenRouter *accepts* the key and
what credit remains, the sandbox, egress, the harness, and Redis.

## Dry run before spending anything

```bash
scripts/oracle_dryrun.py --episode <episode_id>
```

Substitutes each feature's **gold** patch for the agent's and runs the whole
triad — A alone, B alone, three-way merge, merged tests, classification. The
expected label is known from the dataset's own conflict label, so a mismatch
means a bug in our grading or in the task image, found before any money is spent.
It costs nothing: no model is called.

## The campaign

```bash
python3 -m farm.run --campaign c01 --limit 20
```

Reads the frozen plan at `config/task_plan.json` and refuses to start if it is
not marked `frozen`. Per episode: build the task image if needed, capture the
base state as a git bundle, reserve budget, attach the checkpoint snapshotter,
run the two coop agents, collect every artifact, settle the real cost from token
counts, grade the triad, classify, and rewrite the manifest.

Useful flags:

| flag | effect |
|---|---|
| `--limit N` | run only the first N episodes of the plan |
| `--budget` | override the cap (default $50, or `FARM_BUDGET_USD`) |
| `--agent-timeout` | per-episode wall-clock ceiling (default 3600s) |
| `--data-root` | where episode data lands (default `/home/user/farm-data`) |

**Safe to interrupt.** The ledger is append-only and fsync'd, and the manifest is
rewritten after every episode, so a killed campaign leaves an accurate spend
total and a complete index of what ran. Re-running continues into a new attempt
directory rather than overwriting anything.

## Spend

Two independent ceilings:

* **Campaign cap** — `farm/cost.py`. Budget is reserved before an agent starts
  and settled from real token counts afterwards; a reservation that would cross
  the cap stops the campaign rather than shrinking the work silently.
* **Per-agent cap** — `cost_limit: 2.0` in `config/agent_config.yaml`, enforced
  inside the harness. Stops one runaway agent before the campaign cap notices.

Cost is always computed from token counts against `config/pricing.json`, never
from the harness's reported figure — that figure is `0.0` on any pricing
failure, which is how CooperBench's own results table recorded $0.00 for an
agent that consumed 400k+ billable tokens. A settlement that would be $0 despite
real usage raises rather than being recorded.

## Where the data goes

```
$FARM_DATA_ROOT/
├── manifest.json                    campaign index (also committed, paths only)
├── ledger.jsonl                     append-only spend ledger
├── campaign_<name>.log
└── episodes/<episode_id>/
    ├── manifest.json
    ├── base/                        base.bundle, base_commit.txt, image.json, task/
    └── attempts/attempt-001/
        ├── agents/{A,B}/            patch.diff, transcript.jsonl
        ├── raw/                     harness output, verbatim
        ├── checkpoints_raw/         per-container index.jsonl + checkpoints.bundle
        ├── merge/                   merge.json, merged.diff or conflict.txt
        ├── results/                 a_alone_*, b_alone_*, merged_*, classification.json
        └── cost.json
```

Nothing is deleted. Failed, timed-out and empty-patch attempts are kept and
appear in the manifest; only headline rates exclude them, and the exclusion is
reported with its count.

## Replaying an episode

```bash
git clone --no-checkout base/base.bundle repo && cd repo
git checkout $(cat ../base/base_commit.txt)          # pre-agent state
git apply ../attempts/attempt-001/agents/A/patch.diff
```

For the write-by-write sequence:

```bash
git clone --no-checkout checkpoints.bundle work && cd work
git log --reverse --format=%H     # oldest-first == seq 1..N in index.jsonl
git checkout <commit>             # the tree exactly as it stood at that write
```

## If something goes wrong

| symptom | cause | fix |
|---|---|---|
| `OpenrouterException - 403` | host blocked by egress policy | allowlist `openrouter.ai` for the environment |
| key rejected (401) | invalid or out of credit | rotate at openrouter.ai/keys |
| key not seen by the harness | called `cooperbench` directly | use `scripts/cooperbench`, or see `docs/ENVIRONMENT.md` §1 |
| `pull access denied` for a task image | image not built locally | `scripts/build_task_image.sh <repo> <task_id>` |
| `SELF_SIGNED_CERT_IN_CHAIN` in a build | Node ignores the system trust store | already handled by `build_task_image.sh`; check `NODE_EXTRA_CA_CERTS` |
| agents start then stall | Redis down | `scripts/start_redis.sh` |
| `no space left on device` | writable allowance spent | `docker image prune`, delete old `$FARM_DATA_ROOT` attempts |
