"""The convention graders, against the shapes the step B corpus actually uses.

These catch what neither the compiler nor `git` will: two branches claiming the
same name in a namespace that is unique or ordered only by convention. The
fixtures below are written in the exact syntax of
`trpc/examples-next-prisma-starter`, because a grader that works on invented
syntax and not on the corpus is worse than none.
"""
from __future__ import annotations

from farm.conventions import grade, parse_branch

MIGRATION_A = """diff --git a/prisma/migrations/20240117120000_add_comments/migration.sql b/prisma/migrations/20240117120000_add_comments/migration.sql
--- /dev/null
+++ b/prisma/migrations/20240117120000_add_comments/migration.sql
@@ -0,0 +1,2 @@
+CREATE TABLE "Comment" ("id" TEXT NOT NULL);
"""

MIGRATION_B_SAME_ORDINAL = """diff --git a/prisma/migrations/20240117120000_add_tags/migration.sql b/prisma/migrations/20240117120000_add_tags/migration.sql
--- /dev/null
+++ b/prisma/migrations/20240117120000_add_tags/migration.sql
@@ -0,0 +1,2 @@
+CREATE TABLE "Tag" ("id" TEXT NOT NULL);
"""

MIGRATION_C_OTHER_ORDINAL = """diff --git a/prisma/migrations/20240118090000_add_votes/migration.sql b/prisma/migrations/20240118090000_add_votes/migration.sql
--- /dev/null
+++ b/prisma/migrations/20240118090000_add_votes/migration.sql
@@ -0,0 +1,2 @@
+CREATE TABLE "Vote" ("id" TEXT NOT NULL);
"""

ROUTER_A = """diff --git a/src/server/routers/_app.ts b/src/server/routers/_app.ts
--- a/src/server/routers/_app.ts
+++ b/src/server/routers/_app.ts
@@ -6,6 +6,7 @@ export const appRouter = router({
   post: postRouter,
+  comment: commentRouter,
 });
"""

ROUTER_B_SAME_PATH = """diff --git a/src/server/routers/_app.ts b/src/server/routers/_app.ts
--- a/src/server/routers/_app.ts
+++ b/src/server/routers/_app.ts
@@ -6,6 +6,7 @@ export const appRouter = router({
   post: postRouter,
+  comment: threadRouter,
 });
"""

CONFIG_A = """diff --git a/src/server/env.ts b/src/server/env.ts
--- a/src/server/env.ts
+++ b/src/server/env.ts
@@ -8,6 +8,7 @@ const envSchema = z.object({
   NODE_ENV: z.enum(['development', 'test', 'production']),
+  PAGE_SIZE: z.string().default('50'),
 });
"""

CONFIG_B_SAME_KEY = """diff --git a/src/server/env.ts b/src/server/env.ts
--- a/src/server/env.ts
+++ b/src/server/env.ts
@@ -8,6 +8,7 @@ const envSchema = z.object({
   NODE_ENV: z.enum(['development', 'test', 'production']),
+  PAGE_SIZE: z.string().default('20'),
 });
"""


def test_a_shared_migration_ordinal_is_a_hit():
    out = grade({"A": MIGRATION_A, "B": MIGRATION_B_SAME_ORDINAL})
    assert out["migration_ordinals"] == [
        {"ordinal": "20240117120000", "lanes": ["A", "B"],
         "names": ["add_comments", "add_tags"]}]


def test_different_ordinals_are_not_a_hit_but_are_recorded():
    out = grade({"A": MIGRATION_A, "B": MIGRATION_C_OTHER_ORDINAL})
    assert out["migration_ordinals"] == []
    assert out["concurrent_migrations"]["lanes"] == ["A", "B"]


def test_two_branches_registering_the_same_route_is_a_hit():
    out = grade({"A": ROUTER_A, "B": ROUTER_B_SAME_PATH})
    assert out["route_paths"] == [{"path": "comment", "lanes": ["A", "B"]}]


def test_the_same_config_key_from_two_branches_is_a_hit():
    out = grade({"A": CONFIG_A, "B": CONFIG_B_SAME_KEY})
    assert out["config_keys"] == [{"key": "PAGE_SIZE", "lanes": ["A", "B"]}]


def test_one_branch_alone_never_collides_with_itself():
    out = grade({"A": MIGRATION_A + ROUTER_A + CONFIG_A})
    assert out["migration_ordinals"] == []
    assert out["route_paths"] == []
    assert out["config_keys"] == []
    assert out["per_lane"]["A"]["routes"] == ["comment"]


def test_removed_lines_are_not_introductions():
    """A branch that deletes a key has not claimed it."""
    removal = CONFIG_A.replace("+  PAGE_SIZE", "-  PAGE_SIZE")
    out = grade({"A": removal, "B": CONFIG_B_SAME_KEY})
    assert out["config_keys"] == []


def test_http_style_routes_are_read_too():
    a = ("+++ b/src/pages/api/x.ts\n@@\n+app.get('/api/health', handler)\n")
    b = ("+++ b/src/pages/api/y.ts\n@@\n+router.get('/api/health', other)\n")
    out = grade({"A": a, "B": b})
    assert out["route_paths"] == [{"path": "GET /api/health", "lanes": ["A", "B"]}]


def test_process_env_reads_count_as_config_keys():
    a = "+++ b/src/a.ts\n@@\n+const x = process.env.FEATURE_FLAG_X\n"
    b = "+++ b/src/b.ts\n@@\n+const y = process.env.FEATURE_FLAG_X\n"
    assert grade({"A": a, "B": b})["config_keys"] == [
        {"key": "FEATURE_FLAG_X", "lanes": ["A", "B"]}]


def test_every_namespace_is_reported_even_when_empty():
    out = grade({"A": "", "B": ""})
    for key in ("migration_ordinals", "route_paths", "config_keys"):
        assert out[key] == [], f"{key} must be present as an empty list"


def test_parse_branch_ignores_context_lines():
    facts = parse_branch("+++ b/src/server/env.ts\n@@\n   EXISTING_KEY: z.string(),\n")
    assert facts.config_keys == set()
