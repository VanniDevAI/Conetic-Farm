# Episode artifacts

`farm/episodes/<id>.json` says what an episode found. What it cited lived under
`/home/user/farm-*` in a container that is rebuilt from scratch on restart, so
the record survived and its evidence did not. These directories are the
evidence, in the repository, beside the record.

| directory | episode |
|---|---|
| `CE-004/` | zod → zod-multipleof-hints. Semantic, stealthy: the first coordination failure the Farm produced across a published-package boundary. |
| `CE-004-control/` | query-core → qc-staleness-panel. The matched control, identical in every respect except that the contract lane A changed is **not** exported. It nulls, and the pair of them is what the published-surface rule rests on. |

Same layout in each:

| path | what it is |
|---|---|
| `patches/provider_agent_A.patch` | lane A's patch, in the provider repository |
| `patches/consumer_agent_B.patch` | lane B's patch, in the consumer repository |
| `patches/*_tests_*.patch` | the graded test patches, applied by the harness, not by an agent |
| `results/a_alone.json` | lane A's branch against the provider's graded tests |
| `results/a_full_suite.json` | lane A's branch against the provider repository's **entire** suite — this is what makes the stealth flag decidable |
| `results/b_alone.json` | lane B's branch against the consumer's tests, with the provider from the registry |
| `results/integrated.json` | lane B's tests with the provider **rebuilt from lane A's patch**, packed and installed over the registry copy. The measurement. |
| `merge.json` | the merge outcome, and why it is what it is |
| `provider_build/*.tgz` | the provider package actually installed for `integrated` — the exact bytes, not a rebuild |
| `provider_build/build.log` | how it was built |
| `trajectories/agent_*_solo_traj.json` | what each agent did. `_full_traj` where a lane's context was compacted; the trimmed file drops the earlier segments. |
| `config/lane_*.json` | model, ceiling and settings each lane ran under |
| `pair_result.json` | the runner's own summary, verbatim |
| `cost.json` | what it billed, and the limits of that number |
| `FILES.json` | every file with its size, sha256, and the path it came from |

## Read `merge.json` before reading `clean`

Both seam episodes merge cleanly, and in neither case is that a result. The two
lanes are in **different repositories**; there is no shared path, so git has
nothing to conflict on. `"structural": true` in `merge.json` says exactly this.
A clean merge here means the failure had no textual signal at all, which is the
point of the episode, not evidence that the change was safe.

## One stale field in the raw runner output

`CE-004-control/pair_result.json` carries `"stealthy": true` on a pair that
never fired. That predates the corrected definition — stealth requires a clean
merge **and** both suites green **and** the product wrong, and this control's
product is right. The episode record (`farm/episodes/CE-004.json`,
`matched_control.failure_class: null`) is correct. The raw file is left exactly
as the runner wrote it, because an archive that quietly corrects its sources is
not an archive; this note is the correction.

## Reproducing `integrated`

The graded claim is one line: rebuild the provider from `provider_agent_A.patch`,
pack it, install it over the consumer's registry copy, and run the consumer's
tests. `pair_result.json` carries the exact `build_cmd`, `restore_cmd` and
`registry_dependency` used. The tarball in `provider_build/` is the output of
that build from the run itself, so a reader who does not want to rebuild can
install it directly and get the same result.
