# Conetic-Farm — episode corpus design

Conetic-Farm produces a **verified corpus of two-agent coding episodes**. Another
process replays them later. Nothing here imports, links against, or names any
Conetic component: an episode is a directory of files plus a JSON manifest, and
the replay contract is written down in this document rather than in code.

## 1. Independence rules

* No dependency on the Forge repo, in code, config, or documentation.
* No Conetic-specific fields in the manifest. The manifest describes *what
  happened*, not what any consumer will do with it.
* Episode data lives **outside** this repository, under `$FARM_DATA_ROOT`.
  This repo holds scripts, configs, reports, and the manifest index only.
* Secrets never enter the repo, an episode, a log, or a transcript.

## 2. Terminology

| Term | Meaning |
|---|---|
| **task** | A CooperBench `(repo, task_id)` with N feature specs. |
| **pair** | Two features `(f_i, f_j)` from one task, assigned to agents A and B. |
| **episode** | One end-to-end run of one pair: both agents, both patches, the merge, and all grading. |
| **attempt** | One execution of an episode. An episode may have several attempts; all are retained, including failures and discards. |

## 3. Episode directory layout

```
$FARM_DATA_ROOT/episodes/<episode_id>/
├── manifest.json                  # canonical description (schema v1)
├── base/
│   ├── base.bundle                # git bundle: full base repo state
│   ├── base_commit.txt            # 40-char SHA the bundle is pinned to
│   ├── image.json                 # image tag, image ID, base-layer provenance
│   └── task/                      # verbatim copy of the dataset task dir
│       ├── Dockerfile             # as built (FROM line rewritten; see image.json)
│       ├── setup.sh
│       ├── run_tests.sh
│       ├── feature<i>/{feature.md,feature.patch,tests.patch}
│       └── feature<j>/...
├── attempts/
│   └── attempt-001/
│       ├── attempt.json           # status, timing, disposition, discard reason
│       ├── agents/
│       │   ├── A/
│       │   │   ├── patch.diff             # final patch (working tree vs base)
│       │   │   ├── transcript.jsonl       # full transcript, one event per line
│       │   │   ├── raw/                   # untouched harness output, verbatim:
│       │   │   │                          #   agent<fid>.patch, agent<fid>_traj.json,
│       │   │   │                          #   conversation.json, result.json, eval.json
│       │   │   │                          # (named by FEATURE id, not agent index;
│       │   │   │                          #  CooperBench's README is out of date)
│       │   │   ├── checkpoints/
│       │   │   │   ├── index.jsonl        # one line per snapshot
│       │   │   │   └── checkpoints.bundle # git bundle: every snapshot, in order
│       │   │   └── agent.json             # model, usage, cost, exit status
│       │   └── B/ ...
│       ├── merge/
│       │   ├── merge.json         # strategy, outcome, conflicted paths
│       │   ├── merged.diff        # combined patch, when the merge succeeded
│       │   └── conflict.txt       # raw conflict output, when it did not
│       ├── results/
│       │   ├── a_alone.json       # A's patch alone vs A's tests and B's tests
│       │   ├── b_alone.json       # B's patch alone vs B's tests and A's tests
│       │   ├── merged.json        # merged patch vs both feature test suites
│       │   └── classification.json
│       └── cost.json
└── episode.log                    # orchestrator log for this episode
```

`attempts/` is append-only. Nothing is ever deleted or overwritten; a discarded
run keeps its directory and records why in `attempt.json.disposition`.

## 4. Intermediate source checkpoints

Final patches lose the *order* in which an agent built its change. The corpus
therefore also retains a replayable sequence of working-tree snapshots.

**Mechanism.** A snapshotter daemon (`farm/snapshotd.py`, copied into the task
container before the agent starts) watches the agent's working tree with inotify.
On every filesystem write, after a short debounce, it commits the whole working
tree into a *shadow* git repository (`GIT_DIR=/workspace/.farm-checkpoints`,
`GIT_WORK_TREE=<agent work tree>`). The shadow repo is invisible to the agent:
it is outside the work tree and does not touch the agent's own `.git`.

Each commit is one checkpoint, and the commit chain gives the ordering for free.

**`checkpoints/index.jsonl`** — one JSON object per line, in order:

```json
{"seq": 7,
 "ts": "2026-09-07T06:41:22.184913Z",
 "ts_monotonic_ns": 918273645000,
 "commit": "3f9a…",
 "parent": "b1c2…",
 "tree": "77de…",
 "trigger": "write",
 "paths": ["src/logic/createFormControl.ts"],
 "files_changed": 1, "insertions": 12, "deletions": 3,
 "bytes_total": 148213,
 "correlation": {"tool_call_index": 14, "tool_name": "str_replace_editor",
                 "confidence": "timestamp"}}
```

* `seq` is **monotonic from 1** within one agent within one attempt, and never
  reused. It is the replay index.
* `ts` is wall-clock UTC, ISO-8601 with microseconds; `ts_monotonic_ns` is a
  monotonic counter for ordering when two writes share a wall-clock microsecond
  or the clock steps.
* `correlation` links a snapshot to the tool call that caused it. Two sources,
  and the field says which was used: `"explicit"` when the adapter called the
  in-container `farm-checkpoint` marker command with a tool-call index, and
  `"timestamp"` when it was matched post hoc to the nearest preceding tool call
  in `transcript.jsonl`. Adapters that expose a per-tool-call hook get
  `"explicit"`; the others fall back to `"timestamp"` and remain correct in
  *order* even where the attribution is approximate.

**These are kept strictly separate from final patches.** `patch.diff` is the
deliverable patch; checkpoints are process data. The manifest lists them under
`agents.<A|B>.checkpoints`, never under `agents.<A|B>.patch`.

**Replay contract.** Given `checkpoints.bundle`:

```bash
git clone --no-checkout checkpoints.bundle work && cd work
# commits, oldest first, are exactly seq 1..N
git log --reverse --format=%H
git checkout <commit>   # working tree exactly as it stood at that snapshot
```

`base.bundle` supplies the pre-agent state; snapshot `seq=1` is the first write.

## 5. Grading: the A / B / merge triad

Every attempt produces three independent test runs, each in a **fresh** container
from the same base image:

| Run | Tree under test | Tests run |
|---|---|---|
| `a_alone` | base + A's patch | A's feature tests, then B's feature tests |
| `b_alone` | base + B's patch | B's feature tests, then A's feature tests |
| `merged`  | base + merge(A,B) | both feature test suites |

Running each agent's tests *and* its partner's against a single patch is what
lets us tell a genuine integration failure from a patch that silently already
implemented both features.

**Merge strategy** is recorded explicitly in `merge/merge.json`. Default is a
real three-way git merge of two branches rooted at `base_commit` — not
sequential `git apply`, which hides conflicts by ordering. `merge.json.strategy`
pins the exact commands so a replayer can reproduce them.

## 6. Failure taxonomy

`results/classification.json` carries exactly one `label`:

| Label | Condition | Meaning |
|---|---|---|
| `both_pass_merge_passes` | A alone ✓, B alone ✓, merge applies ✓, merged tests ✓ | Clean cooperation. |
| `integration_failure_tests` | A alone ✓, B alone ✓, merge applies ✓, merged tests ✗ | **Genuine integration failure.** Both patches are individually correct; combining them breaks behaviour. |
| `integration_failure_merge` | A alone ✓, B alone ✓, merge ✗ (conflict) | **Genuine integration failure.** Both patches individually correct; they cannot be combined textually. |
| `a_broken` / `b_broken` | that agent's patch fails its own tests alone | Individually broken patch. **Not** an integration failure. |
| `both_broken` | both fail alone | Individually broken patches. |
| `no_patch_a` / `no_patch_b` / `no_patch_both` | agent produced an empty or absent patch | Agent failure, not a code result. |
| `harness_error` | infrastructure fault (container, timeout, transport) | Excluded from rates; retained on disk. |

**The headline metric — "genuine integration failure" — is
`integration_failure_tests` + `integration_failure_merge`, and requires both
patches to pass alone.** This is the distinction the report is built on, and it
is computed from the triad, never inferred.

Both labels are counted, and they are also always reported separately, because
they mean different things to a replayer: a textual conflict is visible before
any test runs, a semantic one is not.

## 7. Task-plan strata

Every episode is assigned exactly one stratum at plan time, frozen before any
run (`config/task_plan.json`):

* **`compatible`** — the two gold patches merge cleanly and touch disjoint code.
  Ordinary cooperative work.
* **`conflicting`** — the two gold patches textually conflict
  (`gold_conflict_report.json` → `has_conflict: true`, with neither patch
  failing to apply). A conflict is *expected*.
* **`control`** — features chosen so no interaction is plausible (different
  modules, no shared symbols). Any integration failure here is a signal about
  the agents or the harness, not about the task.

Stratum is an *a priori* label from gold-patch analysis. It is never revised
after seeing a result; the outcome is recorded separately.

## 8. Retention

Nothing is filtered. Every attempt is kept, including crashes, budget aborts,
timeouts, empty patches, and runs discarded for operator error. `attempt.json`
records `disposition` ∈ {`counted`, `discarded`} with a free-text `reason`;
discarded attempts stay on disk and stay in the manifest, and are excluded only
from headline rates — where the exclusion is stated with its count.

## 9. Manifest

`$FARM_DATA_ROOT/manifest.json` indexes every episode; a copy of the index is
committed to this repo at `reports/manifest.json` (data paths only, no data).
Schema: `farm/schema/manifest.schema.json`. Every episode entry carries absolute
paths, byte sizes, and SHA-256 digests of the key artifacts so a replayer can
verify integrity without this repo.
