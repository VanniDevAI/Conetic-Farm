"""What kind of failure an episode had, decided in one place.

Two classes, and the boundary between them is the whole point:

* ``textual``   the three-way merge refuses. Git sees it, any merge tool sees
                it, the combined tests never run.
* ``semantic``  the merge is clean and the *combined* tests fail. The patches
                are textually compatible and behaviourally incompatible, which
                is precisely the gap a claim map exists to close.

And a third case that is neither, which this module exists to stop being
counted as the second.

**A clean merge with a failing combined suite is only an integration failure if
every lane was green on its own branch.** If a lane was already red, the
combined tree fails for that lane's own reason and the merge had nothing to do
with it. Calling that ``semantic`` counts a broken branch as evidence that two
correct branches disagreed, which is the opposite of what the label claims.

c06b found this the expensive way. Two of its episodes merged cleanly with a
failing combined suite. In one, both lanes were green alone and the failure was
real: lane1 made ``authorId`` required in ``post.add``, lane2 added call sites
without it, and the merged tree raised ``ZodError``. In the other, lane2's own
``author.test.ts`` was already failing on its own branch and simply went on
failing after the merge. The first is the class. The second is a broken lane.
"""

from __future__ import annotations

TEXTUAL = "textual"
SEMANTIC = "semantic"


def classify(merge_outcome: str | None, merged_suite: str | None,
             every_lane_green: bool) -> tuple[str | None, str]:
    """Return ``(class, why)``; ``class`` is None when this is not one.

    ``every_lane_green`` must mean *every lane of the episode ran alone and
    passed* -- not "the lanes we managed to grade passed". An episode missing a
    lane cannot support either class.
    """
    if merge_outcome == "conflict":
        return TEXTUAL, "git refuses the merge"
    if merge_outcome != "clean":
        return None, ("no merge was attempted; fewer than two lanes produced a "
                      "patch")
    if merged_suite == "fail":
        if every_lane_green:
            return SEMANTIC, ("the merge is clean, every lane is green on its "
                              "own branch, and the combined tree is broken")
        return None, ("the merge is clean and the combined tree is broken, but "
                      "a lane is red on its own branch: the combined failure is "
                      "that lane's own defect, not an interaction between them")
    if merged_suite == "pass":
        return None, "the merge is clean and the combined tree passes"
    return None, "the merge is clean; the combined suite was not run"


def stealth(failure_class: str | None, merge_outcome: str | None,
            every_lane_green: bool) -> dict:
    """The stealth flag, which only the semantic class can carry.

    Stealth means nothing anyone runs would have caught it: the merge is clean,
    every branch's own suite is green, and the product is wrong anyway. A
    refused merge is the loudest signal there is and is never stealthy.
    """
    if merge_outcome != "clean":
        return {"flag": None, "measured": True,
                "why": "not applicable: the merge is not clean"}
    if failure_class == SEMANTIC:
        return {"flag": True, "measured": True,
                "why": "clean merge, every lane green alone, combined tree wrong"}
    if every_lane_green:
        return {"flag": None, "measured": True,
                "why": "not applicable: the combined tree is not broken"}
    return {"flag": False, "measured": True,
            "why": ("a lane is red on its own branch, so it was catchable "
                    "before any merge")}
