"""The report's eligibility and conflict accounting.

Appendix B.2 warned that diffing the whole working tree lets two agents
create same-named scratch files and manufacture a merge conflict that has
nothing to do with either feature.  The report must therefore say, for every
conflict, whether the conflicted path is a file that existed at the task base
(real source) or one an agent created (scratch) -- exactly, from the corpus,
not from a filename pattern.

The definition pinned here: a path is scratch if either agent's patch
introduces it as a NEW file (``--- /dev/null`` then ``+++ b/<path>``);
otherwise the patch modifies a file that was already there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import report  # noqa: E402  (scripts/report.py)


NEW_FILE_PATCH = """\
diff --git a/test_debug.py b/test_debug.py
new file mode 100644
--- /dev/null
+++ b/test_debug.py
@@ -0,0 +1,2 @@
+def test_x():
+    assert True
diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1,2 +1,3 @@
 def a():
+    pass
     return 1
"""

MODIFY_ONLY_PATCH = """\
diff --git a/src/core.py b/src/core.py
--- a/src/core.py
+++ b/src/core.py
@@ -1,2 +1,3 @@
 def a():
+    x = 1
     return 1
"""


def test_new_files_are_detected_from_the_diff_header() -> None:
    assert report._new_files_in_patch(NEW_FILE_PATCH) == {"test_debug.py"}
    assert report._new_files_in_patch(MODIFY_ONLY_PATCH) == set()
    assert report._new_files_in_patch("") == set()


def _data_root(tmp_path: Path, conflicted: list[str], patches: tuple[str, str],
               label: str = "a_broken") -> Path:
    root = tmp_path / "data"
    ep = root / "episodes" / "demo__task1__f1_f2__abcd1234"
    att = ep / "attempts" / "attempt-001"
    for role, text in zip(("A", "B"), patches):
        d = att / "agents" / role
        d.mkdir(parents=True)
        (d / "patch.diff").write_text(text)
    manifest = {
        "episode_id": ep.name, "campaign": "t", "repo": "demo", "task_id": 1,
        "stratum": "conflicting", "language": "python",
        "attempts": [{
            "attempt_id": "attempt-001", "status": "completed", "disposition": "counted",
            "agents": [
                {"role": "A", "exit_status": "Submitted",
                 "patch": {"bytes": len(patches[0]), "path": str(att / "agents/A/patch.diff")}},
                {"role": "B", "exit_status": "LimitsExceeded",
                 "patch": {"bytes": len(patches[1]), "path": str(att / "agents/B/patch.diff")}},
            ],
            "classification": {"label": label, "evidence": {
                "merge": {"outcome": "conflict" if conflicted else "clean",
                          "conflicted_paths": conflicted}}},
        }],
    }
    (ep / "manifest.json").write_text(json.dumps(manifest))
    (root / "manifest.json").write_text(json.dumps({"episodes": [{
        "episode_id": ep.name, "campaign": "t", "repo": "demo", "task_id": 1,
        "stratum": "conflicting", "language": "python",
        "manifest_path": str(ep / "manifest.json"), "episode_dir": str(ep),
        "attempts": [{"attempt_id": "attempt-001", "status": "completed",
                      "disposition": "counted", "label": label, "cost_usd": 1.5}],
    }]}))
    (root / "ledger.jsonl").write_text(json.dumps({
        "kind": "settle", "amount_usd": 1.5, "episode_id": ep.name, "ts": "t",
        "source": "provider_delta"}) + "\n")
    return root


def test_conflicts_are_split_into_source_and_scratch(tmp_path: Path) -> None:
    root = _data_root(tmp_path, ["src/core.py", "test_debug.py"],
                      (NEW_FILE_PATCH, MODIFY_ONLY_PATCH))
    episodes, _ = report.load(root, "t")
    ev = report.merge_evidence(episodes[0])
    assert ev["outcome"] == "conflict"
    assert ev["source"] == ["src/core.py"]
    assert ev["scratch"] == ["test_debug.py"]


def test_a_conflict_only_on_scratch_files_is_flagged_as_such(tmp_path: Path) -> None:
    root = _data_root(tmp_path, ["test_debug.py"], (NEW_FILE_PATCH, NEW_FILE_PATCH))
    episodes, _ = report.load(root, "t")
    ev = report.merge_evidence(episodes[0])
    assert ev["source"] == [] and ev["scratch"] == ["test_debug.py"]
    assert ev["scratch_only"] is True


def test_cost_per_eligible_episode_uses_settled_spend(tmp_path: Path) -> None:
    root = _data_root(tmp_path, [], (MODIFY_ONLY_PATCH, MODIFY_ONLY_PATCH))
    episodes, ledger = report.load(root, "t")
    eligible = [e for e in episodes if report.both_patches_present(e)]
    assert len(eligible) == 1
    assert report.cost_per_eligible(ledger, eligible) == 1.5


def test_cost_per_eligible_is_undefined_with_no_eligible_episodes() -> None:
    assert report.cost_per_eligible({"settled_usd": 9.0}, []) is None
