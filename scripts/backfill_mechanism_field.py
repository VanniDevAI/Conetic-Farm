#!/usr/bin/env python3
"""Answer, for every banked episode, whether the claim map named the mechanism.

The distinction the field exists for: the claim map always produces *a* chain
between two patches that touch related code. Sometimes that chain is the reason
the product broke. Sometimes it is a true statement that explains nothing.

CE-007 is the case that forced it. Its recorded chain is
``postRouter -> defaultPostSelect``, which is correct about the two patches and
silent about the mechanism -- two test files racing on one sqlite database.
No analysis of TypeScript identifiers was going to find that.

Curated answers for the CE episodes, because each needs a reading of what the
map actually emitted against what actually broke. The campaign episodes get a
rule: a textual conflict's mechanism *is* overlapping edits, which the
classifier reports, so those are yes; an episode with no failure has no
mechanism to name and gets null.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from farm.episode_record import EPISODES_DIR, SCHEMA_VERSION, write_episode  # noqa: E402

CURATED = {
    "CE-001": (True,
        "the mechanism is two branches rewriting the same function, and the "
        "overlap classifier reports exactly that -- `textual`, same file, "
        "hunks touching. Nothing is hidden here, which is why git also reports "
        "it for free."),
    "CE-002": (True,
        "chain `isStaleByTime -> timeUntilStale`, anchored at "
        "packages/query-core/src/utils.ts:136. That is the provider whose clamp "
        "was removed and the consumer that negates it: the map named the "
        "broken contract and both of its ends."),
    "CE-003": (True,
        "chain `$ZodCheckMultipleOf -> floatSafeRemainder`, anchored at the "
        "changed helper. The consumer tests `=== 0` and the provider stopped "
        "snapping; both ends named."),
    "CE-004": (True,
        "chain `hints.ts::isMultipleOf -> core.util.floatSafeRemainder`, plus "
        "the published-surface attribute that explains why the provider's own "
        "call-site audit could not reach it. This is the episode the map was "
        "designed around and it names the mechanism completely."),
    "CE-005": (True,
        "a textual conflict; the classifier reports `textual` with the "
        "conflicted path, which is the mechanism. The chain it also emitted, "
        "`PostViewPage -> PostItem`, is incidental."),
    "CE-006": (False,
        "NO, and this record previously read as if yes. What the claim map "
        "emitted for this pair is `postRouter -> defaultPostSelect` -- the "
        "enclosing router and a select object. What broke is `post.add`'s input "
        "schema gaining a required `authorId` while another lane wrote call "
        "sites without it. The precise chain stored under `claim.chain` in this "
        "record was written by hand from reading the two patches; the automated "
        "output points at the right file and the wrong thing inside it."),
    "CE-007": (False,
        "the chain is `postRouter -> defaultPostSelect`, a true statement about "
        "two patches that touch the same router. The mechanism is that both "
        "lanes' test files run in parallel vitest workers against one sqlite "
        "file, and lane2's `beforeEach(prisma.post.deleteMany({}))` wipes "
        "lane1's fixtures. The shared thing is a database, not an identifier, "
        "and no static analysis of TypeScript names finds it."),
}


# The episodes a CE record was promoted from are the same episode and must not
# get a generic answer where the CE record got a read one.
ALIASES = {"c06b-pair1-bare": "CE-006", "c07-ep05-roomed": "CE-007"}


def rule(record: dict) -> tuple[bool | None, str]:
    cls = record["failure_class"]
    if cls == "textual":
        return True, ("the mechanism is overlapping edits and the classifier "
                      "reports `textual` with the conflicted paths")
    if cls == "semantic":
        return False, ("a semantic failure whose mechanism has not been read "
                       "against what the map emitted; treated as not named "
                       "until someone does the reading")
    return None, "no failure, so there is no mechanism to name"


def main() -> int:
    apply = "--apply" in sys.argv
    changed = 0
    for path in sorted(EPISODES_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        key = ALIASES.get(rec["id"], rec["id"])
        named, why = CURATED.get(key) or rule(rec)
        current = rec.get("mechanism_named_by_claim_map")
        if current and current.get("named") == named:
            continue
        print(f"{rec['id']:22} named={str(named):5} "
              f"{'(curated)' if key in CURATED else '(rule)'}"
              f"{'' if key == rec['id'] else ' as ' + key}")
        if apply:
            rec["mechanism_named_by_claim_map"] = {
                "named": named, "why": why,
                "source": ("curated" if key in CURATED else "rule")
                          + (f", as {key}" if key != rec["id"] else ""),
            }
            rec["schema_version"] = SCHEMA_VERSION
            write_episode(rec)
        changed += 1
    print(f"{changed} record(s) {'rewritten' if apply else 'would change'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
