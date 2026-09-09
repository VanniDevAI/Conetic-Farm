"""An identity graph over a repository checkout, and reachability across it.

`farm.overlap` decides whether two patches are `semantic` -- disjoint files,
one providing what the other consumes -- by intersecting the names each patch
*writes on a changed line*. That test is blind by one hop, and the blindness is
not incidental: it is the normal shape of the failure.

    A changes  utils.ts :: timeUntilStale
    B extends  query.ts :: Query, whose existing isStaleByTime calls it

Nothing on B's changed lines says `timeUntilStale`. The name appears only in
the body of the method B is building on, which B never edits and the diff never
shows. Intersecting changed-line names finds nothing and reports `independent`.

This module supplies the missing hop. It reads the repository at the pair's
base commit and records, for every top-level definition, where it is defined
and which identifiers its body mentions. Reachability over that graph answers
the question the diff cannot: does the code B changed reach, through some chain
of named definitions, the code A changed?

Deliberate limits, because a name-based graph cannot be sound:

* Resolution is by *name*, not by scope or import. Two unrelated functions
  called `parse` are one node. That over-connects, so the result is an upper
  bound on reachability and the class it produces is a candidate, not a proof.
* Bodies are delimited by the next definition in the same file, not by parsing.
  A trailing block of module-level code is attributed to the definition above
  it.
* Only definitions are nodes. A call through a value, a table of handlers, or
  reflection is invisible.

Both directions of error are reported rather than hidden: `reaches` returns the
path it found, so every positive can be read and checked by hand, and the
census reports the count with the old count beside it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

# Extensions we can index, grouped by the definition syntax they share.
_PY = {".py"}
_TS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts"}
_GO = {".go"}
_RS = {".rs"}
INDEXABLE = _PY | _TS | _GO | _RS

# Directories that hold no first-party source and cost minutes to walk.
_SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "target", "vendor",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".next", "coverage", "site-packages",
}

_DEF_PATTERNS = {
    "py": [
        re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),
    ],
    "ts": [
        re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"),
        re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
        # Only module-level bindings. An indented `const ratio = val / step`
        # is a local, and admitting locals as graph nodes connects every
        # function that happens to name a variable the same way.
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]"),
        re.compile(r"^(?:export\s+)?(?:type|interface|enum)\s+([A-Za-z_$][\w$]*)"),
        # Class members: `foo(args) {`, `get foo()`, `#foo(` -- indented, and
        # not a control keyword.
        re.compile(r"^\s{2,}(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|get\s+|set\s+|async\s+)*#?([A-Za-z_$][\w$]*)\s*[(<]"),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"),
        re.compile(r"^type\s+([A-Za-z_]\w*)"),
    ],
    "rs": [
        re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|impl)\s+([A-Za-z_]\w*)"),
    ],
}

# Reserved words that the member-definition pattern would otherwise capture.
_NOT_DEFS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "await",
    "new", "case", "do", "else", "try", "function", "class", "constructor",
    "import", "export", "yield", "delete", "in", "of", "with", "throw",
}

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")

# Identifiers so common that an edge through them says nothing about coupling.
_STOPWORDS = _NOT_DEFS | {
    "const", "let", "var", "this", "self", "true", "false", "null", "undefined",
    "void", "any", "string", "number", "boolean", "object", "type", "interface",
    "def", "pass", "None", "True", "False", "print", "len", "str", "int",
    "float", "dict", "list", "set", "tuple", "range", "super", "async", "from",
    "as", "is", "not", "and", "or", "public", "private", "protected", "static",
    "readonly", "extends", "implements", "enum", "declare", "namespace", "get",
    "err", "nil", "fn", "pub", "mut", "impl", "struct", "match", "Some", "Ok",
    "Err", "String", "Vec", "Option", "Result", "Self", "crate", "use",
}


def _family(path: Path) -> str | None:
    ext = path.suffix
    if ext in _PY:
        return "py"
    if ext in _TS:
        return "ts"
    if ext in _GO:
        return "go"
    if ext in _RS:
        return "rs"
    return None


@dataclass(frozen=True)
class Definition:
    """One named definition and the half-open line span [start, end) it owns."""
    name: str
    path: str
    start: int
    end: int


@dataclass
class Index:
    """Definitions by name, definitions by file, and each body's identifiers."""
    by_name: dict[str, list[Definition]] = field(default_factory=dict)
    by_path: dict[str, list[Definition]] = field(default_factory=dict)
    refs: dict[Definition, frozenset[str]] = field(default_factory=dict)
    files_indexed: int = 0

    def enclosing(self, path: str, line: int) -> Definition | None:
        """The definition whose span contains `line` in `path`, innermost last.

        Spans are built from consecutive definition starts, so a nested
        definition's span is contained in nothing -- the last definition
        starting at or before the line is the innermost one.
        """
        best: Definition | None = None
        for d in self.by_path.get(path, ()):
            if d.start <= line < d.end:
                best = d
        return best

    def enclosing_for_hunks(self, path: str, hunks) -> set[Definition]:
        out: set[Definition] = set()
        for h in hunks:
            for line in range(h.start, h.end + 1):
                d = self.enclosing(path, line)
                if d is not None:
                    out.add(d)
        return out


def _definitions_in(text: str, rel: str, family: str) -> list[Definition]:
    pats = _DEF_PATTERNS[family]
    lines = text.splitlines()
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        for pat in pats:
            m = pat.match(line)
            if m:
                name = m.group(1)
                if name in _NOT_DEFS:
                    break
                starts.append((i, name))
                break
    out: list[Definition] = []
    for idx, (line_no, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines) + 1
        out.append(Definition(name=name, path=rel, start=line_no, end=end))
    return out


def build_index(root: Path, *, max_bytes: int = 400_000) -> Index:
    """Index every source file under `root` that we know how to read.

    `max_bytes` skips generated blobs (bundled locale tables, lock-like data
    files); they define nothing a patch is likely to reach through and they
    dominate the walk.
    """
    idx = Index()
    root = Path(root)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in INDEXABLE:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        family = _family(path)
        if family is None:
            continue
        rel = str(path.relative_to(root))
        defs = _definitions_in(text, rel, family)
        if not defs:
            continue
        idx.files_indexed += 1
        idx.by_path[rel] = defs
        lines = text.splitlines()
        for d in defs:
            idx.by_name.setdefault(d.name, []).append(d)
            body = "\n".join(lines[d.start: min(d.end - 1, len(lines))])
            names = {t for t in _IDENT.findall(body) if t not in _STOPWORDS}
            names.discard(d.name)
            idx.refs[d] = frozenset(names)
    return idx


def reaches(idx: Index, start: set[Definition], targets: set[Definition],
            *, max_hops: int = 3) -> list[str] | None:
    """A shortest name path from any `start` body to any `targets` definition.

    Returns the chain of names walked, or None. `max_hops` bounds how far a
    consumer may sit from the provider; 1 is "B's own body names it", 2 is
    "B's body names something whose body names it", and so on. A chain of k
    edges comes back as k+1 names, starting with the consumer's own.

    The two guards below are the whole contract and they used to be off by one:
    the target check ran unguarded, so a node already at the budget could still
    return one more edge, and expansion was allowed from that node too. The
    result was that `max_hops=1` walked two edges and `max_hops=3` walked four.
    Everything the campaign measured in hops meant one more than it said.
    """
    target_names = {d.name for d in targets}
    target_keys = {(d.path, d.name) for d in targets}
    frontier: deque[tuple[Definition, list[str]]] = deque()
    seen: set[tuple[str, str]] = set()
    for d in start:
        frontier.append((d, [d.name]))
        seen.add((d.path, d.name))
    while frontier:
        node, path_names = frontier.popleft()
        # Returning from here costs one more edge, so this node may only be
        # examined while the budget still has that edge in it.
        if len(path_names) > max_hops:
            continue
        for name in idx.refs.get(node, ()):  # names this body mentions
            if name in target_names:
                for t in idx.by_name.get(name, ()):
                    if (t.path, t.name) in target_keys:
                        return path_names + [name]
            # A neighbour costs an edge to reach and another to return from.
            if len(path_names) >= max_hops:
                continue
            for nxt in idx.by_name.get(name, ()):
                key = (nxt.path, nxt.name)
                if key in seen:
                    continue
                seen.add(key)
                frontier.append((nxt, path_names + [name]))
    return None
