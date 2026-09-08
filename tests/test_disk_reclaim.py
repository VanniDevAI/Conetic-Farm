"""The disk guard must never delete the base image.

Two wrong versions shipped before this test existed.  `image prune -f` removed
only dangling images and freed nothing, so the guard fired correctly and the
campaign still hit ENOSPC.  `image prune -af` then removed everything no
container was using -- which between builds includes the base image -- and the
next eight episodes died with "base image missing".
"""

from __future__ import annotations

from farm.run import reclaimable_images

BASE = "conetic-farm/node22-base:local"

LISTED = [
    BASE,
    "akhatua/cooperbench-pallets-jinja:task1465",
    "conetic-farm/task-pallets_jinja_task-1465:local",
    "akhatua/cooperbench-typst:task6554",
    "conetic-farm/task-typst_task-6554:local",
    "<none>:<none>",
    "redis:7",
]


def test_the_base_image_is_never_reclaimed() -> None:
    assert BASE not in reclaimable_images(LISTED, BASE)


def test_task_images_are_reclaimed() -> None:
    got = reclaimable_images(LISTED, BASE)
    assert "akhatua/cooperbench-typst:task6554" in got
    assert "conetic-farm/task-pallets_jinja_task-1465:local" in got
    assert len(got) == 4


def test_unrelated_images_are_left_alone() -> None:
    """Deleting something we did not create is not ours to do."""
    got = reclaimable_images(LISTED, BASE)
    assert "redis:7" not in got
    assert "<none>:<none>" not in got


def test_a_renamed_base_is_still_protected() -> None:
    alt = "my-org/custom-base:v2"
    listed = [alt, "conetic-farm/task-x-1:local"]
    got = reclaimable_images(listed, alt)
    assert alt not in got and got == ["conetic-farm/task-x-1:local"]


def test_nothing_to_reclaim_is_not_an_error() -> None:
    assert reclaimable_images([BASE], BASE) == []
