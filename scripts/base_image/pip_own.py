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
from pathlib import Path

# pip's wording for "this requirement has no installable release", which is the
# only failure that is a fact about the package rather than about this build.
NO_RELEASE_MARKERS = (
    "No matching distribution found",
    "Could not find a version that satisfies the requirement",
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
    """``ok`` / ``unavailable`` / ``error``, with the line that decided it."""
    if returncode == 0:
        return "ok", ""
    for line in output.splitlines():
        if any(m in line for m in NO_RELEASE_MARKERS):
            return "unavailable", line.strip()
    tail = "\n".join(output.strip().splitlines()[-12:])
    return "error", tail


def run_pip(spec: str) -> tuple[int, str]:
    p = subprocess.run(
        # --retries/--timeout because the failure this program exists to
        # classify was measured as a files.pythonhosted.org ReadTimeoutError
        # that succeeded on the very next attempt.  Classifying correctly is
        # not enough if a transient still stops the build every other run.
        ["pip3", "install", "--ignore-installed", "-c", CONSTRAINTS,
         "--break-system-packages", "--no-cache-dir",
         "--retries", "5", "--timeout", "60", spec],
        capture_output=True, text=True,
        env={**_env(), "PIP_CERT": "/etc/ssl/certs/ca-certificates.crt"},
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
        if verdict == "ok":
            print(f"  pip-owned:         {spec}")
            continue
        if verdict == "unavailable":
            declared.append(name)
            print(f"  left apt-managed:  {spec}  ({reason})")
            continue
        print(f"FATAL: pip could not install {spec}, and the failure is not "
              f"'no such release' -- so it says nothing about the package and "
              f"must not be recorded as if it did:\n{reason}", file=sys.stderr)
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
