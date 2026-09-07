# Environment and credentials

## 1. The exact file and variable name

> **File:** `/home/user/Conetic-Farm/.env` (this repository's root)
> **Variable:** `OPENROUTER_API_KEY`

```bash
cd /home/user/Conetic-Farm
cp .env.example .env
chmod 600 .env
$EDITOR .env          # set OPENROUTER_API_KEY=sk-or-v1-...
python3 scripts/preflight.py
```

**Then always invoke the harness through `scripts/cooperbench`, not the bare
`cooperbench` command.** The wrapper is what makes the file above the right one;
see the trap below.

Preflight prints only the key's **length** and a **SHA-256 prefix**. It never
prints the value, not even truncated. It also *verifies end to end* that the key
reaches CooperBench's process, rather than assuming it.

### The trap: CooperBench ignores a `.env` in this repository

`cooperbench/cli.py:16` calls `dotenv.load_dotenv()` under the comment
*"load ./.env from cwd before anything reads env vars"*. **That comment is
wrong.** `python-dotenv`'s `find_dotenv()` defaults to `usecwd=False` and walks
up from the **calling module's file** (`dotenv/main.py:361-375`) — which under
an editable install is `/home/user/work/CooperBench/src/cooperbench/cli.py`. The
walk lands on `/home/user/work/CooperBench/.env`.

Measured, with a `.env` in this repo and the working directory set to this repo:

| `.env` location | cwd | key CooperBench sees |
|---|---|---|
| `Conetic-Farm/.env` only | anywhere | **none** — ignored |
| `CooperBench/.env` only | `Conetic-Farm` | loaded |
| both | `Conetic-Farm` | `CooperBench/.env` wins |

Worse, the behaviour depends on *how python is started*, because
`find_dotenv` also falls back to cwd when `_is_interactive()` or `_is_debugger()`
is true (`dotenv/main.py:361`):

| invocation | `.env` used | our repo's key seen? |
|---|---|---|
| `python -c "import cooperbench.cli"` | **cwd** (no `__main__.__file__`) | yes |
| `python script.py` | walk from `cooperbench/cli.py` | **no** |
| the real `cooperbench` console script | walk from `cooperbench/cli.py` | **no** |
| under a debugger or coverage | **cwd** (`sys.gettrace()` is set) | yes |

So a quick `python -c` check would report the key working while the actual run
cannot see it. That is why preflight verifies delivery with a real script rather
than a `-c` probe.

### The fix, and why it is safe

`load_dotenv` defaults to `override=False` (`dotenv/main.py:392`), so **a
variable already present in the environment wins over anything the harness
later finds**. `farm/env.py` reads this repository's `.env` and injects it into
the child process, and `scripts/cooperbench` is the entry point that does it:

```bash
scripts/cooperbench run -n c01 -r react_hook_form_task -t 153 -f 1,6 ...
```

The credential therefore stays in this repository, git-ignored, under our
control, and CooperBench's own lookup becomes irrelevant rather than merely
redundant. `tests/test_env.py` pins this, including a regression guard that
fails if upstream ever starts honouring cwd.

If you would rather not use the wrapper, the alternatives are to place the file
at `/home/user/work/CooperBench/.env`, or to export the variable in your shell
before invoking `cooperbench`. Both work; neither keeps the secret in a
directory this project controls.

### Why that variable name

* `mini_swe_agent_v2/models/litellm_model.py:141` passes
  `model=self.config.model_name` **verbatim** to `litellm.completion`, so a model
  string of `openrouter/qwen/qwen3-coder` selects LiteLLM's OpenRouter provider.
* LiteLLM resolves that provider's credential from `OPENROUTER_API_KEY`
  (`litellm/main.py:3369` and `:6446`), falling back to `OR_API_KEY`.
* There is no OpenRouter-specific code anywhere in CooperBench itself —
  `grep -rn OPENROUTER src/` returns nothing. The name comes entirely from
  LiteLLM.

### Keep the key on the host, out of the agent's reach

Adapter choice decides whether the credential ever enters a container:

| Adapter | Where the LLM call happens | Does the key enter the container? |
|---|---|---|
| `mini_swe_agent_v2` *(what we use)* | Host process, via LiteLLM | **No.** The container only runs shell commands via `docker exec`. |
| `claude_code` | Inside the container | **Yes** — `claude_code/adapter.py:167-171` forwards `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` in. |

We run `mini_swe_agent_v2`. The agent under test executes arbitrary shell
commands in its sandbox; it should not be executing them next to a live API key.

### Handling rules

* `.env` is git-ignored, and preflight **fails** if it is not, or if git is
  already tracking it.
* No `farm/` module logs, serialises, or echoes the value. Transcripts,
  manifests, and episode data are scrubbed of anything matching a key shape
  before they are written.
* If the key is ever pasted into a terminal that gets committed or shared,
  rotate it at openrouter.ai/keys rather than trying to scrub history.

---

## 2. Blocking issue: OpenRouter is unreachable from this environment

**This must be resolved before any agent can run. It is not a configuration
error on our side, and no key value will fix it.**

The remote execution environment's network policy denies egress to
`openrouter.ai`. The denial happens at the egress gateway, before TLS:

```
$ curl -v https://openrouter.ai/api/v1/models
> CONNECT openrouter.ai:443 HTTP/1.1
< HTTP/1.1 403 Forbidden

$ curl -sS "$HTTPS_PROXY/__agentproxy/status" | jq .recentRelayFailures
[ { "kind": "connect_rejected",
    "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
    "host": "openrouter.ai:443" } ]
```

It is denied from **inside task containers** too, so routing around it through
the sandbox is not an option:

| Host | From host | From container |
|---|---|---|
| `openrouter.ai` | 403 | 403 |
| `api.openai.com` | 403 | 403 |
| `api.together.xyz`, `api.groq.com`, `api.deepinfra.com`, `api.fireworks.ai` | 403 | 403 |
| `huggingface.co` | 403 | 403 |
| `registry-1.docker.io` blobs | 403 | 403 |
| `github.com` | 200 | 200 |
| `registry.npmjs.org` | 200 | 200 |
| `pypi.org` | 200 | 200 |
| `api.anthropic.com` | 401 (reachable) | — |
| `generativelanguage.googleapis.com` | 404 (reachable) | — |

### What would unblock it

1. **Add `openrouter.ai` to the environment's egress allowlist.** This is the
   direct fix and keeps the plan exactly as specified: Qwen3-Coder, open weights,
   two agents, via OpenRouter. The environment's network policy is set when the
   environment is created — see
   https://code.claude.com/docs/en/claude-code-on-the-web.
2. **Run the campaign somewhere with open egress** — a local machine or a VM.
   Everything in this repo is portable: `scripts/build_base_image.sh` falls back
   to a plain `docker pull node:22-slim` where registries are reachable.
3. **Point at a self-hosted endpoint.** CooperBench supports `--base-url` /
   `--auth-token` against any OpenAI- or Anthropic-compatible server
   (`docs/QWEN_LOCAL.md`). Not viable *here*: model weights come from
   HuggingFace, which is also blocked, and this container has 4 CPUs, 15 GB RAM
   and no GPU.

Options 2 and 3 change what gets measured, so neither is a silent substitution —
say which you want and the config changes to match.

---

## 3. What has been verified locally, with no key and no OpenRouter

Everything that does not require model inference is working and tested:

| Component | Status |
|---|---|
| CooperBench checkout + Python 3.12 venv | installed, `cooperbench` CLI runs |
| Dataset (652 pairs, 12 repos, 4 languages) | vendored in the checkout; no HuggingFace download needed |
| Docker daemon | started (`dockerd`); not running by default in this image |
| Sandbox base image | built locally from the host rootfs (registry blocked) |
| TypeScript task image (`react_hook_form_task/153`) | **builds**: upstream clone at the pinned commit, `pnpm install`, entrypoint |
| Gold-patch oracle run in the sandbox | see `reports/sandbox_verification.md` |
| Working-tree checkpointing | implemented and unit-tested (`tests/test_snapshotd.py`) |
| Cost ledger + hard cap | implemented and unit-tested (`tests/test_cost.py`) |
| Failure classification | implemented and unit-tested (`tests/test_classify.py`) |

Three environment-specific fixes were needed to build a task image, all recorded
in the generated Dockerfile and in every episode manifest:

1. `FROM node:22-slim` → the locally-imported base (registry blobs blocked).
2. The `apt-get` layer → an assertion the tools are present (Debian mirrors blocked).
3. `NODE_EXTRA_CA_CERTS` + `CYPRESS_INSTALL_BINARY=0` and friends — Node ignores
   the system trust store, and several packages fetch binaries from CDNs that
   are blocked.

---

## 4. Redis

Coop mode needs Redis for inter-agent messaging. The documented setup is
`docker run -p 6379:6379 redis:7`, which needs a registry pull and therefore
fails here. `scripts/start_redis.sh` builds a Redis container from source
against the local base image instead, and falls back to a host-native Redis if
one is installed.
