"""Load credentials from this repository's .env and inject them into children.

There is a trap here worth stating plainly, because it fails **silently**.

``cooperbench/cli.py:16`` calls ``dotenv.load_dotenv()`` under the comment
*"load ./.env from cwd"*.  That comment is wrong.  ``python-dotenv``'s
``find_dotenv()`` defaults to ``usecwd=False`` and walks up from the **calling
module's file**, not from the working directory (``dotenv/main.py:361-375``).
Under an editable install that module is
``/home/user/work/CooperBench/src/cooperbench/cli.py``, so the walk lands on
``/home/user/work/CooperBench/.env``.

Verified experimentally:

    .env location                     cwd            key seen by cooperbench
    --------------------------------  -------------  -----------------------
    Conetic-Farm/.env only            anywhere       None      <- ignored
    CooperBench/.env only             Conetic-Farm   loaded
    both                              Conetic-Farm   CooperBench/.env wins

So a `.env` placed in *this* repository is never read by the harness, and the
failure looks like an authentication error rather than a misplaced file.

The fix does not depend on that behaviour at all.  ``load_dotenv`` defaults to
``override=False`` (``dotenv/main.py:392``), so **a variable already present in
the environment wins over anything the harness later finds**.  We therefore read
our own ``.env`` and export it into the child process ourselves.  The credential
stays in this repository, git-ignored, under our control — and CooperBench's
lookup becomes irrelevant rather than merely redundant.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"

# Names whose values must never be logged, echoed, or serialised.
SECRET_PATTERN = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

# Values shaped like a live credential, used to scrub anything we write out.
KEY_SHAPE = re.compile(r"\b(sk-or-v1-[A-Za-z0-9_\-]{16,}|sk-ant-[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9]{32,})\b")


class EnvError(RuntimeError):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file.  Values are returned but must never be logged."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load(path: Path | None = None, *, override: bool = False) -> list[str]:
    """Load this repo's .env into ``os.environ``.  Returns the names set.

    Names only — a caller that logs the return value cannot leak a value.
    """
    env = parse_env_file(path or ENV_FILE)
    applied: list[str] = []
    for k, v in env.items():
        if not v:
            continue
        if k in os.environ and not override:
            continue
        os.environ[k] = v
        applied.append(k)
    return applied


def child_env(
    extra: dict[str, str] | None = None, *, path: Path | None = None
) -> dict[str, str]:
    """Build the environment for a CooperBench subprocess.

    Our values are placed directly in the child's environment, so the harness's
    own ``load_dotenv`` (``override=False``) cannot displace them regardless of
    which ``.env`` its frame-walk happens to find.
    """
    env = dict(os.environ)
    env.update({k: v for k, v in parse_env_file(path or ENV_FILE).items() if v})
    env.update(extra or {})
    return env


def require(*names: str, path: Path | None = None) -> None:
    """Raise if any required credential is absent.  Never names a value."""
    env = parse_env_file(path or ENV_FILE)
    missing = [n for n in names if not (env.get(n) or os.environ.get(n))]
    if missing:
        raise EnvError(
            f"missing required environment variable(s): {', '.join(missing)}; "
            f"set them in {path or ENV_FILE}"
        )


def redact(text: str) -> str:
    """Strip anything credential-shaped before writing to disk or a log."""
    return KEY_SHAPE.sub("<redacted>", text)


def shadowing_env_files(cooperbench_dir: Path) -> list[Path]:
    """Other .env files the harness could pick up.

    Ours wins because we export into the child environment, but a stale key in
    one of these is a real leak surface and worth reporting.
    """
    try:
        from platformdirs import user_config_dir

        mswea_config_dir = user_config_dir("mini-swe-agent")
    except ImportError:
        # platformdirs is a harness dependency, so it lives in CooperBench's
        # venv -- not necessarily in whatever interpreter runs preflight.  This
        # check only ever emits a warning, so fall back to the path
        # platformdirs would return on Linux rather than failing the whole gate
        # over a missing convenience dependency.
        mswea_config_dir = str(
            Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / "mini-swe-agent"
        )

    candidates = [
        Path(cooperbench_dir) / ".env",
        Path(os.getenv("MSWEA_GLOBAL_CONFIG_DIR") or mswea_config_dir) / ".env",
    ]
    return [p for p in candidates if p.exists()]
