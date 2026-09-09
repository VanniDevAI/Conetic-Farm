"""How two patches relate: the overlap class an episode records.

`c04` targets the *semantic* class -- a clean merge whose combined tests fail --
and neither selecting for it nor reporting it honestly is possible unless each
episode says what kind of overlap its two patches had.

Four classes, in decreasing order of what a merge tool can see:

``textual``      same file, hunks touching or abutting. git refuses. This is the
                 class `git merge` already reports for free.
``same_file``    same file, hunks far enough apart that git merges cleanly.
                 Textually fine and semantically the most dangerous shape there
                 is: two edits in one file that never meet in the diff.
``semantic``     disjoint files sharing a symbol, type or import -- one side
                 provides, the other consumes. Invisible to any merge tool.
``independent``  disjoint files with nothing in common.

The order is deliberate: a pair can be several of these at once, and the class
reported is the strongest claim about the *merge*, because that is what decides
the outcome. A pair git will refuse must never be filed under a class git
cannot see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# git's three-way merge needs unchanged context between two hunks. Hunks closer
# than this conflict even when their changed lines do not literally overlap, so
# "not overlapping" is not the same as "merges cleanly".
CONTEXT_LINES = 3


@dataclass(frozen=True)
class Hunk:
    start: int
    end: int

    def touches(self, other: "Hunk", pad: int = CONTEXT_LINES) -> bool:
        return not (self.end + pad < other.start or other.end + pad < self.start)


@dataclass
class PatchFacts:
    """What one patch touches: files with hunk ranges, plus the names it moves.

    `changed_lines` is narrower than `files` on purpose. A hunk range spans its
    context lines too, so asking "which definition does this hunk sit in" via
    the range alone drags in whichever neighbours the three lines of context
    reach. `changed_lines` holds only old-side positions the patch actually
    edits: the line number of every removed line, and the position an added
    line is inserted at. That is the right input for the identity graph, which
    needs to know what a patch *changed*, not what it happened to print.
    """
    files: dict[str, list[Hunk]] = field(default_factory=dict)
    symbols: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    changed_lines: dict[str, set[int]] = field(default_factory=dict)


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_IMPORT = re.compile(r"""from\s+['"]([^'"]+)['"]""")
# Exported or declared names a patch adds or removes -- the things another file
# could plausibly consume.
_SYMBOL = re.compile(
    r"\b(?:export\s+(?:type|interface|const|function|class|enum)|"
    r"type|interface|function|class|const)\s+([A-Za-z_$][\w$]*)")


def parse_patch(text: str) -> PatchFacts:
    """Facts about a unified diff: files and hunk ranges, symbols, imports.

    Hunk ranges are taken from the *old* side, because two patches are compared
    against the same base and only the base's line numbers are common ground.
    """
    facts = PatchFacts()
    current: str | None = None
    old_line = 0
    for line in text.splitlines():
        m = _FILE.match(line)
        if m:
            current = m.group(2)
            facts.files.setdefault(current, [])
            continue
        m = _HUNK.match(line)
        if m and current:
            start = int(m.group(1))
            length = int(m.group(2) or 1)
            facts.files[current].append(Hunk(start, start + max(length, 1) - 1))
            old_line = start
            continue
        if line[:1] in "+-" and line[:3] not in ("+++", "---"):
            if current is not None:
                facts.changed_lines.setdefault(current, set()).add(old_line)
                if line[0] == "-":
                    old_line += 1
            body = line[1:]
            for sm in _SYMBOL.finditer(body):
                facts.symbols.add(sm.group(1))
            for im in _IMPORT.finditer(body):
                facts.imports.add(im.group(1))
            continue
        if current is not None and line[:1] in (" ", ""):
            old_line += 1
    return facts


def changed_definitions(facts: PatchFacts, idx) -> set:
    """The definitions a patch actually edits, per the identity graph.

    Uses `changed_lines`, not hunk ranges: a hunk's context reaches into
    whatever definitions happen to sit three lines away, and those are not
    what the patch changed.
    """
    out = set()
    for path, lines in facts.changed_lines.items():
        for line in lines:
            d = idx.enclosing(path, line)
            if d is not None:
                out.add(d)
    return out


def semantic_link(a: PatchFacts, b: PatchFacts, idx, *, max_hops: int = 3):
    """A chain of names from one patch's changed code to the other's, or None.

    Both directions are tried because which side is the provider is not known
    in advance -- that is a fact about the code, not about the patch order.
    """
    from farm.identity import reaches
    A, B = changed_definitions(a, idx), changed_definitions(b, idx)
    if not A or not B:
        return None
    return reaches(idx, B, A, max_hops=max_hops) or reaches(idx, A, B, max_hops=max_hops)


def classify_overlap(a: PatchFacts, b: PatchFacts, idx=None) -> str:
    """The overlap class, optionally resolved through an identity graph.

    Without `idx` the semantic test is the original one: do the two patches
    name the same symbol or import *on a line one of them changed*. That test
    is blind by one hop, which is the normal shape of the failure -- the
    provider's name lives in the body of the consumer's existing method, and
    neither diff prints it. With `idx` the same question is asked of the code
    instead of the diff.

    The precedence is unchanged, and it is why supplying `idx` cannot move a
    pair that shares a file: a pair git will refuse must not be filed under a
    class git cannot see. `semantic_link` answers the narrower question --
    is there a provider/consumer chain here at all -- for pairs of any class.
    """
    shared_files = set(a.files) & set(b.files)
    if shared_files:
        for path in shared_files:
            for ha in a.files[path]:
                for hb in b.files[path]:
                    if ha.touches(hb):
                        return "textual"
        return "same_file"
    if idx is not None:
        return "semantic" if semantic_link(a, b, idx) else "independent"
    if (a.symbols & b.symbols) or (a.imports & b.imports):
        return "semantic"
    return "independent"
