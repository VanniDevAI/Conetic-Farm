"""A second read of a container may never destroy the first one's result.

Found by adversarial review of the teardown shim, and it is the same class of
bug the shim was built to fix, one layer further in.

The ordering that does it:

1. ``capture()`` writes ``<agent>.patch`` (``farm/teardown.py``) **before** it
   writes ``.done`` -- the patch comes first, the markers come in the
   ``finally``.
2. A capture that overruns ``CAPTURE_BUDGET_S`` inside ``detach_and_export``
   therefore leaves a *complete, correct* patch on disk with no ``.done``.
   ``_await_shim_capture`` reports "not captured", which is right: the capture
   did not finish.
3. ``run_agents`` falls through to reading the container live.  It is mid-stop,
   so ``git diff`` fails -- and ``patch_from_container`` returns **normally**
   with an empty diff, recording the reason in ``note`` rather than raising, so
   nothing catches it.
4. The live result was written over the file unconditionally, replacing the
   agent's work with an empty string, and the episode graded ``no_patch``.

No error was raised, nothing was logged, and the evidence was gone.  That is
exactly the ``c02`` failure mode.

Pinned here: a live read may only take the place of what is already on disk
when it actually read more than is there.  When it did not, the capture stays
and the disagreement is written down -- a disagreement that is visible can be
investigated, a silent one cannot.

The second contract in this file: an extraction that could **not** read the
container's identity is not an agent.  Keyed by the short container id it looked
like an agent literally named ``<12 hex>``, so ``_bundle_fallback`` counted the
container as claimed and refused to attribute a bundle that belonged to exactly
one missing agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from farm import episode as ep
from farm import patchgen

GOOD = "diff --git a/core.py b/core.py\n--- a/core.py\n+++ b/core.py\n@@ -1 +1 @@\n-a\n+b\n"


def _stub(monkeypatch, ex: patchgen.ExtractedPatch) -> None:
    monkeypatch.setattr(patchgen, "patch_from_container",
                        lambda cid, base, **kw: ex)


def test_an_empty_live_read_must_not_replace_a_capture_already_on_disk(
        monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "agent1.patch").write_text(GOOD)          # the shim got there first
    _stub(monkeypatch, patchgen.ExtractedPatch(
        agent_id="agent1", text="", source="container",
        note="diff failed: container is not running"))
    extracted: dict = {}

    ep._live_extract(tmp_path, "abc123456789cafe", "", extracted)

    assert (tmp_path / "agent1.patch").read_text() == GOOD, (
        "the live read overwrote the shim's capture with nothing: the agent's "
        "work is gone and no error was raised")


def test_the_discarded_live_read_is_written_down_rather_than_dropped(
        monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "agent1.patch").write_text(GOOD)
    _stub(monkeypatch, patchgen.ExtractedPatch(
        agent_id="agent1", text="", note="diff failed: container is not running"))
    extracted: dict = {}

    ep._live_extract(tmp_path, "abc123456789cafe", "", extracted)

    assert (tmp_path / "agent1.live.patch").exists(), (
        "the live attempt vanished; a disagreement that leaves no trace cannot "
        "be investigated")
    assert "agent1" in extracted
    blob = json.dumps(extracted["agent1"])
    assert "diff failed" in blob, blob


def test_a_live_read_that_found_more_does_replace_an_empty_file(
        monkeypatch, tmp_path: Path) -> None:
    """The rule is 'do not destroy evidence', not 'never write'.  A shim that
    captured nothing must not block a live read that captured something."""
    (tmp_path / "agent1.patch").write_text("")
    _stub(monkeypatch, patchgen.ExtractedPatch(
        agent_id="agent1", text=GOOD, files_changed=1, source="container"))
    extracted: dict = {}

    ep._live_extract(tmp_path, "abc123456789cafe", "", extracted)

    assert (tmp_path / "agent1.patch").read_text() == GOOD
    assert extracted["agent1"]["files_changed"] == 1


def test_the_ordinary_case_still_writes_the_patch(monkeypatch, tmp_path: Path) -> None:
    _stub(monkeypatch, patchgen.ExtractedPatch(
        agent_id="agent2", text=GOOD, files_changed=1, source="container"))
    extracted: dict = {}

    ep._live_extract(tmp_path, "beef123456789abc", "", extracted)

    assert (tmp_path / "agent2.patch").read_text() == GOOD
    assert extracted["agent2"]["captured_by"] == "post_return"


def test_an_unidentified_extraction_is_not_an_agent(monkeypatch, tmp_path: Path) -> None:
    """`git config user.name` was unreadable.  Recording that under the short
    container id invents an agent of that name."""
    _stub(monkeypatch, patchgen.ExtractedPatch(agent_id="", text=GOOD, files_changed=1))
    extracted: dict = {}

    ep._live_extract(tmp_path, "abc123456789cafe", "", extracted)

    assert "abc123456789" not in extracted, (
        "an extraction with no identity was recorded as an agent named after "
        "the container")
    assert any(k.startswith(ep.UNKNOWN_PREFIX) for k in extracted), extracted


def test_an_unattributed_container_does_not_block_bundle_elimination(tmp_path: Path) -> None:
    """The consequence of the previous test, at the place it bites.

    Agent B's container never got `git config user.name` set, so its extraction
    has no identity -- but the shim did export its checkpoint bundle.  Agent A
    is accounted for.  One bundle is left over and exactly one agent is missing
    a patch, so elimination can attribute it.

    With B's container recorded as an agent literally named `<12 hex>`,
    `claimed` said someone already owned that container, `unclaimed` came out
    empty, and the branch never fired: B was graded `no_patch` while its work
    sat in a bundle on disk.
    """
    raw = tmp_path / "checkpoints_raw" / "bbbbbbbbbbbb"
    raw.mkdir(parents=True)
    (raw / "checkpoints.bundle").write_bytes(b"not a real bundle")

    extracted = {
        "agent1": {"container": "aaaaaaaaaaaa", "files_changed": 1, "empty": False},
        f"{ep.UNKNOWN_PREFIX}bbbbbbbbbbbb":
            {"container": "bbbbbbbbbbbb", "files_changed": 0, "empty": True},
    }
    calls: list = []

    real = patchgen.patch_from_bundle
    patchgen.patch_from_bundle = lambda path, agent_id="": (   # noqa: E731
        calls.append((str(path), agent_id))
        or patchgen.ExtractedPatch(agent_id=agent_id, text=GOOD, files_changed=1))
    try:
        got = ep.EpisodeRunner._bundle_fallback(tmp_path, extracted, "agent2")
    finally:
        patchgen.patch_from_bundle = real

    assert got is not None and not got.is_empty, (
        "the only bundle left, and the only agent left, were not matched")
    assert calls and calls[0][1] == "agent2"
