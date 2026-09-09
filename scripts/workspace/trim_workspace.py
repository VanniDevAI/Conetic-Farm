#!/usr/bin/env python3
"""Cut a repository down to one agent's territory, inside its own container.

Step 3 asks for the ownership boundary to be enforced by the sandbox rather
than by the brief: the provider agent must not be able to find the consumer's
call site at all, however diligently it greps.

The cut is by *runtime* import edges. A file is removed when it imports the
forbidden module, directly or transitively, through an import that survives to
runtime. `import type` edges are not followed: they vanish at compile time, so
a file carrying only a type edge still runs, and following them would delete
the very file the agent owns (in both seeded pairs the provider type-imports
the consumer -- they are peers in one package, which is exactly why a package
boundary does not already exist here).

The consequence is deliberate and worth stating: the agent keeps a workspace it
can run scratch tests in, and loses the repository's own suite, because that
suite lives on the other side of the boundary. That is what working inside one
package of a split repository actually feels like.

Usage:
    trim_workspace.py <repo_root> --keep <path> --forbid <path> [--forbid ...]

Exits non-zero, changing nothing, if the kept file would itself be removed or
if any forbidden name still appears in the tree afterwards.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# A runtime import: `from "x"` or `require("x")`, but never `import type ...`
# and never `export type ... from`.
_FROM = re.compile(r"""(?<!\btype\s)\bfrom\s+["']([^"']+)["']""")
_REQUIRE = re.compile(r"""\brequire\(\s*["']([^"']+)["']\s*\)""")
_TYPE_LINE = re.compile(r"^\s*(?:import|export)\s+type\b")

_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", "")


def _runtime_imports(path: Path) -> set[Path]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    out: set[Path] = set()
    for line in text.splitlines():
        if _TYPE_LINE.match(line):
            continue
        for m in list(_FROM.finditer(line)) + list(_REQUIRE.finditer(line)):
            spec = m.group(1)
            if not spec.startswith("."):
                continue
            base = (path.parent / spec).resolve()
            # zod writes `./checks.js` for `checks.ts`; try the source first.
            stems = [base]
            if base.suffix in (".js", ".jsx", ".mjs"):
                stems.insert(0, base.with_suffix(""))
            for stem in stems:
                for ext in _EXTS:
                    cand = Path(str(stem) + ext) if ext else stem
                    if cand.is_file():
                        out.add(cand)
                        break
                    idx = stem / f"index{ext}" if ext else None
                    if idx is not None and idx.is_file():
                        out.add(idx)
                        break
                else:
                    continue
                break
    return out


def dependents_closure(root: Path, forbidden: set[Path]) -> set[Path]:
    """Every file that reaches a forbidden file through runtime imports."""
    sources = [p for p in root.rglob("*")
               if p.is_file() and p.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs")
               and "node_modules" not in p.parts and ".git" not in p.parts]
    edges = {p: _runtime_imports(p) for p in sources}
    doomed = set(forbidden)
    changed = True
    while changed:
        changed = False
        for src, deps in edges.items():
            if src not in doomed and deps & doomed:
                doomed.add(src)
                changed = True
    return doomed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--keep", action="append", required=True)
    ap.add_argument("--forbid", action="append", required=True)
    ap.add_argument("--absent", action="append", default=[],
                    help="name that must not appear anywhere afterwards")
    ap.add_argument("--drop-tests-outside", default=None,
                    help="remove every *.test.* file not under this directory; "
                         "tests belong to whoever owns the module, and the ones "
                         "left behind by the cut only fail confusingly")
    ap.add_argument("--message", default="workspace: this agent's package only")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    keep = {(root / k).resolve() for k in args.keep}
    forbid = {(root / f).resolve() for f in args.forbid}
    for f in forbid:
        if not f.is_file():
            print(f"FATAL: forbidden path not found: {f}", file=sys.stderr)
            return 2

    # Seed with the forbidden files, then iterate: any surviving file that
    # still *mentions* a forbidden name becomes a seed too. One pass is not
    # enough -- zod carries a whole second implementation under `src/v3` with
    # its own `floatSafeRemainder`, which no import edge connects to `core`
    # but which shows the same `!== 0` caller shape the boundary exists to
    # hide.
    if args.drop_tests_outside:
        own = (root / args.drop_tests_outside).resolve()
        for path in list(root.rglob("*")):
            if not path.is_file() or "node_modules" in path.parts or ".git" in path.parts:
                continue
            if ".test." not in path.name and ".spec." not in path.name:
                continue
            rp = path.resolve()
            if own in rp.parents or rp == own:
                continue
            forbid.add(rp)

    doomed = dependents_closure(root, forbid)
    for _ in range(10):
        extra = set()
        for path in root.rglob("*"):
            if (not path.is_file() or path.suffix not in
                    (".ts", ".tsx", ".js", ".jsx", ".mjs")):
                continue
            if "node_modules" in path.parts or ".git" in path.parts:
                continue
            rp = path.resolve()
            if rp in doomed or rp in keep:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(name in text for name in args.absent):
                extra.add(rp)
        if not extra:
            break
        doomed = dependents_closure(root, doomed | extra)
    if doomed & keep:
        print("FATAL: the kept file is itself a runtime dependent of the "
              f"forbidden one: {sorted(str(p) for p in doomed & keep)}",
              file=sys.stderr)
        return 3

    rel = sorted(str(p.relative_to(root)) for p in doomed)
    subprocess.run(["git", "rm", "-q", "--ignore-unmatch", *rel],
                   cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=farm@local", "-c", "user.name=farm",
                    "commit", "-q", "-m", args.message], cwd=root, check=True)

    leaks: list[str] = []
    for name in args.absent:
        r = subprocess.run(["grep", "-rn", "--include=*.ts", "--include=*.tsx",
                            "--include=*.js", "--exclude-dir=node_modules", name, "."],
                           cwd=root, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            path = line.split(":", 1)[0].lstrip("./")
            if (root / path).resolve() in keep:
                continue          # the provider defining its own name is fine
            leaks.append(line)
    if leaks:
        print("FATAL: forbidden name still reachable:", file=sys.stderr)
        for line in leaks[:20]:
            print("   " + line, file=sys.stderr)
        return 4

    print(f"removed {len(rel)} file(s); tree clean")
    for line in rel[:40]:
        print("   - " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
