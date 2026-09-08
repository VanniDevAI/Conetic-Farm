"""The guard must make room for the build it is about to run, not for 12 GB.

Measured in `c03`, episode 5.  The guard checked free space, saw 19.3 GB, and
returned without reclaiming -- correct by its own rule.  Then
`dottxt_ai_outlines/1655`, whose image carries jax and jaxlib, exhausted the
disk mid-`docker build`:

    failed to extract layer sha256:7f7ca... write .../jaxlib/libjax_common.so:
    no space left on device

The episode was recorded as a harness error.  It is not one: that image built
without trouble in `c02`.  A false harness error is worse than a slow campaign,
because it lands in the denominator the report divides by and there is nothing
in the artifact that says it was the instrument's fault rather than the task's.

The rule was wrong in two ways at once:

* it reclaimed only *below* a threshold, so images accumulated up to it -- by
  episode 5 four task images (27 GB with the base) were resident and none was
  in use;
* the threshold was a constant, but the thing that has to fit is the next
  build, and the largest of these needs more headroom than 12 GB.

So: reclaim before every episode, and keep exactly the image the upcoming
episode needs.  Consecutive episodes usually share one (the plan runs
`react_hook_form/153` three times in a row), so this costs no rebuild in the
common case and bounds resident images at one plus the base.
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
    "redis:7",
]


def test_the_image_the_next_episode_needs_is_kept() -> None:
    got = reclaimable_images(LISTED, BASE, keep={"akhatua/cooperbench-typst:task6554"})
    assert "akhatua/cooperbench-typst:task6554" not in got, (
        "the guard deleted the image the very next episode is about to use, "
        "paying a full rebuild for nothing")
    assert "akhatua/cooperbench-pallets-jinja:task1465" in got


def test_keeping_one_image_does_not_keep_its_siblings() -> None:
    """The two tags of one task image are the same image; a *different* task's
    tags are not, and holding them is what filled the disk."""
    got = reclaimable_images(LISTED, BASE, keep={"akhatua/cooperbench-typst:task6554"})
    assert "conetic-farm/task-pallets_jinja_task-1465:local" in got


def test_the_base_is_still_never_reclaimed_even_if_asked_to_keep_nothing() -> None:
    assert BASE not in reclaimable_images(LISTED, BASE, keep=set())


def test_keep_defaults_to_nothing_so_existing_callers_are_unchanged() -> None:
    assert len(reclaimable_images(LISTED, BASE)) == 4


# --- which tags belong to the episode about to run --------------------------

from farm.run import tags_for_task


def test_both_tags_of_the_upcoming_task_are_recognised() -> None:
    """A task image carries two tags: ours and the one CooperBench resolves.
    They are the same image, and keeping only one of them would not save it."""
    got = tags_for_task(LISTED + [
        "conetic-farm/task-pallets_jinja_task-1621:local",
        "akhatua/cooperbench-pallets-jinja:task1621",
    ], "pallets_jinja_task", 1621)
    assert got == {"conetic-farm/task-pallets_jinja_task-1621:local",
                   "akhatua/cooperbench-pallets-jinja:task1621"}, got


def test_a_task_id_that_is_a_prefix_of_another_does_not_match() -> None:
    """`153` must not keep `1530`'s image alive, or the guard frees nothing."""
    listed = ["akhatua/cooperbench-react-hook-form:task153",
              "akhatua/cooperbench-react-hook-form:task1530",
              "conetic-farm/task-react_hook_form_task-1530:local"]
    got = tags_for_task(listed, "react_hook_form_task", 153)
    assert got == {"akhatua/cooperbench-react-hook-form:task153"}, got


def test_a_different_repo_with_the_same_id_is_not_kept() -> None:
    listed = ["akhatua/cooperbench-typst:task25",
              "akhatua/cooperbench-pillow:task25"]
    assert tags_for_task(listed, "pillow_task", 25) == {
        "akhatua/cooperbench-pillow:task25"}


def test_nothing_matching_is_an_empty_set_not_an_error() -> None:
    assert tags_for_task([], "dspy_task", 8563) == set()
