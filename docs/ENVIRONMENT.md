# Environment and credentials

## 1. The exact file and variable name

> **File:** `/home/user/Conetic-Farm/.env`
> **Variable:** `OPENROUTER_API_KEY`

Create it from the template and lock it down:

```bash
cd /home/user/Conetic-Farm
cp .env.example .env
chmod 600 .env
$EDITOR .env          # set OPENROUTER_API_KEY=sk-or-v1-...
```

Then verify without revealing anything:

```bash
python3 scripts/preflight.py
```

Preflight prints only the key's **length** and a **SHA-256 prefix**. It never
prints the value, not even truncated. Nothing else in this repo reads the value
except to hand it to the model client.

### Why that name, and why that file

Both facts come from the harness's own source, not from convention:

* `cooperbench/cli.py:16` calls `dotenv.load_dotenv()` with no path —
  *"load ./.env from cwd before anything reads env vars"*. So the `.env` that
  matters is the one in the **directory `cooperbench` is invoked from**. Our
  runner always invokes it from the repo root, so `/home/user/Conetic-Farm/.env`
  is the file that gets read.
* `mini_swe_agent_v2/models/litellm_model.py:141` passes `model=self.config.model_name`
  **verbatim** to `litellm.completion`. A model string of
  `openrouter/qwen/qwen3-coder` therefore selects LiteLLM's OpenRouter provider.
* LiteLLM resolves that provider's credential from exactly one variable —
  `litellm/main.py:3369` and `:6446`: `get_secret_str("OPENROUTER_API_KEY")`.

There is a second `.env` that also gets loaded, at
`platformdirs.user_config_dir("mini-swe-agent")/.env`
(`mini_swe_agent_v2/__init__.py:46`). We do **not** use it — one file, one place,
so there is one thing to audit and one thing to shred.

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
