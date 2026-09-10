"""The published-surface attribute, checked against the two episodes that set it.

`c05a` ran the same seed twice across a real package boundary and the arms
split on exactly one thing: whether the contract the provider changed was
exported. `timeUntilStale` is not, the provider agent repaired the in-repo
consumer, and the downstream package never noticed. `floatSafeRemainder` is,
the same agent repaired the same way, and the downstream package broke.

So this attribute is load-bearing, and these tests pin it on the two cases
whose answers are known from a run rather than from reading the source.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from farm.surface import build_surface

_CHECKOUTS = {
    "query": (os.environ.get("FARM_QUERY_CHECKOUT"), ["packages/query-core/src/index.ts"]),
    "zod": (os.environ.get("FARM_ZOD_CHECKOUT"), ["packages/zod/src/v4/core/index.ts"]),
}


def _surface(key: str):
    root, entries = _CHECKOUTS[key]
    if not root or not Path(root).is_dir():
        pytest.skip(f"no checkout for {key}; set the env var to enable")
    return build_surface(Path(root), entries)


def test_the_contract_that_did_not_cross_the_seam_is_not_published():
    s = _surface("query")
    assert not s.is_published("timeUntilStale")
    assert s.how("timeUntilStale") is None
    # Sanity: the detector is not simply answering False.
    assert s.is_published("hashKey") and s.how("hashKey") == "named"
    assert s.is_published("Query")


def test_the_contract_that_did_cross_the_seam_is_published_under_a_namespace():
    s = _surface("zod")
    assert s.is_published("floatSafeRemainder")
    assert s.how("floatSafeRemainder") == "namespace util"


def test_a_name_added_by_the_provider_patch_is_not_published_until_it_is_exported():
    """`multipleOfTolerance` is exported from util.ts but util is namespaced.

    It reaches the surface the same way `floatSafeRemainder` does, so it is
    absent only because the base commit does not define it yet -- which is what
    makes it a useful negative: the detector reads the tree it is given.
    """
    s = _surface("zod")
    assert not s.is_published("multipleOfTolerance")


def test_star_export_republishes_a_whole_module(tmp_path: Path):
    (tmp_path / "util.ts").write_text("export function alpha() {}\nfunction hidden() {}\n")
    (tmp_path / "index.ts").write_text("export * from './util'\nexport const beta = 1\n")
    s = build_surface(tmp_path, ["index.ts"])
    assert s.is_published("alpha") and s.is_published("beta")
    assert not s.is_published("hidden")


def test_namespace_export_records_how_the_name_got_out(tmp_path: Path):
    (tmp_path / "u.ts").write_text("export const gamma = 1\n")
    (tmp_path / "index.ts").write_text("export * as u from './u.js'\n")
    s = build_surface(tmp_path, ["index.ts"])
    assert s.is_published("gamma")
    assert s.how("gamma") == "namespace u"


def test_a_renamed_export_is_published_under_its_new_name(tmp_path: Path):
    (tmp_path / "a.ts").write_text("export function inner() {}\n")
    (tmp_path / "index.ts").write_text("export { inner as outer } from './a'\n")
    s = build_surface(tmp_path, ["index.ts"])
    assert s.is_published("outer")


def test_a_cycle_between_entry_files_terminates(tmp_path: Path):
    (tmp_path / "a.ts").write_text("export * from './b'\nexport const one = 1\n")
    (tmp_path / "b.ts").write_text("export * from './a'\nexport const two = 2\n")
    s = build_surface(tmp_path, ["a.ts"])
    assert s.is_published("one") and s.is_published("two")


def test_a_bare_specifier_is_not_followed(tmp_path: Path):
    (tmp_path / "index.ts").write_text(
        textwrap.dedent("""
        export * from 'some-other-package'
        export const mine = 1
        """))
    s = build_surface(tmp_path, ["index.ts"])
    assert s.is_published("mine")
    assert len(s.published) == 1
