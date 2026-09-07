"""Pin the publisher's two load-bearing guarantees: no key reaches git, and
nothing is dropped from an archive without saying so."""

from __future__ import annotations

import gzip
import tarfile
from pathlib import Path

import pytest

from farm import publish


def _episode(root: Path, name: str = "demo_task__task1__f1_f2__abcd1234") -> Path:
    """A miniature episode laid out the way EpisodeRunner writes one."""
    ep = root / "episodes" / name
    for role in ("A", "B"):
        d = ep / "attempts" / "attempt-001" / "agents" / role
        d.mkdir(parents=True)
        (d / "patch.diff").write_text(f"--- a/x\n+++ b/x\n@@\n+{role}\n")
        (d / "transcript.jsonl").write_text('{"role":"assistant","content":"hi"}\n')
    res = ep / "attempts" / "attempt-001" / "results"
    res.mkdir(parents=True)
    (res / "merged_a.json").write_text('{"passed": true}\n')
    (ep / "base").mkdir(parents=True)
    (ep / "base" / "base_commit.txt").write_text("deadbeef\n")
    # The thing that must never be archived: a full clone of the upstream repo.
    (ep / "base" / "base.bundle").write_bytes(b"PACK" + b"\x00" * 4096)
    return ep


def _members(archive: Path) -> list[str]:
    with gzip.open(archive, "rb") as gz, tarfile.open(fileobj=gz, mode="r") as tf:
        return tf.getnames()


def test_archive_excludes_the_base_bundle(tmp_path: Path) -> None:
    ep = _episode(tmp_path)
    res = publish.build_archive(ep, tmp_path / "out" / "ep.tar.gz")
    names = _members(res.archive)
    assert not any(n.endswith("base.bundle") for n in names), names
    # ...while keeping what the bundle is reconstructible from, and the evidence.
    assert any(n.endswith("base_commit.txt") for n in names)
    assert any(n.endswith("agents/A/patch.diff") for n in names)
    assert any(n.endswith("agents/B/transcript.jsonl") for n in names)
    assert any(n.endswith("results/merged_a.json") for n in names)
    assert res.dropped == []


def test_a_credential_in_a_transcript_aborts_the_publish(tmp_path: Path) -> None:
    """A key in an artifact must stop the commit, not be quietly redacted.

    Redacting would hide that a credential reached a transcript at all, which is
    the thing worth knowing.
    """
    ep = _episode(tmp_path)
    leaked = ep / "attempts" / "attempt-001" / "agents" / "A" / "transcript.jsonl"
    leaked.write_text(
        '{"content":"exporting OPENROUTER_API_KEY=sk-or-v1-'
        + "a" * 40 + '"}\n')

    with pytest.raises(publish.CredentialInArtifact) as exc:
        publish.build_archive(ep, tmp_path / "out" / "ep.tar.gz")
    assert "transcript.jsonl" in str(exc.value)
    # And nothing was written that a later `git add` could sweep up.
    assert not (tmp_path / "out" / "ep.tar.gz").exists()


def test_scan_reads_undecodable_bytes_without_crashing(tmp_path: Path) -> None:
    """A truncated tool output can leave invalid UTF-8; failing to scan is not
    an acceptable outcome, so the scan decodes leniently."""
    ep = _episode(tmp_path)
    bad = ep / "attempts" / "attempt-001" / "agents" / "A" / "transcript.jsonl"
    bad.write_bytes(b'{"content":"\xff\xfe truncated ' +
                    b"sk-or-v1-" + b"b" * 40 + b'"}\n')
    assert publish.scan_for_credentials(ep)  # found despite the bad bytes


def test_oversize_drops_optional_components_and_records_them(tmp_path: Path,
                                                             monkeypatch) -> None:
    ep = _episode(tmp_path)
    for d in ("checkpoints_raw", "raw"):
        p = ep / "attempts" / "attempt-001" / d
        p.mkdir(parents=True)
        # Incompressible, so the cap is actually crossed.
        (p / "blob.txt").write_bytes(bytes(range(256)) * 2000)

    monkeypatch.setattr(publish, "MAX_ARCHIVE_BYTES", 4096)
    logged: list[str] = []
    res = publish.build_archive(ep, tmp_path / "out" / "ep.tar.gz", log=logged.append)

    assert res.dropped, "an oversize archive must drop something"
    names = _members(res.archive)
    for d in res.dropped:
        assert not any(f"/{d}/" in n for n in names)
    # The drop is announced, never silent.
    assert any("dropping" in m for m in logged)
    # The evidence a label rests on survives the drop.
    assert any(n.endswith("agents/A/patch.diff") for n in names)


def test_clean_episode_scans_clean(tmp_path: Path) -> None:
    assert publish.scan_for_credentials(_episode(tmp_path)) == []
