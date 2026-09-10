"""Classify how two patches relate, so an episode records WHY a merge behaved as it did.

c04 targets the semantic class -- clean merge, failing combined tests -- and to
select for it, or even to report it honestly, an episode has to say what kind of
overlap its two patches had. Four kinds, and the boundaries carry the meaning:

* ``textual``      same file, hunks that touch or abut. git cannot merge these;
                   this is the class git already reports for free.
* ``same_file``    same file, hunks far enough apart that git merges them
                   cleanly. Textually fine, semantically the most dangerous
                   shape there is -- two edits to one function's neighbourhood
                   that never meet in the diff.
* ``semantic``     disjoint files that share a symbol, type or import. One side
                   provides, the other consumes. No merge tool can see it.
* ``independent``  disjoint files with nothing in common.

Adjacency matters: git's three-way merge needs context lines between two hunks,
so hunks separated by less than a context window conflict even though their
changed lines do not literally overlap. Treating "not overlapping" as "merges
cleanly" would mislabel exactly the pairs c04 must not confuse.
"""

from __future__ import annotations

from farm.overlap import Hunk, PatchFacts, classify_overlap, parse_patch

A_FILE = "src/logic/createFormControl.ts"
B_FILE = "src/useForm.ts"


def _p(files):
    return PatchFacts(files=files, symbols=set(), imports=set())


def test_same_file_overlapping_hunks_is_textual() -> None:
    a = _p({A_FILE: [Hunk(1098, 1104)]})
    b = _p({A_FILE: [Hunk(1100, 1110)]})
    assert classify_overlap(a, b) == "textual"


def test_same_file_adjacent_hunks_are_textual_too() -> None:
    """Separated by less than git's context window: no literal overlap, but the
    merge still refuses. Calling this clean would be wrong in the direction that
    matters."""
    a = _p({A_FILE: [Hunk(100, 105)]})
    b = _p({A_FILE: [Hunk(107, 112)]})
    assert classify_overlap(a, b) == "textual"


def test_same_file_distant_hunks_merge_cleanly() -> None:
    a = _p({A_FILE: [Hunk(100, 105)]})
    b = _p({A_FILE: [Hunk(900, 910)]})
    assert classify_overlap(a, b) == "same_file"


def test_disjoint_files_sharing_a_symbol_is_semantic() -> None:
    a = PatchFacts(files={A_FILE: [Hunk(10, 20)]}, symbols={"UseFormHandleSubmit"}, imports=set())
    b = PatchFacts(files={B_FILE: [Hunk(10, 20)]}, symbols={"UseFormHandleSubmit"}, imports=set())
    assert classify_overlap(a, b) == "semantic"


def test_disjoint_files_sharing_an_import_is_semantic() -> None:
    a = PatchFacts(files={A_FILE: [Hunk(10, 20)]}, symbols=set(), imports={"./types/form"})
    b = PatchFacts(files={B_FILE: [Hunk(10, 20)]}, symbols=set(), imports={"./types/form"})
    assert classify_overlap(a, b) == "semantic"


def test_disjoint_files_with_nothing_shared_are_independent() -> None:
    a = PatchFacts(files={A_FILE: [Hunk(10, 20)]}, symbols={"foo"}, imports={"./x"})
    b = PatchFacts(files={B_FILE: [Hunk(10, 20)]}, symbols={"bar"}, imports={"./y"})
    assert classify_overlap(a, b) == "independent"


def test_textual_wins_when_a_pair_is_both() -> None:
    """Two patches can share a file AND a symbol elsewhere. The merge outcome is
    decided by the file overlap, so that is the class -- otherwise a pair git
    will refuse gets filed under the class git cannot see."""
    a = PatchFacts(files={A_FILE: [Hunk(100, 105)], B_FILE: [Hunk(1, 5)]},
                   symbols={"S"}, imports=set())
    b = PatchFacts(files={A_FILE: [Hunk(101, 106)]}, symbols={"S"}, imports=set())
    assert classify_overlap(a, b) == "textual"


def test_same_file_distant_beats_semantic_when_both_apply() -> None:
    """Sharing a file at all is a stronger statement than sharing a symbol."""
    a = PatchFacts(files={A_FILE: [Hunk(100, 105)]}, symbols={"S"}, imports=set())
    b = PatchFacts(files={A_FILE: [Hunk(900, 905)], B_FILE: [Hunk(1, 5)]},
                   symbols={"S"}, imports=set())
    assert classify_overlap(a, b) == "same_file"


def test_a_blank_line_in_a_patch_does_not_crash_the_parser():
    """`line[:1] in "+-"` is true for the empty string, and then line[0] raises.

    Real patches carry blank lines: a diff of a file whose trailing context is
    an empty line writes one. The census hit this on its first repository, four
    tasks in, having already spent the clone time.
    """
    text = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
        "@@ -1,4 +1,4 @@\n def f():\n\n-    return 1\n+    return 2\n"
    )
    facts = parse_patch(text)
    assert set(facts.files) == {"x.py"}
    assert facts.changed_lines["x.py"]
