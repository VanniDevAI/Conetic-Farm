# Sandbox verification — TypeScript task slice

**Date:** 2026-09-07
**Question:** can CooperBench's TypeScript task slice be run locally, in isolated
sandboxes, in this environment?
**Answer:** yes. Verified with a positive and a negative control.

## What was run

Task: `react_hook_form_task/task153` — the TypeScript slice of the CooperBench
dataset (upstream `react-hook-form`, pinned at `cec3267e12aaee01b6a17b657f9297021defdc50`).

Image built by `scripts/build_task_image.sh react_hook_form_task 153`:

```
conetic-farm/task-react_hook_form_task-153:local
sha256:38e80048dc70cfac1e8e611d3b2ac7c1d1be2badaf2b137d616dfd4697c36458
```

Each run is a fresh `docker run --rm` container, patches mounted read-only at
`/patches`, entrypoint `runner.sh <test_patch> [feature_patch]`.

## Positive control — gold patch must pass

```
docker run --rm -v .../patches:/patches \
  conetic-farm/task-react_hook_form_task-153:local f1_tests.patch f1.patch
```

```
✓ should bubble the error up when an error occurs in the provided handleSubmit
  function by leaving formState flags in a consistent state (170 ms)

Test Suites: 1 passed, 1 total
Tests:       17 passed, 17 total
exit code:   0
```

## Negative control — tests must fail without the patch

The positive control alone proves nothing: a suite that passes unconditionally
would look identical. So the same tests were run against the unmodified base.

```
docker run --rm -v .../patches:/patches \
  conetic-farm/task-react_hook_form_task-153:local f1_tests.patch
```

```
> expect(await screen.findByText('isSubmitting : false')).toBeVisible();
                      ^  at src/__tests__/useForm/handleSubmit.test.tsx:297

Test Suites: 1 failed, 1 total
Tests:       1 failed, 16 passed, 17 total
exit code:   1
```

**Exactly one test flips** — the one that describes feature 1. The suite
discriminates on the feature under test and nothing else, which is what makes a
pass meaningful.

## Isolation properties

* Real Docker containers: separate filesystem, PID, network and mount namespaces.
* `--rm`, so no state survives a run; each grading condition starts from the
  image, never from a previous run's tree.
* `runner.sh` does `git reset --hard && git clean -fdx` on exit, so even a reused
  container cannot leak a patch into the next condition.
* Dependencies are baked into the image (`node_modules_cache`), so a graded run
  performs no network installs and cannot be perturbed by registry drift.

## Environment-specific deviations from upstream

All three are forced by the environment's egress policy, are recorded in the
generated Dockerfile, and are carried into every episode manifest.

| # | Upstream | Here | Why |
|---|---|---|---|
| 1 | `FROM node:22-slim` | `FROM conetic-farm/node22-base:local` | Registry blob downloads are blocked (`production.cloudfront.docker.com` → 403). Base imported from the host rootfs; Node 22.22.2, Ubuntu 24.04 rather than Debian slim. |
| 2 | `RUN apt-get update && apt-get install -y git python3 python3-pip` | assertion that `git` and `python3` exist | Debian mirrors are not on the allowlist. The assertion fails the build loudly rather than letting a missing tool surface later as a test failure. |
| 3 | — | `NODE_EXTRA_CA_CERTS`, `CYPRESS_INSTALL_BINARY=0`, `PUPPETEER_SKIP_DOWNLOAD=1`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` | Node ignores the system trust store, so npm failed with `SELF_SIGNED_CERT_IN_CHAIN` behind the TLS-intercepting gateway. Cypress and friends fetch prebuilt binaries from CDNs that are blocked; none are used by the graded jest suites. |

**Bias note.** Deviation 1 means the userland under test is Ubuntu 24.04, not
Debian slim. Node's major version matches and the graded suites are pure JS/TS
unit tests, so the risk is low — but a test sensitive to the base distro, to a
system library version, or to a shell builtin would behave differently here than
in a run reproduced from the upstream image. Deviation 3 means the image has no
Cypress/Puppeteer/Playwright binaries; any task whose graded suite needs a
browser would fail here for infrastructure reasons rather than code reasons.
No such task exists in the TypeScript slice.

## What this does *not* establish

Sandboxes work. Agents have not run: the model endpoint (OpenRouter) is blocked
by the same egress policy — see `docs/ENVIRONMENT.md` §2.

---

# Addendum — full harness plumbing verified

Run after the sections above, same session.

## The harness resolves our locally-built image with no fork

`cooperbench.utils.get_image_name` points every task at Docker Hub:

```python
>>> get_image_name('react_hook_form_task', 153)
'akhatua/cooperbench-react-hook-form:task153'
```

That pull fails here. Docker prefers a locally-present image over pulling, so
`scripts/build_task_image.sh` now also tags the local build with exactly that
name. No fork of CooperBench, no config override.

## `cooperbench run` reaches agent launch

```
cooperbench run -n farm_smoke_01 -r react_hook_form_task -t 153 -f 1,6 \
  -m openrouter/qwen/qwen3-coder -a mini_swe_agent_v2 \
  --backend docker --setting coop -c 1 --no-auto-eval
```

Observed while running:

```
$ docker ps --format '{{.Names}} {{.Image}}'
minisweagent-8328df34 akhatua/cooperbench-react-hook-form:task153
minisweagent-90b1e015 akhatua/cooperbench-react-hook-form:task153
```

**Two coop agent containers, from our local image.** So task selection, image
resolution, container startup, Redis messaging setup and agent launch all work.
The run then stalls retrying the model endpoint, which is blocked.

## The one remaining blocker, at the exact layer the campaign uses

```python
>>> litellm.completion(model='openrouter/qwen/qwen3-coder', ...)
litellm.APIError: APIError: OpenrouterException - 403 Forbidden
```

This is the whole story of the block, and it also confirms the credential wiring
is right: LiteLLM resolved the `openrouter/` prefix to its OpenRouter provider,
picked up `OPENROUTER_API_KEY`, and issued the call. The gateway refused it. A
real key changes nothing until `openrouter.ai` is reachable.

## Checkpointing verified against a real harness container

The snapshotter was attached to a live `minisweagent-*` container — not a
synthetic one — and edits applied the way the harness applies them
(`docker exec`):

```json
{"seq":1,"ts":"...T06:47:46.434969Z","files_changed":452,"trigger":"baseline"}
{"seq":2,"ts":"...T06:47:47.184505Z","files_changed":1,"paths":["src/farm_probe.txt"],"trigger":"write"}
{"seq":3,"ts":"...T06:47:48.165206Z","files_changed":1,"paths":["src/farm_probe.txt"],"trigger":"write"}
{"seq":4,"ts":"...T06:47:49.139422Z","files_changed":1,"paths":["src/farm_probe.txt"],"trigger":"write"}
```

Snapshot 1 is the baseline: 452 files, the react-hook-form tree as the agent
found it. Cloning the exported bundle and walking commits oldest-first replays
the writes exactly:

```
2511a232  probe=
659e165c  probe=alpha,
eaa131fe  probe=alpha,beta,
1e9e1ea5  probe=alpha,beta,gamma,
```

Ordered, monotonic, non-degraded, and replayable from a standalone git bundle.

## Summary

| Stage | Status |
|---|---|
| Task image build | verified |
| Gold-patch oracle (positive control) | verified — 17/17 pass |
| Negative control | verified — exactly 1 test flips |
| Harness image resolution | verified |
| `cooperbench run` → containers → agent launch | verified |
| Redis coop messaging | verified (`+PONG`) |
| Checkpoint capture + replay in a harness container | verified |
| **Model inference** | **blocked — `openrouter.ai` 403 at the egress gateway** |
