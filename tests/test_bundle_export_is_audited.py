"""A bundle that never reached the host must not audit as a bundle we have.

`detach_and_export` runs `git bundle create` *inside* the container and records
that in ``bundle_created``; whether the file then reached the host is a
*separate* key, ``checkpoints.bundle``, set by the `docker cp` that follows.  A
container removed between the two -- exactly what the double-cleanup race did --
produces:

    {"bundle_created": True, "checkpoints.bundle": False, "checkpoints": 2, ...}

and no ``checkpoints.bundle`` on disk.

`audit_extraction`'s ``no_bundle`` rule read only ``bundle_created``, so that
episode printed ``clean``.  That matters more than the bundle does: the audit is
the before/after proof for the whole teardown fix.  Read this way, `c03` could
lose the fallback record for every container and still print
``PASS: every agent that worked has its work recorded`` -- a green instrument
reading on an instrument that had failed.

Downstream is equally blind: `checkpoint_bundles` lists only directories that
actually contain the file, so `_bundle_fallback` finds nothing and the agent is
recorded ``patch_source: "none"``.

Pinned here: one derived key, ``exported``, that means "we have the bundle on
the host", and an audit that reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

from farm import checkpoints

import importlib.util
REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "audit_extraction", REPO / "scripts" / "audit_extraction.py")
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def _run_info(**ck) -> dict:
    return {"checkpoints": {"abc123456789cafe": ck}}


COMPLETED = {"attempts": [{"status": "completed", "attempt_id": "attempt-001",
                           "agents": []}]}


def test_a_bundle_that_never_reached_the_host_is_a_finding() -> None:
    found = audit.audit_episode(
        COMPLETED,
        {"attempt-001": _run_info(**{"bundle_created": True,
                                     "checkpoints.bundle": False,
                                     "index.jsonl": True, "checkpoints": 2})})
    kinds = {k for k, _ in found}
    assert "no_bundle" in kinds, (
        "an export cut off mid-`docker cp` audited as clean; the proof for the "
        "whole teardown fix would read PASS on a failed instrument")


def test_a_bundle_that_did_reach_the_host_is_not_a_finding() -> None:
    found = audit.audit_episode(
        COMPLETED,
        {"attempt-001": _run_info(**{"bundle_created": True,
                                     "checkpoints.bundle": True,
                                     "index.jsonl": True, "checkpoints": 2})})
    assert [k for k, _ in found] == [], found


def test_a_bundle_git_never_created_is_still_a_finding() -> None:
    found = audit.audit_episode(
        COMPLETED,
        {"attempt-001": _run_info(**{"bundle_created": False,
                                     "checkpoints.bundle": False,
                                     "checkpoints": 2})})
    assert "no_bundle" in {k for k, _ in found}


def test_detach_and_export_derives_a_single_exported_verdict(monkeypatch, tmp_path: Path) -> None:
    """`bundle_created` alone is not "we have it".  One key answers that."""
    class R:
        def __init__(self, rc=0): self.returncode, self.stdout = rc, ""

    calls: list[tuple] = []

    def fake_docker(*argv, **kw):
        calls.append(argv)
        if argv[0] == "exec" and "pgrep" in argv:
            return R(1)                        # snapshotter already gone
        if argv[0] == "cp" and str(argv[2]).endswith("checkpoints.bundle"):
            return R(1)                        # the container died before cp
        return R(0)

    monkeypatch.setattr(checkpoints, "_docker", fake_docker)
    att = checkpoints.Attachment(container_id="abc123456789cafe",
                                 work_tree="/workspace/repo")
    out = checkpoints.detach_and_export(att, tmp_path, timeout_s=1)

    assert out["bundle_created"] is True
    assert out["checkpoints.bundle"] is False
    assert out["exported"] is False, (
        "`exported` must mean the bundle is on the host, not that git made one "
        f"inside a container we no longer have: {json.dumps(out, default=str)}")


def test_exported_is_true_only_when_both_halves_succeeded(monkeypatch, tmp_path: Path) -> None:
    class R:
        def __init__(self, rc=0): self.returncode, self.stdout = rc, ""

    def fake_docker(*argv, **kw):
        if argv[0] == "exec" and "pgrep" in argv:
            return R(1)
        if argv[0] == "cp":
            dest = Path(argv[2])
            dest.write_text("")               # both files land
            return R(0)
        return R(0)

    monkeypatch.setattr(checkpoints, "_docker", fake_docker)
    att = checkpoints.Attachment(container_id="abc123456789cafe",
                                 work_tree="/workspace/repo")
    out = checkpoints.detach_and_export(att, tmp_path, timeout_s=1)
    assert out["exported"] is True, out
