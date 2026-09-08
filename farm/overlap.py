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
    """What one patch touches: files with hunk ranges, plus the names it moves."""
    files: dict[str, list[Hunk]] = field(default_factory=dict)
    symbols: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)


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
            continue
        if line[:1] in "+-" and line[:3] not in ("+++", "---"):
            body = line[1:]
            for sm in _SYMBOL.finditer(body):
                facts.symbols.add(sm.group(1))
            for im in _IMPORT.finditer(body):
                facts.imports.add(im.group(1))
    return facts


def classify_overlap(a: PatchFacts, b: PatchFacts) -> str:
    shared_files = set(a.files) & set(b.files)
    if shared_files:
        for path in shared_files:
            for ha in a.files[path]:
                for hb in b.files[path]:
                    if ha.touches(hb):
                        return "textual"
        return "same_file"
    if (a.symbols & b.symbols) or (a.imports & b.imports):
        return "semantic"
    return "independent"
