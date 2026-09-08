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
