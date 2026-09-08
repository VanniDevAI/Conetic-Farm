"""A task image build must not be lost to one slow packet.

Measured in `c03`, episode 5.  The `dottxt_ai_outlines/1655` image build died
with:

    Caused by: error decoding response body for url
      (https://files.pythonhosted.org/.../pytest_xdist-3.8.0-py3-none-any.whl.metadata)
    Caused by: operation timed out
    ERROR: process "uv pip install --system pytest pytest-xdist pytest_mock"
      did not complete successfully: exit code: 2

and the episode was recorded as a harness error.  It is not one -- that image
builds fine, and did in `c02`.  This is the same fault the base-image work was
about, in a different place: a transient recorded as a permanent fact, landing
in the denominator the report divides by.

Two independent defences, because either alone leaves a gap:

* give `uv` and `pip` a longer HTTP timeout and real retries inside the image,
  so an ordinary slow response is not fatal in the first place.  `uv`'s default
  is 30s, and pypi metadata fetches behind an intercepting gateway exceed it;
* retry the whole build once, because a transient can land anywhere in a
  Dockerfile, including steps whose retry policy we do not control.

Neither hides a real failure: a build that is genuinely broken fails twice, and
the second failure is what gets reported.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REWRITER = (REPO / "scripts" / "build_task_image.sh").read_text()


def test_uv_gets_a_timeout_longer_than_its_thirty_second_default() -> None:
    m = re.search(r"UV_HTTP_TIMEOUT=(\d+)", REWRITER)
    assert m, "uv's default 30s timeout is what lost c03 episode 5"
    assert int(m.group(1)) >= 120, m.group(0)


def test_pip_gets_retries_and_a_timeout_too() -> None:
    """Some task Dockerfiles use pip rather than uv; the same slow index
    affects both."""
    assert "PIP_RETRIES=" in REWRITER
    assert "PIP_TIMEOUT=" in REWRITER


def test_the_injected_env_is_still_one_ENV_per_group() -> None:
    """A malformed ENV line breaks every task image at once, so the shape is
    worth pinning."""
    for var in ("UV_NATIVE_TLS=1", "UV_HTTP_TIMEOUT="):
        assert var in REWRITER


# --- retrying the build itself ---------------------------------------------

from farm.episode import EpisodeRunner


def test_ensure_image_retries_a_failed_build_once(monkeypatch, tmp_path: Path) -> None:
    calls: list = []

    class R:
        def __init__(self, rc): self.returncode, self.stdout, self.stderr = rc, "", "boom"

    runner = EpisodeRunner.__new__(EpisodeRunner)
    runner.image = "img:local"
    runner.cb = tmp_path
    runner.log = lambda *a, **k: None

    class Spec:
        repo, task_id = "dottxt_ai_outlines_task", 1655
    runner.spec = Spec()

    import farm.episode as m
    monkeypatch.setattr(m.subprocess, "run",
                        lambda argv, **kw: (calls.append(argv), R(1))[1])
    # exists() False throughout: the build never succeeds
    monkeypatch.setattr(m.sandbox, "image_exists", lambda img: False)

    try:
        runner.ensure_image()
    except m.sandbox.SandboxError:
        pass
    else:
        raise AssertionError("a build that never succeeds must still raise")

    assert len(calls) == 2, (
        f"the build was attempted {len(calls)} time(s); one transient PyPI "
        f"timeout should not cost an episode")


def test_a_build_that_succeeds_on_the_retry_is_not_an_error(monkeypatch, tmp_path: Path) -> None:
    import farm.episode as m
    attempts = {"n": 0}

    class R:
        def __init__(self, rc): self.returncode, self.stdout, self.stderr = rc, "", ""

    runner = EpisodeRunner.__new__(EpisodeRunner)
    runner.image = "img:local"
    runner.cb = tmp_path
    runner.log = lambda *a, **k: None

    class Spec:
        repo, task_id = "dottxt_ai_outlines_task", 1655
    runner.spec = Spec()

    def fake_run(argv, **kw):
        attempts["n"] += 1
        return R(1 if attempts["n"] == 1 else 0)

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    monkeypatch.setattr(m.sandbox, "image_exists", lambda img: attempts["n"] >= 2)
    runner.ensure_image()                     # must not raise
    assert attempts["n"] == 2


def test_an_image_that_already_exists_is_not_rebuilt(monkeypatch, tmp_path: Path) -> None:
    import farm.episode as m
    runner = EpisodeRunner.__new__(EpisodeRunner)
    runner.image = "img:local"
    runner.log = lambda *a, **k: None
    monkeypatch.setattr(m.sandbox, "image_exists", lambda img: True)
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rebuilt")))
    runner.ensure_image()
