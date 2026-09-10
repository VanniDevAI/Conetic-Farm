# The Farm's edits to CooperBench, in a form that survives the container

CooperBench is a separate checkout at `/home/user/work/CooperBench`, pinned to
the commit in `PINNED_COMMIT`. Four campaign fixes live inside it, each marked
`[conetic-farm]` at the point of change. Until now they lived only in that
working tree, which is ephemeral: a fresh container starts from the upstream
commit and silently loses all four.

`farm-edits.patch` is that diff. `apply.sh` reapplies it.

    scripts/../vendor/cooperbench/apply.sh          # default checkout
    FARM_COOPERBENCH_DIR=/path/to/CooperBench vendor/cooperbench/apply.sh

What the patch contains, and why each exists:

| change | why |
|---|---|
| `adapter.py` forwards `environment.run_args` | `DockerEnvironment` already accepted it; only team mode ever set it, so a `run_args` key in an agent config was silently dropped. The Farm needs it to mount a provider file read-only and enforce an ownership boundary the repository's layout does not provide. |
| `agents/default.py` warns once at 80% of a ceiling | A lane cut off mid-task never writes `patch.txt`. The warning was declined by both lanes that saw it, which is why `farm/lane_budget.py` no longer asks. |
| `connectors/git.py` + `adapter.py` grade a solo lane's working tree | The published-only rule measures submission etiquette when there is no colleague to publish to. Two c06 lanes wrote green, tested features and were recorded as nothing. See `docs/HARNESS_NOTES.md` §16. |
| `AgentResult.patch_salvaged`, `runner/solo.py` | Records which of the two a patch was, so a salvaged submission is never read as a push. |

Re-export after any further edit:

    cd "$FARM_COOPERBENCH_DIR" && git diff -- src/ > vendor/cooperbench/farm-edits.patch
