"""The roomed arm's brief, built from the claim map. No model in the loop.

The question c06 asks is whether a *room* -- a prepared account of what the
code already assumes and who already depends on it -- changes what an agent
ships. That only means anything if the room is machine-made. If a model wrote
the brief, the experiment would be measuring the model that wrote it.

So every line below comes from the repository itself:

``assumes``          outbound edges of the files the task will touch: the
                     definitions their bodies reference, resolved through
                     `farm.identity`, with the file and line that defines each.
``changed since``    what is already claimed in the namespaces a second agent
                     could collide in -- migration ordinals, route names,
                     config keys -- read straight off the tree by
                     `farm.conventions`' own parsers.
``look first``       inbound edges: the definitions elsewhere that reference
                     what the task will touch, which is the list of things that
                     break if the task changes shape.

The room originally closed with a numbered assumption check -- write your
assumptions down, compare them against the lists, only then start editing --
and was appended *after* the task brief. That is now off by default, because
of what it did.

**The closing protocol is ablated.** In c06 and c06b the room was the last
thing a roomed agent read, and its last sentence told the agent to start
editing. Roomed lanes then skipped the submit step at 5 of 12 against bare's
1 of 12 (pooled, p = 0.155): they wrote the feature, ran the suite green, wrote
a prose summary, and never ran a git command. Nothing in the closing list is
wrong; it is simply the last instruction in the prompt, and it is an
instruction to begin rather than to finish.

So the facts now go *before* the task, where context belongs, and the task's
own working agreement is again the last thing read. `closing_protocol=True`
restores the old form for reproducing those runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from .identity import Index, build_index

_ENV_SCHEMA_KEY = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*:\s*z\.")
_PROCEDURE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*:\s*(?:[A-Za-z_$][\w$]*Procedure|[A-Za-z_$][\w$]*Router)\b")

# The ablated block. Kept, not deleted, so c06 and c06b remain reproducible and
# so a future arm can test the facts and the protocol separately.
PROTOCOL = """
### Before you write anything

1. Write down, in one short list, what your change assumes about the code above
   — the shapes it reads, the names it adds, the tables it touches.
2. Check each assumption against the two lists above. Say explicitly which of
   your assumptions the room confirms and which it does not cover.
3. Only then start editing.

Do not skip step 1 because the task looks small. The failures this exists to
prevent all look small from inside one branch.
"""


def _existing_migrations(root: Path) -> list[str]:
    d = root / "prisma" / "migrations"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def _existing_routes(root: Path) -> list[str]:
    out: set[str] = set()
    for path in (root / "src" / "server" / "routers").rglob("*.ts"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _PROCEDURE.match(line)
            if m:
                out.add(m.group(1))
    return sorted(out)


def _existing_config_keys(root: Path) -> list[str]:
    out: set[str] = set()
    env = root / "src" / "server" / "env.ts"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _ENV_SCHEMA_KEY.match(line)
            if m:
                out.add(m.group(1))
    return sorted(out)


def _assumes(idx: Index, targets: list[str], limit: int = 12) -> list[str]:
    """Definitions the target files' own bodies reach, one hop out."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for target in targets:
        for d in idx.by_path.get(target, ()):
            for name in sorted(idx.refs.get(d, ())):
                for other in idx.by_name.get(name, ()):
                    if other.path == target or name in seen:
                        continue
                    seen.add(name)
                    rows.append((name, f"{other.path}:{other.start}"))
                    break
    return [f"`{n}` — defined at `{loc}`" for n, loc in sorted(rows)[:limit]]


def _look_first(idx: Index, targets: list[str], limit: int = 12) -> list[str]:
    """Definitions elsewhere whose bodies reach into the target files."""
    owned = {d.name for t in targets for d in idx.by_path.get(t, ())}
    rows: set[tuple[str, str]] = set()
    for path, defs in idx.by_path.items():
        if path in targets:
            continue
        for d in defs:
            hit = owned & set(idx.refs.get(d, ()))
            if hit:
                rows.add((f"{path}:{d.start}", ", ".join(sorted(hit)[:3])))
    return [f"`{loc}` — uses {names}" for loc, names in sorted(rows)[:limit]]


def build(root: Path, targets: list[str], *, index: Index | None = None,
          closing_protocol: bool = False) -> str:
    """The room, as markdown, for a task that will touch `targets`.

    `closing_protocol` restores the trailing numbered assumption check that
    c06 and c06b ran with. It is off by default; see the module docstring.
    """
    root = Path(root)
    idx = index or build_index(root)
    assumes = _assumes(idx, targets)
    look = _look_first(idx, targets)
    migrations = _existing_migrations(root)
    routes = _existing_routes(root)
    keys = _existing_config_keys(root)

    protocol = PROTOCOL if closing_protocol else ""

    def block(title: str, rows: list[str], empty: str) -> str:
        body = "\n".join(f"* {r}" for r in rows) if rows else f"* {empty}"
        return f"### {title}\n\n{body}\n"

    return f"""
## The room

This section is generated from the repository, not written for you. It says
what the code you are about to touch already relies on, what names are already
taken, and who is relying on you.

{block("What this code assumes", assumes,
        "nothing outside its own file")}
{block("Who looks at it — check these before you change a shape", look,
        "nothing else reaches into these files")}
### What is already claimed

Other work lands in the same namespaces. These are taken; picking one of them
again is a collision nobody's tests will report.

* migrations already present: {", ".join(f"`{m}`" for m in migrations) or "none"}
* route names already registered: {", ".join(f"`{r}`" for r in routes) or "none"}
* config keys already defined: {", ".join(f"`{k}`" for k in keys) or "none"}

{protocol}"""
