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
import pathlib
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


def test_a_reproducible_build_failure_IS_a_fact_about_the_package() -> None:
    """Corrected against the real image, not assumed.

    The first version of this file asserted that a build failure, like a
    network failure, says nothing about the package.  The rebuild disproved it:
    `PyGObject==3.48.2` has no wheel, and its meson sdist cannot configure
    without libgirepository dev headers that are not in this rootfs.  pip's
    verdict there -- `metadata-generation-failed`, "This is an issue with the
    package mentioned above, not pip" -- is a true, reproducible statement that
    pip cannot install it *here*, and treating it as the build's problem makes
    the base image unbuildable over a package no task touches.

    What separates this from the transient case is not the wording, it is
    reproducibility: `main()` retries before it believes any failure.  And
    nothing that matters can be declared regardless, because `verify()` fails
    the build if a commonly-upgraded package ends up in the declared set.
    """
    assert _load().classify(1, BUILD_FAILURE)[0] == "unbuildable"


def test_a_transient_that_looks_like_a_build_failure_is_caught_by_the_retry(
        tmp_path: Path) -> None:
    """A build-dependency download that times out also surfaces as
    `subprocess-exited-with-error`.  Wording cannot tell the two apart; a second
    attempt can."""
    mod = _load()
    attempts: list[str] = []

    def flaky(spec: str):
        attempts.append(spec)
        return (1, BUILD_FAILURE) if len(attempts) == 1 else (0, "Successfully installed")

    declared = tmp_path / "u.txt"
    rc = mod.main(["PyGObject==3.48.2"], declared_path=declared, run_pip=flaky)

    assert rc == 0
    assert len(attempts) == 2, "a failure was believed on the first attempt"
    assert not declared.exists() or "PyGObject" not in declared.read_text(), (
        "a package that installs fine on retry was declared unmanageable")


def test_a_reproducible_build_failure_is_declared_after_the_retry(tmp_path: Path) -> None:
    mod = _load()
    n = []
    declared = tmp_path / "u.txt"
    rc = mod.main(["PyGObject==3.48.2"], declared_path=declared,
                  run_pip=lambda s: (n.append(s), (1, BUILD_FAILURE))[1])
    assert rc == 0
    assert len(n) == 2
    assert declared.read_text().split() == ["PyGObject"]


def test_an_unexplained_failure_stops_the_build(tmp_path: Path) -> None:
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
    assert len(calls) == 2, "a transient was believed without a second attempt"
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


# --- the packages tasks actually upgrade ------------------------------------
#
# The layer's own assertion asked "is every RECORD-less package *declared*",
# which the declaration itself satisfies.  It never asked the question that
# matters: is anything a task will try to upgrade still unmanageable?  That
# check existed only in pytest, after the build -- so a bad image could be
# produced, tagged, and used, and only a separate test run would notice.
# It belongs in the build.


def test_verify_fails_when_a_commonly_upgraded_package_is_unmanageable() -> None:
    mod = _load()
    rc = mod.verify(record_less={"PyYAML", "python-apt"})
    assert rc != 0, (
        "the build would have shipped an image whose PyYAML pip cannot replace "
        "-- the exact c02 failure")


def test_verify_passes_when_only_ubuntu_only_packages_are_unmanageable() -> None:
    mod = _load()
    assert mod.verify(record_less={"python-apt", "PyGObject", "dbus-python"}) == 0


def test_verify_names_what_is_wrong(capsys) -> None:
    mod = _load()
    mod.verify(record_less={"cryptography"})
    err = capsys.readouterr().err
    assert "cryptography" in err, err


def test_pip_is_given_retries_and_a_timeout(monkeypatch) -> None:
    """The measured failure was a `ReadTimeoutError` from files.pythonhosted.org
    that succeeded on the very next attempt.  A one-shot install turns network
    weather into a permanent, false claim about a package."""
    mod = _load()
    seen: list = []

    class P:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(mod.subprocess, "run",
                        lambda argv, **kw: (seen.append(argv), P())[1])
    mod.run_pip("six==1.16.0")
    argv = seen[0]
    assert "--retries" in argv and "--timeout" in argv, argv


RESOLUTION_IMPOSSIBLE = (
    "    The user requested python-apt==2.7.7+ubuntu5.2\n"
    "    The user requested (constraint) python-apt==2.7.7+ubuntu5.2\n"
    "ERROR: Cannot install python-apt==2.7.7+ubuntu5.2 because these package "
    "versions have conflicting dependencies.\n"
    "ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/\n")


def test_a_package_is_not_constrained_against_itself(monkeypatch, tmp_path: Path) -> None:
    """Measured in the rebuild: `python-apt==2.7.7+ubuntu5.2` has no PyPI
    release at all, but because the constraints file pinned it to the same
    version being requested, pip reported `ResolutionImpossible` -- a conflict
    between the requirement and its own constraint -- instead of "no matching
    distribution".  The build then stopped on a package that is genuinely and
    permanently apt-only.

    Pinning a package you are installing at the version you are installing adds
    nothing; the spec already says it.  So the constraints handed to pip must
    exclude the package itself, and pip's verdict is then about the package.
    """
    mod = _load()
    seen: dict = {}

    class P:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(mod, "CONSTRAINTS", str(tmp_path / "apt.txt"))
    (tmp_path / "apt.txt").write_text("six==1.16.0\npython-apt==2.7.7+ubuntu5.2\n")
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda argv, **kw: (seen.setdefault("argv", argv), P())[1])

    mod.run_pip("python-apt==2.7.7+ubuntu5.2")

    argv = seen["argv"]
    used = pathlib.Path(argv[argv.index("-c") + 1]).read_text()
    assert "python-apt" not in used, (
        f"the package was constrained against itself; pip reports a resolution "
        f"conflict instead of the truth about the package:\n{used}")
    assert "six==1.16.0" in used, "the other pins must still hold"


def test_a_declaration_records_pips_whole_explanation(tmp_path: Path, capsys) -> None:
    """One matched line is not enough to audit a demotion by.  The reason a
    package was left apt-managed has to be readable in the build log."""
    mod = _load()
    mod.main(["PyGObject==3.48.2"], declared_path=tmp_path / "u.txt",
             run_pip=lambda s: (1, BUILD_FAILURE))
    out = capsys.readouterr().out
    assert "Building wheel for PyGObject did not run successfully" in out, out
