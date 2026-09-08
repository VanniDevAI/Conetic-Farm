#!/usr/bin/env python3
"""Give pip ownership of every apt-managed Python distribution in the base image.

Runs *inside* the image build (copied to /opt/farm-pip-own.py); it imports
nothing from this repository.

Why the layer exists: apt installs Python distributions without a pip `RECORD`,
so pip cannot uninstall them, and any task build that needs a different version
dies with `Cannot uninstall <pkg>, RECORD file not found`.  That killed both
`dspy` episodes in `c02`.  For each RECORD-less distribution we install a
pip-owned copy of the *same* version into /usr/local, which precedes
dist-packages on sys.path -- the image's behaviour is unchanged, only pip's
ability to manage it.

Why this is a program rather than a shell loop: the loop it replaces discarded
pip's output (`-q ... >/dev/null 2>&1`) and treated *every* nonzero exit as
proof that the package has no installable PyPI release, appending the name to
`pip-unmanaged.txt` and carrying on.  A transient index error during the
`PyJWT==2.7.0` iteration would therefore ship a RECORD-less PyJWT and print
`OK` -- silently recreating the exact failure the layer exists to prevent.  The
layer's own guard could not catch it either: it asserts "RECORD-less and not
declared", and taking the failure branch is what put the name in the file the
assertion excludes, so the check was empty by construction.

So: only pip's own "there is no such release" verdict may declare a package
unmanageable.  Every other failure is the build's problem and stops the build,
with pip's output on stderr.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# pip's wording for "this requirement has no installable release", which is the
# only failure that is a fact about the package rather than about this build.
NO_RELEASE_MARKERS = (
    "No matching distribution found",
    "Could not find a version that satisfies the requirement",
)

# pip's wording for "the sdist exists but cannot be built in this image".  That
# is also a fact about the package here -- PyGObject 3.48.2 has no wheel and its
# meson build cannot configure without libgirepository dev headers this rootfs
# does not carry -- but only once it reproduces.  A build-dependency download
# that times out prints the same words, which is why `main` retries before it
# believes any failure.
UNBUILDABLE_MARKERS = (
    "metadata-generation-failed",
    "did not run successfully",
    "subprocess-exited-with-error",
    "This is an issue with the package mentioned above, not pip",
)

CONSTRAINTS = "/etc/conetic-farm/apt-constraints.txt"
DECLARED = "/etc/conetic-farm/pip-unmanaged.txt"

# What tasks routinely pip-upgrade.  Any of these left RECORD-less is the c02
# failure waiting to happen, so the *build* refuses to produce such an image --
# this check used to live only in pytest, which runs after the image is already
# tagged and usable.
COMMONLY_UPGRADED = ("PyYAML", "PyJWT", "cryptography", "packaging", "six",
                     "setuptools", "pip", "wheel", "toml", "pyparsing", "oauthlib")


def classify(returncode: int, output: str) -> tuple[str, str]:
    """``ok`` / ``unavailable`` / ``unbuildable`` / ``error``, and why.

    The distinction that matters is not severity, it is *whose problem it is*.
    "No such release" and "cannot build here" are facts about the package;
    a transport error is weather, and recording weather as a fact about a
    package is what would have shipped a RECORD-less PyYAML with a green build.
    """
    if returncode == 0:
        return "ok", ""
    for line in output.splitlines():
        if any(m in line for m in NO_RELEASE_MARKERS):
            return "unavailable", line.strip()
    for line in output.splitlines():
        if any(m in line for m in UNBUILDABLE_MARKERS):
            return "unbuildable", line.strip()
    tail = "\n".join(output.strip().splitlines()[-12:])
    return "error", tail


def constraints_excluding(name: str) -> str:
    """The apt pins, minus the package being installed.

    Pinning a package at the version you are already requesting adds nothing --
    and it costs the truth: pip reports the requirement and its own constraint
    as a *conflict*, so `python-apt==2.7.7+ubuntu5.2`, which simply has no PyPI
    release, came back as `ResolutionImpossible` instead of "no matching
    distribution" and stopped the build.
    """
    src = Path(CONSTRAINTS)
    if not src.exists():
        return CONSTRAINTS
    key = name.lower().replace("_", "-")
    kept = [l for l in src.read_text().splitlines()
            if l.split("==")[0].strip().lower().replace("_", "-") != key]
    out = Path(tempfile.gettempdir()) / f"apt-constraints-not-{key}.txt"
    out.write_text("\n".join(kept) + "\n")
    return str(out)


def run_pip(spec: str) -> tuple[int, str]:
    name = spec.split("==")[0]
    p = subprocess.run(
        # --retries/--timeout because the failure this program exists to
        # classify was measured as a files.pythonhosted.org ReadTimeoutError
        # that succeeded on the very next attempt.  Classifying correctly is
        # not enough if a transient still stops the build every other run.
        ["pip3", "install", "--ignore-installed", "-c", constraints_excluding(name),
         "--break-system-packages", "--no-cache-dir",
         "--retries", "5", "--timeout", "60", spec],
        capture_output=True, text=True,
        # Build isolation runs pip again in a child process; without the trust
        # store in the environment its downloads fail on TLS, which surfaces as
        # `subprocess-exited-with-error` and would read as "this package cannot
        # be built" when the truth is "this build could not reach the index".
        env={**_env(),
             "PIP_CERT": "/etc/ssl/certs/ca-certificates.crt",
             "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
             "REQUESTS_CA_BUNDLE": "/etc/ssl/certs/ca-certificates.crt"},
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _env() -> dict:
    import os
    return dict(os.environ)


def main(specs, *, declared_path=DECLARED, run_pip=run_pip) -> int:
    declared_path = Path(declared_path)
    declared: list[str] = []
    for spec in specs:
        name = spec.split("==")[0]
        rc, output = run_pip(spec)
        verdict, reason = classify(rc, output)
        if verdict != "ok":
            # Never believe a failure the first time.  The measured case was a
            # files.pythonhosted.org ReadTimeoutError that succeeded on the very
            # next attempt; a build-dependency download that times out looks
            # exactly like a package that cannot build.  Reproducibility, not
            # wording, is what separates a fact from weather.
            rc, output = run_pip(spec)
            verdict, reason = classify(rc, output)
        if verdict == "ok":
            print(f"  pip-owned:         {spec}")
            continue
        if verdict in ("unavailable", "unbuildable"):
            declared.append(name)
            print(f"  left apt-managed:  {spec}  ({verdict}: {reason})")
            # The whole explanation, not just the line that matched.  A
            # demotion recorded without its reason is the thing that let a
            # wrong one survive in the first place.
            for line in output.strip().splitlines()[-15:]:
                print(f"      | {line}")
            continue
        print(f"FATAL: pip could not install {spec} twice, and the failure is "
              f"neither 'no such release' nor a build failure -- so it says "
              f"nothing about the package and must not be recorded as if it "
              f"did:\n{reason}", file=sys.stderr)
        return 1
    declared_path.parent.mkdir(parents=True, exist_ok=True)
    with declared_path.open("a") as fh:
        for name in declared:
            fh.write(name + "\n")
    return 0


def _record_less() -> set:
    import importlib.metadata as m
    return {n for n in {d.metadata["Name"] for d in m.distributions()}
            if m.distribution(n).read_text("RECORD") is None}


def verify(record_less=None) -> int:
    """Refuse to finish the build if a package tasks upgrade is unmanageable."""
    left = _record_less() if record_less is None else set(record_less)
    stuck = sorted(left & set(COMMONLY_UPGRADED))
    if stuck:
        print(f"FATAL: these are routinely pip-upgraded by tasks and are still "
              f"RECORD-less, so `pip install` will fail on them exactly as it "
              f"did in c02: {stuck}", file=sys.stderr)
        return 1
    print(f"  verified manageable: {', '.join(COMMONLY_UPGRADED)}")
    return 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        raise SystemExit(verify())
    raise SystemExit(main(sys.argv[1:]))
