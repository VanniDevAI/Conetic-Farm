"""A pip failure the build cannot explain must stop the build, not be recorded
as a fact about the package.

The RECORD-substitution layer walks every apt-managed distribution and installs
a pip-owned copy at the same version.  When that install failed, the old shell
loop appended the name to ``pip-unmanaged.txt`` and carried on -- with pip's
output already discarded by ``-q ... >/dev/null 2>&1``, so *why* it failed was
unknowable.

Two consequences, and the second is the one that matters:

* ``pip-unmanaged.txt`` is a claim about the world ("no installable PyPI
  release at this version").  A transient index error, a proxy hiccup, or a
  build-dependency gap produced exactly the same entry, and the claim was then
  false.
* the layer's own assertion -- *RECORD-less and not declared* -- can never fire
  for anything that loop demoted, because taking the failure branch is what put
  the name in the file the assertion excludes.  The check that was supposed to
  catch this is empty by construction.

So a `PyJWT==2.7.0` install losing its connection for one second would silently
reproduce the exact `c02` failure this layer exists to prevent -- `Cannot
uninstall PyJWT 2.7.0, RECORD file not found` -- while the build printed OK.

Pinned here: only pip's own "there is no such release" verdict may declare a
package unmanageable.  Every other failure is the build's problem and stops it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "scripts" / "base_image" / "pip_own.py"


def _load():
    spec = importlib.util.spec_from_file_location("pip_own", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NO_RELEASE = (
    "ERROR: Could not find a version that satisfies the requirement "
    "python-apt==2.4.0 (from versions: none)\n"
    "ERROR: No matching distribution found for python-apt==2.4.0\n")

TRANSIENT = (
    "WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None,"
    " status=None)) after connection broken by 'NewConnectionError'\n"
    "ERROR: Could not install packages due to an OSError: "
    "HTTPSConnectionPool(host='pypi.org', port=443): Max retries exceeded\n")

BUILD_FAILURE = (
    "error: subprocess-exited-with-error\n"
    "  × Building wheel for PyGObject did not run successfully.\n"
    "  note: This error originates from a subprocess.\n")


def test_success_is_success() -> None:
    assert _load().classify(0, "Successfully installed six-1.16.0")[0] == "ok"


def test_only_a_missing_release_may_declare_a_package_unmanageable() -> None:
    mod = _load()
    verdict, reason = mod.classify(1, NO_RELEASE)
    assert verdict == "unavailable"
    # The reason must be a line pip actually printed, quoted verbatim, and it
    # must be one of pip's "there is no such release" lines -- not a summary we
    # wrote.  Which of the two lines is quoted is pip's business, not ours.
    assert reason in [l.strip() for l in NO_RELEASE.splitlines()], reason
    assert any(m in reason for m in mod.NO_RELEASE_MARKERS), reason


def test_a_transient_network_failure_is_not_a_fact_about_the_package() -> None:
    """The scenario that would silently reproduce c02: one bad second during
    the PyJWT iteration, and the image ships a RECORD-less PyJWT."""
    verdict, reason = _load().classify(1, TRANSIENT)
    assert verdict == "error", (
        "a network error was accepted as proof that the package has no PyPI "
        "release; it would be declared apt-managed and the build would pass")
    assert "Max retries exceeded" in reason


def test_a_build_failure_is_not_a_fact_about_the_package_either() -> None:
    assert _load().classify(1, BUILD_FAILURE)[0] == "error"


def test_an_unexplained_failure_stops_the_build(tmp_path: Path, monkeypatch) -> None:
    """End to end through main(): an 'error' verdict must be fatal, and must
    print what pip actually said rather than swallowing it."""
    mod = _load()
    declared = tmp_path / "pip-unmanaged.txt"
    calls: list[str] = []

    def fake_pip(spec: str):
        calls.append(spec)
        return (1, TRANSIENT)

    rc = mod.main(["PyJWT==2.7.0"], declared_path=declared, run_pip=fake_pip)

    assert rc != 0, "the build continued after a failure it could not explain"
    assert not declared.exists() or "PyJWT" not in declared.read_text(), (
        "PyJWT was declared apt-managed on the strength of a network error")


def test_a_genuinely_unavailable_package_is_declared_and_the_build_continues(
        tmp_path: Path) -> None:
    mod = _load()
    declared = tmp_path / "pip-unmanaged.txt"

    def fake_pip(spec: str):
        return (0, "ok") if spec.startswith("six") else (1, NO_RELEASE)

    rc = mod.main(["python-apt==2.4.0", "six==1.16.0"],
                  declared_path=declared, run_pip=fake_pip)

    assert rc == 0
    assert declared.read_text().split() == ["python-apt"]


def test_every_decision_is_printed(tmp_path: Path, capsys) -> None:
    """`-q ... >/dev/null 2>&1` is how the old loop made its own demotions
    invisible.  Each decision must be legible in the build log."""
    mod = _load()
    mod.main(["python-apt==2.4.0", "six==1.16.0"],
             declared_path=tmp_path / "u.txt",
             run_pip=lambda s: (0, "ok") if s.startswith("six") else (1, NO_RELEASE))
    out = capsys.readouterr().out
    assert "python-apt" in out and "six" in out
    assert any(m in out for m in mod.NO_RELEASE_MARKERS), (
        f"the reason a package was declared unmanageable is not in the log:\n{out}")
