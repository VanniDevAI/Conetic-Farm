#!/usr/bin/env python3
"""Verify the environment is ready to run a campaign.  Never prints a secret.

Checks, in order of how badly each one blocks a run:

  1. .env exists, is not world-readable, and is git-ignored.
  2. The API key variable is present and plausibly shaped.  Only its length and
     a SHA-256 prefix are ever shown -- never the value, not even truncated.
  3. The key actually reaches CooperBench's process (it does not by default --
     see check_key_reaches_harness).
  4. Docker daemon reachable and the sandbox base image present.
  5. Egress to every host a run actually needs.
  6. CooperBench importable, dataset present.
  7. Redis reachable (coop mode needs it).

Exit code 0 when a campaign can start, 1 otherwise.

    python3 scripts/preflight.py [--env-file .env]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]

# The single credential the campaign needs.  LiteLLM reads exactly this name for
# any model string prefixed "openrouter/".
KEY_VAR = "OPENROUTER_API_KEY"
ENV_FILE_DEFAULT = REPO / ".env"

# Hosts a run touches.  (host, port, why)
REQUIRED_EGRESS = [
    ("openrouter.ai", 443, "agent model inference (the API key's endpoint)"),
    ("github.com", 443, "task setup clones the upstream repo under test"),
    ("registry.npmjs.org", 443, "TypeScript tasks install dependencies"),
]
OPTIONAL_EGRESS = [
    ("huggingface.co", 443, "`cooperbench prepare` (not needed: dataset is vendored)"),
    ("registry-1.docker.io", 443, "docker pull (not needed: base image is built locally)"),
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ""


class Report:
    def __init__(self) -> None:
        self.blocking: list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str, detail: str = "") -> None:
        print(f"  {GREEN}PASS{RESET}  {msg}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def warn(self, msg: str, detail: str = "") -> None:
        self.warnings.append(msg)
        print(f"  {YELLOW}WARN{RESET}  {msg}" + (f"  {DIM}{detail}{RESET}" if detail else ""))

    def fail(self, msg: str, detail: str = "") -> None:
        self.blocking.append(msg)
        print(f"  {RED}FAIL{RESET}  {msg}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser.  Values are returned but never logged."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def check_env_file(r: Report, env_path: Path) -> dict[str, str]:
    print(f"\n{DIM}[1/8] credential file{RESET}")
    if not env_path.exists():
        r.fail(f"{env_path} does not exist",
               f"create it from .env.example and set {KEY_VAR}")
        return {}
    r.ok(f"{env_path} exists")

    mode = env_path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        r.warn(f"{env_path} is readable beyond its owner",
               f"fix with: chmod 600 {env_path}")
    else:
        r.ok("permissions are owner-only (0600)")

    check = subprocess.run(["git", "check-ignore", "-q", str(env_path)],
                           cwd=REPO, capture_output=True)
    if check.returncode == 0:
        r.ok(".env is git-ignored")
    else:
        r.fail(".env is NOT git-ignored — it could be committed",
               "add '.env' to .gitignore before continuing")

    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(env_path)],
                             cwd=REPO, capture_output=True)
    if tracked.returncode == 0:
        r.fail(".env is TRACKED BY GIT — the key may already be committed",
               "run: git rm --cached .env  and rotate the key")

    return load_env_file(env_path)


def check_key(r: Report, env: dict[str, str]) -> None:
    print(f"\n{DIM}[2/8] API key{RESET}")
    val = env.get(KEY_VAR) or os.environ.get(KEY_VAR) or ""
    source = ".env" if env.get(KEY_VAR) else ("process environment" if val else "nowhere")
    if not val:
        r.fail(f"{KEY_VAR} is not set",
               f"add it to {ENV_FILE_DEFAULT} as: {KEY_VAR}=sk-or-v1-...")
        return
    digest = hashlib.sha256(val.encode()).hexdigest()[:12]
    # Presence, shape, and a digest.  Never the value.
    r.ok(f"{KEY_VAR} present (from {source})",
         f"length={len(val)} sha256:{digest}\u2026")
    if not val.startswith("sk-or-"):
        r.warn(f"{KEY_VAR} does not start with 'sk-or-'",
               "OpenRouter keys normally do; check you pasted the right key")
    if len(val) < 32:
        r.warn(f"{KEY_VAR} is short ({len(val)} chars)", "possibly truncated")
    for other in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        if env.get(other):
            r.warn(f"{other} is also set",
                   "LiteLLM picks a provider from the model string; an unused "
                   "key here is harmless but widens the blast radius of a leak")


def check_key_reaches_harness(r: Report, env: dict[str, str]) -> None:
    """Prove the credential actually arrives inside CooperBench's process.

    This is not paranoia.  CooperBench calls `dotenv.load_dotenv()` under the
    comment "load ./.env from cwd", but python-dotenv's find_dotenv() defaults
    to usecwd=False and walks up from *its own* cli.py -- so a .env in this
    repository is silently ignored.  Worse, the behaviour is
    invocation-dependent: `python -c` has no __main__.__file__, so dotenv falls
    back to cwd and the same key appears to work.  Verified:

        python -c "import cooperbench.cli"   -> reads cwd/.env       (key found)
        python script.py                     -> reads CooperBench/.env (ignored)

    The `cooperbench` console script is a real file, so it behaves like the
    second row.  scripts/cooperbench injects our values directly into the child
    environment, where load_dotenv(override=False) cannot displace them.  This
    check confirms that end to end rather than assuming it.
    """
    print(f"\n{DIM}[3/8] credential delivery{RESET}")
    cb = Path(env.get("FARM_COOPERBENCH_DIR", "/home/user/work/CooperBench"))
    py = cb / ".venv" / "bin" / "python"
    if not py.exists():
        r.warn("cannot verify credential delivery", f"no interpreter at {py}")
        return

    sys.path.insert(0, str(REPO))
    try:
        from farm.env import child_env, shadowing_env_files
    except ImportError as exc:
        r.warn("cannot import farm.env", str(exc))
        return

    probe = (
        "import os, cooperbench.cli;"
        f"k=os.environ.get({KEY_VAR!r}, '');"
        "print('OK' if k else 'MISSING', len(k))"
    )
    out = subprocess.run([str(py), "-c", probe], cwd=str(REPO), env=child_env(),
                         capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.startswith("OK"):
        r.ok("the key reaches CooperBench's process via scripts/cooperbench",
             out.stdout.strip())
    else:
        r.fail("the key does NOT reach CooperBench",
               (out.stdout + out.stderr).strip()[:200])

    for path in shadowing_env_files(cb):
        r.warn(f"another .env exists at {path}",
               "ours wins because we inject into the child environment, but a "
               "stale key there is a leak surface -- consider removing it")


def check_key_authenticates(r: Report, env: dict[str, str]) -> None:
    """Confirm the credential is actually valid, and read the account's limit.

    Uses OpenRouter's /api/v1/key endpoint: it costs nothing, spends no tokens,
    and returns the account's usage and credit limit -- which is worth knowing
    before starting a campaign against a $50 cap, since a credit limit below the
    cap is the real ceiling.

    The key travels only in the Authorization header and is never logged.
    """
    print(f"\n{DIM}[4/8] credential validity{RESET}")
    val = env.get(KEY_VAR) or os.environ.get(KEY_VAR) or ""
    if not val:
        r.warn("skipped: no key to test")
        return
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {val}", "User-Agent": "conetic-farm-preflight"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode()).get("data", {})
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:200]
        except Exception:  # noqa: BLE001
            pass
        if exc.code in (401, 403):
            r.fail(f"{KEY_VAR} was rejected by OpenRouter (HTTP {exc.code})",
                   "the key is invalid, revoked, or lacks credit -- rotate it at "
                   "openrouter.ai/keys")
        else:
            r.warn(f"could not validate the key (HTTP {exc.code})", body)
        return
    except Exception as exc:  # noqa: BLE001
        r.warn("could not reach OpenRouter to validate the key", str(exc)[:200])
        return

    usage = data.get("usage")
    limit = data.get("limit")
    detail = f"usage=${usage}" if usage is not None else ""
    if limit is not None:
        detail += f" limit=${limit}"
    r.ok("OpenRouter accepted the key", detail or "valid")

    budget = float(env.get("FARM_BUDGET_USD", "50") or 50)
    if limit is not None:
        remaining = float(limit) - float(usage or 0)
        if remaining < budget:
            r.warn(f"OpenRouter credit remaining (${remaining:.2f}) is below the "
                   f"${budget:.2f} campaign cap",
                   "the account balance, not the cap, will stop the run")
    if data.get("is_free_tier"):
        r.warn("this is a free-tier key",
               "free-tier models are heavily rate-limited; expect timeouts")


def check_docker(r: Report, env: dict[str, str]) -> None:
    print(f"\n{DIM}[5/8] sandbox{RESET}")
    if not shutil.which("docker"):
        r.fail("docker is not on PATH")
        return
    info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                          capture_output=True, text=True)
    if info.returncode != 0:
        r.fail("docker daemon unreachable", "start it with:  dockerd >/tmp/dockerd.log 2>&1 &")
        return
    r.ok("docker daemon reachable", f"server {info.stdout.strip()}")

    tag = env.get("FARM_BASE_IMAGE", "conetic-farm/node22-base:local")
    imgs = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                          capture_output=True, text=True).stdout.split()
    if tag in imgs:
        r.ok(f"base image present: {tag}")
    else:
        r.fail(f"base image missing: {tag}", "build it with: scripts/build_base_image.sh")

    probe = subprocess.run(
        ["docker", "run", "--rm", tag, "/bin/sh", "-lc",
         "node --version && git --version >/dev/null && echo READY"],
        capture_output=True, text=True)
    if "READY" in probe.stdout:
        r.ok("containers start and carry node+git",
             probe.stdout.strip().splitlines()[0])
    elif tag in imgs:
        r.fail("base image present but a container failed to run",
               (probe.stderr or probe.stdout).strip()[:200])


def _reachable(host: str, port: int, timeout: float = 12.0) -> tuple[bool, str]:
    """Try a real connection, honouring HTTPS_PROXY when one is configured."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        if proxy:
            pu = urlparse(proxy)
            with socket.create_connection((pu.hostname, pu.port or 8080), timeout) as s:
                s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
                          .encode())
                resp = s.recv(256).decode("latin-1", "replace").splitlines()[0]
                if " 200 " in resp:
                    return True, "via proxy"
                return False, f"proxy said: {resp.strip()}"
        with socket.create_connection((host, port), timeout):
            return True, "direct"
    except OSError as exc:
        return False, str(exc)


def check_egress(r: Report) -> None:
    print(f"\n{DIM}[6/8] network egress{RESET}")
    for host, port, why in REQUIRED_EGRESS:
        ok, detail = _reachable(host, port)
        (r.ok if ok else r.fail)(f"{host}:{port} — {why}", detail)
    for host, port, why in OPTIONAL_EGRESS:
        ok, detail = _reachable(host, port)
        (r.ok if ok else r.warn)(f"{host}:{port} — {why}", detail)


def check_harness(r: Report, env: dict[str, str]) -> None:
    print(f"\n{DIM}[7/8] CooperBench harness{RESET}")
    cb = Path(env.get("FARM_COOPERBENCH_DIR", "/home/user/work/CooperBench"))
    if not cb.exists():
        r.fail(f"CooperBench checkout not found at {cb}")
        return
    r.ok(f"checkout at {cb}")
    py = cb / ".venv" / "bin" / "python"
    if not py.exists():
        r.fail(f"no venv at {py}", "create it: uv venv --python 3.12 .venv && uv pip install -e .")
        return
    probe = subprocess.run([str(py), "-c", "import cooperbench; print(cooperbench.__file__)"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        r.ok("cooperbench imports", probe.stdout.strip())
    else:
        r.fail("cooperbench does not import", probe.stderr.strip()[:200])

    gold = cb / "dataset" / "gold_conflict_report.json"
    if gold.exists():
        n = len(json.loads(gold.read_text())["all_results"])
        r.ok(f"dataset present with gold conflict labels", f"{n} feature pairs")
    else:
        r.fail(f"missing {gold}")


def check_redis(r: Report, env: dict[str, str]) -> None:
    print(f"\n{DIM}[8/8] Redis (coop-mode messaging){RESET}")
    url = env.get("FARM_REDIS_URL", "redis://127.0.0.1:6379")
    pu = urlparse(url)
    host, port = pu.hostname or "127.0.0.1", pu.port or 6379
    try:
        with socket.create_connection((host, port), 5) as s:
            s.sendall(b"PING\r\n")
            if b"PONG" in s.recv(64):
                r.ok(f"redis responds at {host}:{port}")
                return
        r.warn(f"{host}:{port} accepted a connection but did not answer PING")
    except OSError as exc:
        r.warn(f"redis unreachable at {host}:{port}",
               f"{exc}; start one with: scripts/start_redis.sh")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ENV_FILE_DEFAULT)
    args = ap.parse_args()

    print(f"{DIM}conetic-farm preflight{RESET}")
    r = Report()
    env = check_env_file(r, args.env_file)
    check_key(r, env)
    check_key_reaches_harness(r, env)
    check_key_authenticates(r, env)
    check_docker(r, env)
    check_egress(r)
    check_harness(r, env)
    check_redis(r, env)

    print()
    if r.blocking:
        print(f"{RED}NOT READY{RESET} — {len(r.blocking)} blocking issue(s):")
        for b in r.blocking:
            print(f"  - {b}")
        if r.warnings:
            print(f"{YELLOW}plus {len(r.warnings)} warning(s){RESET}")
        return 1
    if r.warnings:
        print(f"{YELLOW}READY WITH WARNINGS{RESET} — {len(r.warnings)} warning(s):")
        for w in r.warnings:
            print(f"  - {w}")
        return 0
    print(f"{GREEN}READY{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
