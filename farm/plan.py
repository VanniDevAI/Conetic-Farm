"""Task-plan construction: choose the 20 pairs before any agent runs.

Selection is deterministic (seeded), stratified, and frozen to
``config/task_plan.json`` *before* the campaign starts.  Nothing about a result
can feed back into which tasks were chosen.

Strata come from CooperBench's own ``dataset/gold_conflict_report.json``, which
records, for every one of the 652 feature pairs, whether the two **gold** patches
merge cleanly.  Two corrections are applied to that file before it is trusted:

1. A pair where a gold patch failed to apply at all
   (``patch1_apply_failed`` / ``patch2_apply_failed``) carries no usable signal.
   Six pairs in the dataset are labelled ``has_conflict: false`` purely because
   one patch never applied — they are *not* clean merges.  Those are excluded.
2. ``has_conflict`` is a *textual* property of the gold patches.  It predicts a
   merge conflict; it does not predict a semantic integration failure, and it
   says nothing about what the agents will actually write.  It is used to
   stratify, never as ground truth for an outcome.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Literal

Stratum = Literal["compatible", "conflicting", "control"]

# Repositories by language, from the dataset's own directory names.
LANGUAGE_BY_REPO = {
    "dottxt_ai_outlines_task": "python",
    "dspy_task": "python",
    "go_chi_task": "go",
    "huggingface_datasets_task": "python",
    "llama_index_task": "python",
    "openai_tiktoken_task": "python",
    "pallets_click_task": "python",
    "pallets_jinja_task": "python",
    "pillow_task": "python",
    "react_hook_form_task": "typescript",
    "samuelcolvin_dirty_equals_task": "python",
    "typst_task": "rust",
}


@dataclass(frozen=True)
class Pair:
    repo: str
    task_id: int
    f1: int
    f2: int
    has_conflict: bool
    patch1_apply_failed: bool
    patch2_apply_failed: bool

    @property
    def language(self) -> str:
        return LANGUAGE_BY_REPO.get(self.repo, "unknown")

    @property
    def usable(self) -> bool:
        """A pair whose gold patches both apply.  Others carry no signal."""
        return not (self.patch1_apply_failed or self.patch2_apply_failed)

    @property
    def key(self) -> str:
        return f"{self.repo}/task{self.task_id}/f{self.f1}-f{self.f2}"

    @property
    def episode_id(self) -> str:
        h = hashlib.sha256(self.key.encode()).hexdigest()[:8]
        return f"{self.repo}__task{self.task_id}__f{self.f1}_f{self.f2}__{h}"


@dataclass(frozen=True)
class PlannedEpisode:
    episode_id: str
    repo: str
    task_id: int
    f1: int
    f2: int
    language: str
    stratum: Stratum
    gold_has_conflict: bool
    order: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_pairs(gold_conflict_report: Path) -> list[Pair]:
    data = json.loads(Path(gold_conflict_report).read_text())
    return [
        Pair(
            repo=r["repo"], task_id=int(r["task_id"]),
            f1=int(r["f1"]), f2=int(r["f2"]),
            has_conflict=bool(r["has_conflict"]),
            patch1_apply_failed=bool(r.get("patch1_apply_failed", False)),
            patch2_apply_failed=bool(r.get("patch2_apply_failed", False)),
        )
        for r in data["all_results"]
    ]


def stratify(pairs: Iterable[Pair]) -> dict[str, list[Pair]]:
    """Split usable pairs into conflicting / compatible buckets.

    ``control`` is not a property of the gold report: it is a deliberately
    chosen subset of ``compatible`` pairs whose features are in different
    modules.  ``build_plan`` draws controls from the compatible bucket and
    labels them; the caller supplies the module-disjointness check.
    """
    buckets: dict[str, list[Pair]] = {"conflicting": [], "compatible": [],
                                      "excluded_apply_failed": []}
    for p in pairs:
        if not p.usable:
            buckets["excluded_apply_failed"].append(p)
        elif p.has_conflict:
            buckets["conflicting"].append(p)
        else:
            buckets["compatible"].append(p)
    return buckets


def build_plan(
    pairs: list[Pair],
    *,
    n_conflicting: int,
    n_compatible: int,
    n_control: int,
    seed: int = 42,
    languages: set[str] | None = None,
    control_pairs: list[Pair] | None = None,
    language_floor: dict[str, int] | None = None,
) -> list[PlannedEpisode]:
    """Deterministically select and order the campaign's episodes.

    ``control_pairs`` is an explicit, hand-checked list of pairs whose features
    touch disjoint modules.  Controls are never sampled blindly: "no conflict is
    expected" is a claim about the code, and it has to be made deliberately.
    """
    if languages:
        pairs = [p for p in pairs if p.language in languages]
    buckets = stratify(pairs)
    rng = random.Random(seed)

    def take(bucket: list[Pair], n: int, exclude: set[str]) -> list[Pair]:
        avail = sorted((p for p in bucket if p.key not in exclude), key=lambda p: p.key)
        if len(avail) < n:
            raise ValueError(
                f"need {n} pairs but only {len(avail)} available after exclusions"
            )
        return rng.sample(avail, n)

    chosen: list[tuple[Pair, Stratum]] = []
    used: set[str] = set()

    # A language floor keeps a small slice represented.  The TypeScript slice is
    # 25 pairs across 2 tasks, so uniform sampling from 499 conflicting pairs
    # draws it only about 40% of the time -- and the brief starts from
    # TypeScript.  The floor is applied to the conflicting stratum because that
    # is the only stratum TypeScript can supply: it has no genuinely clean pairs.
    floor = dict(language_floor or {})

    if n_control:
        if not control_pairs:
            raise ValueError(
                "n_control > 0 requires an explicit control_pairs list; controls "
                "must be chosen by inspecting the features, not sampled"
            )
        ctrl = take(list(control_pairs), n_control, used)
        for p in ctrl:
            chosen.append((p, "control"))
            used.add(p.key)

    remaining_conflicting = n_conflicting
    for lang, floor_n in sorted(floor.items()):
        pool = [p for p in buckets["conflicting"] if p.language == lang]
        want = min(floor_n, remaining_conflicting)
        if want <= 0:
            continue
        if len(pool) < want:
            raise ValueError(
                f"language floor asks for {want} conflicting {lang} pairs but "
                f"only {len(pool)} exist"
            )
        for p in take(pool, want, used):
            chosen.append((p, "conflicting"))
            used.add(p.key)
        remaining_conflicting -= want

    for p in take(buckets["conflicting"], remaining_conflicting, used):
        chosen.append((p, "conflicting"))
        used.add(p.key)
    for p in take(buckets["compatible"], n_compatible, used):
        chosen.append((p, "compatible"))
        used.add(p.key)

    # Interleave strata so an early abort still leaves a balanced sample.
    by_stratum: dict[str, list[tuple[Pair, Stratum]]] = {}
    for item in chosen:
        by_stratum.setdefault(item[1], []).append(item)
    for v in by_stratum.values():
        rng.shuffle(v)
    ordered: list[tuple[Pair, Stratum]] = []
    while any(by_stratum.values()):
        for s in ("conflicting", "compatible", "control"):
            if by_stratum.get(s):
                ordered.append(by_stratum[s].pop())

    return [
        PlannedEpisode(
            episode_id=p.episode_id, repo=p.repo, task_id=p.task_id,
            f1=p.f1, f2=p.f2, language=p.language, stratum=s,
            gold_has_conflict=p.has_conflict, order=i + 1,
        )
        for i, (p, s) in enumerate(ordered)
    ]
