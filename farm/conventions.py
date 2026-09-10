"""Collisions no test suite reports and no merge tool sees.

The claim map answers "does one branch's code reach the other's". These graders
answer a different question that matters just as much on a real application:
did two branches independently claim the same *name* in a shared namespace.
Nobody's tests fail, `git` merges happily when the two additions land in
different files, and the application is broken or silently wrong.

Three namespaces, chosen because each one is ordered or unique by convention
rather than by the compiler:

``migration_ordinals``  two branches adding the same sequence number. The
                        second migration to merge is either skipped or applied
                        out of order, depending on the tool.
``route_paths``         two branches registering the same route. One wins,
                        silently, and which one depends on merge order.
``config_keys``         two branches introducing the same environment or
                        settings key with different defaults.

Everything here reads **added lines only**, from the patch rather than from the
tree, because the question is what a branch introduced. A line both branches
happen to keep is not a collision.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# prisma/migrations/20240117120000_add_comments/migration.sql
_MIGRATION = re.compile(r"(?:^|/)migrations/(\d+)_([A-Za-z0-9_.-]*)/")
# also catch a sequence-numbered convention: migrations/0042_name.sql
_MIGRATION_FLAT = re.compile(r"(?:^|/)migrations/(\d+)[_-]([A-Za-z0-9_.-]+)\.(?:sql|ts|js)")

# `name: publicProcedure` / `name: protectedProcedure` / `name: somethingRouter`
_PROCEDURE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*:\s*(?:[A-Za-z_$][\w$]*Procedure|[A-Za-z_$][\w$]*Router)\b")
# express/hono/next style: app.get('/path'), router.post('/path')
_HTTP_ROUTE = re.compile(r"""\.\s*(get|post|put|patch|delete|all)\s*\(\s*["'`]([^"'`]+)["'`]""")

# `KEY: z.string()` inside an env schema, and direct process.env reads
_ENV_SCHEMA_KEY = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*:\s*z\.")
_PROCESS_ENV = re.compile(r"process\.env\.([A-Z][A-Z0-9_]{2,})")
_ENV_FILE_KEY = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=")

_FILE = re.compile(r"^\+\+\+ b/(.+)$")


@dataclass
class BranchFacts:
    """What one branch introduced in each shared namespace."""
    migrations: dict[str, str] = field(default_factory=dict)   # ordinal -> name
    routes: set[str] = field(default_factory=set)
    config_keys: set[str] = field(default_factory=set)


def parse_branch(patch_text: str) -> BranchFacts:
    facts = BranchFacts()
    current = ""
    for line in patch_text.splitlines():
        m = _FILE.match(line)
        if m:
            current = m.group(1)
            for pat in (_MIGRATION, _MIGRATION_FLAT):
                mm = pat.search(current)
                if mm:
                    facts.migrations[mm.group(1)] = mm.group(2)
                    break
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        m = _PROCEDURE.match(body)
        if m:
            facts.routes.add(m.group(1))
        for m in _HTTP_ROUTE.finditer(body):
            facts.routes.add(f"{m.group(1).upper()} {m.group(2)}")
        m = _ENV_SCHEMA_KEY.match(body)
        if m:
            facts.config_keys.add(m.group(1))
        if current.endswith(".env") or "/.env" in current or current == ".env.example":
            m = _ENV_FILE_KEY.match(body)
            if m:
                facts.config_keys.add(m.group(1))
        for m in _PROCESS_ENV.finditer(body):
            facts.config_keys.add(m.group(1))
    return facts


def grade(branches: dict[str, str]) -> dict:
    """Cross-branch collisions, given ``{lane: patch text}``.

    Every namespace is reported even when empty, so a zero reads as "looked for
    and not found" rather than "not measured". `concurrent_migrations` is
    reported separately from `migration_ordinals` and is **not** a hit: two
    branches adding differently-numbered migrations is normal, and calling it a
    collision would drown the signal that matters.
    """
    facts = {lane: parse_branch(text) for lane, text in branches.items()}

    by_ordinal: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for lane, f in facts.items():
        for ordinal, name in f.migrations.items():
            by_ordinal[ordinal].append((lane, name))
    ordinal_hits = [
        {"ordinal": ordinal, "lanes": sorted(lane for lane, _ in rows),
         "names": sorted(name for _, name in rows)}
        for ordinal, rows in sorted(by_ordinal.items()) if len(rows) > 1
    ]

    def collisions(attr: str, key: str) -> list[dict]:
        owners: dict[str, list[str]] = defaultdict(list)
        for lane, f in facts.items():
            for value in getattr(f, attr):
                owners[value].append(lane)
        return [{key: value, "lanes": sorted(lanes)}
                for value, lanes in sorted(owners.items()) if len(lanes) > 1]

    adding = sorted(lane for lane, f in facts.items() if f.migrations)
    return {
        "migration_ordinals": ordinal_hits,
        "route_paths": collisions("routes", "path"),
        "config_keys": collisions("config_keys", "key"),
        "concurrent_migrations": {
            "lanes": adding,
            "count": len(adding),
            "note": "not a hit: differently-numbered migrations from two "
                    "branches are ordinary, and only a shared ordinal is a "
                    "collision",
        },
        "per_lane": {lane: {"migrations": f.migrations,
                            "routes": sorted(f.routes),
                            "config_keys": sorted(f.config_keys)}
                     for lane, f in sorted(facts.items())},
    }
