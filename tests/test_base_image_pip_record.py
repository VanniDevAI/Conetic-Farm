"""pip must be able to replace PyYAML in the sandbox base image.

Both dspy episodes in `c02` died at image build with

    error: uninstall-no-record-file
    × Cannot uninstall PyYAML 6.0.1

The upstream task images are ``python:3.x-slim``, where every package is
pip-installed and carries a RECORD file.  Our base is the host rootfs -- Ubuntu
-- whose PyYAML comes from apt with no RECORD, so ``pip install -e ".[dev]"``
cannot upgrade it and the whole layer fails.  Same family as the ``pip install
--upgrade pip`` failure fixed in Appendix B.3, one layer deeper.

The precondition is checkable offline and precisely: does the PyYAML that
``import yaml`` resolves to carry a RECORD?  Before the fix, no; after it, the
base image ships a pip-owned copy that shadows the apt one.

Skipped when docker or the sandbox base image is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

IMAGE = "conetic-farm/node22-base:local"

PROBE = r"""
import importlib.metadata as m
d = m.distribution("PyYAML")
print("RECORD" if d.read_text("RECORD") is not None else "NO_RECORD", d.version,
      d.locate_file(""))
"""


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE],
                          capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ready(), reason="docker daemon or sandbox base image unavailable"
)


def test_pyyaml_in_the_base_image_is_pip_owned() -> None:
    out = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python3", IMAGE, "-c", PROBE],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    status, version, where = out.stdout.split(maxsplit=2)
    assert status == "RECORD", (
        f"PyYAML {version} at {where.strip()} has no RECORD file, so pip cannot "
        f"uninstall it and `pip install -e .[dev]` fails exactly as it did for dspy")


# The PyYAML fix worked and the same defect recurred one package deeper: dspy's
# `pip install -e ".[dev]"` then died on PyJWT 2.7.0.  A base image with 24
# apt-managed distributions cannot be fixed one name at a time.
COMMONLY_UPGRADED = ("PyYAML", "PyJWT", "cryptography", "packaging", "six",
                     "setuptools", "pip", "wheel", "toml", "pyparsing", "oauthlib")

GENERAL_PROBE = r"""
import importlib.metadata as m, json, pathlib
unmanaged_file = pathlib.Path("/etc/conetic-farm/pip-unmanaged.txt")
unmanaged = set(unmanaged_file.read_text().split()) if unmanaged_file.exists() else None
missing = []
for name in sorted({d.metadata["Name"] for d in m.distributions()}):
    d = m.distribution(name)                     # first-found: what pip resolves
    if d.read_text("RECORD") is None:
        missing.append(name)
print(json.dumps({"missing": missing, "unmanaged": sorted(unmanaged) if unmanaged is not None else None}))
"""


def test_pyjwt_in_the_base_image_is_pip_owned() -> None:
    probe = PROBE.replace('"PyYAML"', '"PyJWT"')
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", IMAGE, "-c", probe],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    status, version, where = out.stdout.split(maxsplit=2)
    assert status == "RECORD", (
        f"PyJWT {version} at {where.strip()} has no RECORD file; dspy's "
        f"`pip install -e .[dev]` died on exactly this after PyYAML was fixed")


def test_every_resolvable_distribution_is_pip_manageable_or_declared() -> None:
    """The general property.  Every distribution pip would resolve first must
    carry a RECORD, except those the base image explicitly declares it could
    not reinstall (Ubuntu-only packages with no PyPI release) -- and that
    declaration may never contain a package tasks commonly upgrade."""
    import json
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", IMAGE, "-c", GENERAL_PROBE],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["unmanaged"] is not None, (
        "/etc/conetic-farm/pip-unmanaged.txt is absent: the base image never "
        "recorded which apt packages it could not make pip-manageable")
    undeclared = sorted(set(data["missing"]) - set(data["unmanaged"]))
    assert not undeclared, f"RECORD-less and undeclared: {undeclared}"
    leaked = sorted(set(data["unmanaged"]) & set(COMMONLY_UPGRADED))
    assert not leaked, f"commonly-upgraded packages left apt-managed: {leaked}"


DRIFT_PROBE = r"""
import importlib.metadata as m, json
apt = {}
for d in m.distributions():
    if "/usr/lib/python3/dist-packages" in str(d.locate_file("")):
        apt[d.metadata["Name"].lower()] = d.version
drift = []
for name, av in sorted(apt.items()):
    try:
        cur = m.distribution(name)
    except Exception:
        continue
    if cur.version != av and "/usr/local/" in str(cur.locate_file("")):
        drift.append([name, av, cur.version])
print(json.dumps(drift))
"""


def test_making_packages_pip_owned_does_not_change_their_versions() -> None:
    """The substitution must be invisible to the tasks under test.

    Reinstalling with --ignore-installed but without --no-deps re-resolves each
    package's dependency closure at the newest versions, so a later iteration
    silently replaces a version an earlier one pinned.  Six packages drifted
    that way (httplib2 0.20.4 -> 0.32.0, wadllib 1.3.6 -> 2.1.0, ...) while the
    build's own record claimed apt-equivalent versions throughout.  A task whose
    behaviour depends on one of them would then differ from what the
    substitution record in every episode manifest says it got.
    """
    import json
    out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", IMAGE,
                          "-c", DRIFT_PROBE], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    drift = json.loads(out.stdout)
    assert not drift, (
        "versions changed while making packages pip-manageable: "
        + ", ".join(f"{n} {a}->{c}" for n, a, c in drift))
