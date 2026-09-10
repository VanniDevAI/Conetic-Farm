"""The durable form of a coordination episode.

Everything the Farm has learned so far lives in prose reports and in per-run
artifact trees that are named differently in every campaign. That is fine for
reading and useless for counting: there is no way to ask "how many semantic
episodes were stealthy" without re-reading four documents.

This module fixes the shape. One JSON record per episode under
``farm/episodes/<id>.json``, one line per episode appended to
``farm/episodes/index.jsonl``, and a schema that every campaign writes the same
way. The record is the artifact of record; the prose reports become commentary
on it rather than the only place a number exists.

Two fields carry the weight and are required even when empty:

``prediction``  what was expected *before* the episode ran, and what was
                observed. A prediction written afterwards is not a prediction,
                so the frozen text is stored with the plan path it came from.
``split``       ``gold`` for episodes a human has verified, ``observed`` for
                ones that happened but are not settled, ``train`` for
                everything else. A campaign writes ``train`` and only a human
                verdict moves a record.

``mechanism_named_by_claim_map``
                whether the claim map's own output identified *why the product
                broke*, as against merely relating the two patches. The
                distinction earns its own field because it is the one that
                decides whether the engine is useful: CE-007's chain,
                ``postRouter -> defaultPostSelect``, is a true statement about
                two patches that says nothing about two test files racing on
                one sqlite database. ``named`` is true, false, or null when
                there was no failure to explain, and ``why`` is required in
                every case -- a yes or no with no reason is an assertion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3

EPISODES_DIR = Path(__file__).resolve().parent / "episodes"
INDEX_PATH = EPISODES_DIR / "index.jsonl"

CLASSES = {"textual", "semantic", None}
# ``gold``     a human has verified it and it may carry an argument.
# ``observed``  it happened and is recorded faithfully, but something about it
#               is not settled -- CE-007 is a race and may not reproduce -- so
#               it must not be counted as if it were.
# ``train``     everything else.
SPLITS = {"gold", "observed", "train"}

# Every key is required. A missing measurement is recorded as null with a
# reason next to it, never left out -- an absent key reads as "not applicable"
# and a null reads as "looked for and not found", and only the second is
# usually true.
REQUIRED = (
    "schema_version", "id", "split", "corpus", "seam", "lanes",
    "git_outcome", "product_outcome", "failure_class", "stealth",
    "claim", "convention_graders", "published_surface", "cost",
    "prediction", "patches", "merge", "test_logs", "checkpoints",
    "mechanism_named_by_claim_map",
)

LANE_REQUIRED = ("agent", "model", "runtime", "brief", "assumptions")


class EpisodeSchemaError(ValueError):
    pass


def validate(record: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED if k not in record]
    if missing:
        raise EpisodeSchemaError(f"episode {record.get('id')!r} missing: {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise EpisodeSchemaError(
            f"episode {record['id']!r} is schema {record['schema_version']}, "
            f"this module writes {SCHEMA_VERSION}")
    if record["split"] not in SPLITS:
        raise EpisodeSchemaError(f"split must be one of {sorted(SPLITS)}")
    if record["failure_class"] not in CLASSES:
        raise EpisodeSchemaError(
            f"failure_class must be one of {sorted(c or 'null' for c in CLASSES)}")
    if not isinstance(record["lanes"], list) or not record["lanes"]:
        raise EpisodeSchemaError("lanes must be a non-empty list")
    for i, lane in enumerate(record["lanes"]):
        lane_missing = [k for k in LANE_REQUIRED if k not in lane]
        if lane_missing:
            raise EpisodeSchemaError(f"lane {i} of {record['id']!r} missing: {lane_missing}")
    m = record["mechanism_named_by_claim_map"]
    if not isinstance(m, dict) or "named" not in m or "why" not in m:
        raise EpisodeSchemaError(
            f"{record['id']!r}: mechanism_named_by_claim_map needs "
            f"{{named, why}}")
    if m["named"] not in (True, False, None):
        raise EpisodeSchemaError(
            f"{record['id']!r}: mechanism_named_by_claim_map.named must be "
            f"true, false or null")
    if not m["why"]:
        raise EpisodeSchemaError(
            f"{record['id']!r}: a yes or no with no reason is an assertion, "
            f"not a record")
    pred = record["prediction"]
    for key in ("frozen", "observed", "correct", "source"):
        if key not in pred:
            raise EpisodeSchemaError(f"prediction of {record['id']!r} missing {key!r}")


def index_line(record: dict[str, Any]) -> dict[str, Any]:
    """The one-line summary. Deliberately small: the record holds the detail."""
    return {
        "id": record["id"],
        "split": record["split"],
        "corpus": record["corpus"].get("name"),
        "failure_class": record["failure_class"],
        "stealth": record["stealth"].get("flag"),
        "published_surface": record["published_surface"].get("published"),
        "convention_hits": sum(len(v) for v in record["convention_graders"].values()
                               if isinstance(v, list)),
        "mechanism_named": record["mechanism_named_by_claim_map"]["named"],
        "cost_usd": record["cost"].get("usd"),
        "prediction_correct": record["prediction"].get("correct"),
        "record": f"farm/episodes/{record['id']}.json",
    }


def write_episode(record: dict[str, Any], *, episodes_dir: Path | None = None) -> Path:
    """Write one record and append its index line.

    Rewriting an existing record is allowed -- a re-grade should correct the
    file. The index is append-only, so a rewrite appends a second line and the
    history of what was believed when stays readable. Readers take the last
    line for an id.
    """
    validate(record)
    directory = Path(episodes_dir) if episodes_dir else EPISODES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record['id']}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=False) + "\n")
    with (directory / "index.jsonl").open("a") as fh:
        fh.write(json.dumps(index_line(record), sort_keys=True) + "\n")
    return path


def load_index(*, episodes_dir: Path | None = None) -> dict[str, dict]:
    """The current view: the last line wins for each id."""
    directory = Path(episodes_dir) if episodes_dir else EPISODES_DIR
    index = directory / "index.jsonl"
    if not index.exists():
        return {}
    out: dict[str, dict] = {}
    for line in index.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        out[row["id"]] = row
    return out


def load_episode(episode_id: str, *, episodes_dir: Path | None = None) -> dict:
    directory = Path(episodes_dir) if episodes_dir else EPISODES_DIR
    return json.loads((directory / f"{episode_id}.json").read_text())
