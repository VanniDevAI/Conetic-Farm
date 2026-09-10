"""An archive whose manifest lists files the commit does not contain is not one.

Every exported episode writes a FILES.json naming each file with its size and
sha256. That manifest is what another session reads to know it has everything.
It was, for three episodes, describing files that .gitignore had quietly eaten:
`*.diff` took every merged diff and `*.log` took every provider build log.

Nothing failed. The export printed a file count, the commit went through, the
push succeeded, and a session fetching it would have found FILES.json promising
artifacts that were not there.

So: every path in every FILES.json must be a tracked file whose bytes hash to
the recorded sha256.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "farm" / "episodes" / "artifacts"
MANIFESTS = sorted(ARTIFACTS.glob("*/FILES.json"))


def _tracked() -> set[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached",
                          "farm/episodes/artifacts"],
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


@pytest.mark.skipif(not MANIFESTS, reason="no exported episodes")
def test_every_listed_file_is_tracked_by_git():
    tracked = _tracked()
    missing = []
    for manifest in MANIFESTS:
        for entry in json.loads(manifest.read_text()):
            rel = f"farm/episodes/artifacts/{entry['path']}"
            if rel not in tracked:
                missing.append(rel)
    assert not missing, (
        "these files are named in a FILES.json and are not in the commit; "
        "check .gitignore: " + ", ".join(sorted(missing)[:10]))


@pytest.mark.skipif(not MANIFESTS, reason="no exported episodes")
def test_every_listed_file_still_hashes_to_its_recorded_sha256():
    bad = []
    for manifest in MANIFESTS:
        for entry in json.loads(manifest.read_text()):
            path = ARTIFACTS / entry["path"]
            if not path.exists():
                bad.append((entry["path"], "absent"))
                continue
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != entry["sha256"]:
                bad.append((entry["path"], "changed since it was exported"))
    assert not bad, bad


@pytest.mark.skipif(not MANIFESTS, reason="no exported episodes")
def test_the_archive_is_exempt_from_the_working_file_ignores():
    """Pinned directly, because this is the rule that was missing and the
    symptom of its absence is silence."""
    ignored = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-v",
         "farm/episodes/artifacts/probe/merge/merged.diff",
         "farm/episodes/artifacts/probe/provider_build/build.log"],
        capture_output=True, text=True).stdout
    assert "!farm/episodes/artifacts" in ignored or not ignored.strip(), ignored
