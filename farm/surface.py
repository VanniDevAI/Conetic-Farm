"""Which of a package's definitions are on its published surface.

`c05` step A produced the rule the whole series had been circling: a
coordination failure crosses a package boundary only when the contract that
changed is **exported**. Internal contracts are repaired by the provider's own
call-site audit, which a capable agent performs unprompted and performs well —
four for four across `s03`, `s04` and `c05a`. What survives that audit is what
the package publishes.

So "published" is not a footnote on a claim, it is the attribute that predicts
whether the claim can matter to anyone downstream. This module computes it.

A name is published when it is reachable from an entry point by `export`
statements, following relative re-exports transitively:

    export { hashKey } from './utils'          -> hashKey, named
    export * from './types'                    -> everything types.ts exports
    export * as util from './util.js'          -> everything util.ts exports,
                                                  under the namespace `util`
    export function foo()                      -> foo, defined in the entry itself

Limits, stated because a name-based answer cannot be exact: a package can
re-export through a path this does not resolve (a bare specifier, a wildcard in
`package.json`'s `exports`), and a name published under a namespace is reachable
only as `ns.name`, which callers may or may not do. Both directions are
recorded rather than smoothed over — `namespaces` says how a name got out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", "")

# export { a, b as c } from './x'   /   export { a, b }
_NAMED = re.compile(r"""^\s*export\s*\{([^}]*)\}\s*(?:from\s*["']([^"']+)["'])?""", re.M)
# export * from './x'   /   export * as ns from './x'
_STAR = re.compile(r"""^\s*export\s*\*\s*(?:as\s+([A-Za-z_$][\w$]*)\s+)?from\s*["']([^"']+)["']""", re.M)
# export function foo / export const foo / export class Foo / export type Foo
_DECL = re.compile(
    r"""^\s*export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?"""
    r"""(?:function\s*\*?|class|const|let|var|type|interface|enum|abstract\s+class)\s+"""
    r"""([A-Za-z_$][\w$]*)""", re.M)


@dataclass
class Surface:
    """The names a package publishes, and how each one got out."""
    published: set[str] = field(default_factory=set)
    namespaces: dict[str, set[str]] = field(default_factory=dict)
    entries: list[str] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)

    def is_published(self, name: str) -> bool:
        return name in self.published

    def how(self, name: str) -> str | None:
        """`"named"` for a directly exported name, or the namespaces it is under."""
        if name not in self.published:
            return None
        under = sorted(ns for ns, names in self.namespaces.items() if name in names)
        return f"namespace {', '.join(under)}" if under else "named"


def _resolve(base: Path, spec: str) -> Path | None:
    if not spec.startswith("."):
        return None                      # a bare specifier leaves this package
    target = (base.parent / spec).resolve()
    stems = [target]
    if target.suffix in (".js", ".jsx", ".mjs", ".cjs"):
        stems.insert(0, target.with_suffix(""))   # zod writes './util.js' for util.ts
    for stem in stems:
        for ext in _EXTS:
            cand = Path(str(stem) + ext) if ext else stem
            if cand.is_file():
                return cand
            index = stem / f"index{ext}" if ext else None
            if index is not None and index.is_file():
                return index
    return None


def _names_exported_by(path: Path, surface: Surface, root: Path,
                       namespace: str | None, depth: int = 0) -> set[str]:
    key = str(path)
    if depth > 12 or key in surface.visited:
        return set()
    surface.visited.add(key)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()

    out: set[str] = set()
    for m in _DECL.finditer(text):
        out.add(m.group(1))
    for m in _NAMED.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            part = part.removeprefix("type ").strip()
            name = part.split(" as ")[-1].strip() if " as " in part else part
            if name:
                out.add(name)
    for m in _STAR.finditer(text):
        ns, spec = m.group(1), m.group(2)
        target = _resolve(path, spec)
        if target is None:
            continue
        inner = _names_exported_by(target, surface, root, ns or namespace, depth + 1)
        out |= inner
        if ns:
            surface.namespaces.setdefault(ns, set()).update(inner)
    return out


def build_surface(root: Path, entry_points: list[str]) -> Surface:
    """Every name reachable by `export` from any of `entry_points`."""
    root = Path(root)
    surface = Surface(entries=list(entry_points))
    for entry in entry_points:
        path = (root / entry)
        if not path.is_file():
            continue
        surface.published |= _names_exported_by(path, surface, root, None)
    return surface
