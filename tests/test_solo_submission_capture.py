"""A solo lane that never published still did the work, and it must be graded.

CooperBench grades what an agent **published** -- a PR tag, or failing that a
pushed branch. In coop that rule is the whole point: the artifact is what a
colleague could read, so an agent cannot submit from a local file nobody saw.

In a solo lane there is no colleague and no channel, and the same rule stops
measuring integration. It measures whether the model remembered to commit.

c06 paid for that distinction. Both lanes of ``c06-pair1-roomed`` wrote the
feature, ran ``npx vitest run`` green and ``npx tsc --noEmit`` clean, and then
wrote a prose summary instead of running a single git command -- 68 steps and
20 steps, zero commits between them. Both exited ``Submitted`` with a zero-byte
patch. The episode recorded ``lanes_present: []`` while two working
implementations sat in its containers, and the arm it belonged to read as
having shipped nothing.

So: when a solo lane publishes nothing, its working tree is diffed against the
task's base commit and that is graded, marked as salvaged rather than
published. Coop keeps the published-only rule unchanged.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

COOPERBENCH = Path(os.getenv("FARM_COOPERBENCH_DIR", "/home/user/work/CooperBench"))
ADAPTER = COOPERBENCH / "src/cooperbench/agents/mini_swe_agent_v2/adapter.py"
CONNECTOR = COOPERBENCH / "src/cooperbench/agents/mini_swe_agent_v2/connectors/git.py"
SOLO = COOPERBENCH / "src/cooperbench/runner/solo.py"

pytestmark = pytest.mark.skipif(not ADAPTER.exists(),
                                reason="CooperBench checkout unavailable")


def _src(p: Path) -> str:
    return p.read_text()


def test_the_connector_can_read_a_working_tree_against_the_base_commit():
    src = _src(CONNECTOR)
    assert "def working_tree_patch" in src
    fn = src[src.index("def working_tree_patch"):]
    fn = fn[:fn.index("\n    def ", 1)] if "\n    def " in fn[1:] else fn
    assert "git add -A" in fn, "untracked files are most of a new router's work"
    assert "self._base_sha" in fn, "the diff is against the task's base, not HEAD"


def test_the_fallback_runs_only_for_a_solo_lane():
    """Coop's published-only rule is not weakened by this."""
    src = _src(ADAPTER)
    assert "working_tree_patch" in src
    line = next(l for l in src.splitlines() if "working_tree_patch" in l and "git_connector" in l)
    block = src[:src.index(line)]
    guard = block.rsplit("if ", 1)[1].splitlines()[0]
    assert "not is_coop" in guard, f"the fallback must be gated on solo, found: {guard!r}"
    assert "not patch.strip()" in guard, "a published patch must never be replaced"


def test_the_fallback_reads_the_container_before_it_is_destroyed():
    """`env.cleanup()` is what makes this a one-shot: after it there is nothing to read."""
    lines = _src(ADAPTER).splitlines()
    # Line numbers, not string offsets: the comment above the fallback names
    # `env.cleanup()` too, and matching that would pass whatever the order.
    fallback = next(i for i, l in enumerate(lines) if "git_connector.working_tree_patch" in l)
    cleanup = next(i for i, l in enumerate(lines) if l.strip() == "env.cleanup()")
    assert fallback < cleanup


def test_a_salvaged_patch_is_recorded_as_salvaged_not_as_published():
    assert "patch_salvaged" in _src(ADAPTER)
    assert "patch_salvaged" in _src(SOLO), "result.json must say which it was"
    agents_init = COOPERBENCH / "src/cooperbench/agents/__init__.py"
    tree = ast.parse(agents_init.read_text())
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "AgentResult")
    fields = [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)]
    assert "patch_salvaged" in fields
