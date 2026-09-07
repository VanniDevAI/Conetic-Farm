"""Episode manifest: the record a replayer reads instead of this repository.

Two levels:

* **Episode manifest** — ``<episode>/manifest.json``.  Self-contained: it names
  every artifact by path, size and SHA-256, so a replayer can verify integrity
  and reconstruct the run without any part of this repo.
* **Campaign index** — ``$FARM_DATA_ROOT/manifest.json``, one entry per episode.
  A copy with paths and digests but no payload is committed to this repo at
  ``reports/manifest.json``.

The schema deliberately contains nothing Conetic-specific.  It describes what
happened; it does not describe what anyone will do with it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "conetic-farm/episode-manifest/1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, _chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_chunk):
            h.update(chunk)
    return h.hexdigest()


def describe(path: Path, root: Path | None = None) -> dict[str, Any] | None:
    """Path, size and digest for one artifact.  ``None`` when it is absent.

    Absence is recorded as ``null`` rather than omitted, so a consumer can tell
    "this run had no merged diff" from "this manifest predates the field".
    """
    if not path.exists() or not path.is_file():
        return None
    return {
        "path": str(path),
        "relpath": str(path.relative_to(root)) if root else None,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def describe_dir(path: Path, root: Path | None = None) -> dict[str, Any] | None:
    if not path.exists() or not path.is_dir():
        return None
    files, total = 0, 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            total += p.stat().st_size
    return {
        "path": str(path),
        "relpath": str(path.relative_to(root)) if root else None,
        "files": files,
        "bytes": total,
    }


@dataclass
class AgentManifest:
    role: str                      # "A" | "B"
    feature_id: int
    model: str
    adapter: str
    adapter_profile: dict[str, Any] = field(default_factory=dict)
    exit_status: str = "unknown"
    wallclock_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    cost_source: str = ""
    patch: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    raw_outputs: dict[str, Any] | None = None
    # Intermediate source checkpoints.  Deliberately a sibling of `patch`,
    # never nested inside it: process data and deliverable are different things.
    checkpoints: dict[str, Any] | None = None


@dataclass
class EpisodeManifest:
    schema: str = SCHEMA_VERSION
    episode_id: str = ""
    campaign: str = ""
    created_at: str = field(default_factory=_utcnow)

    # what was run
    repo: str = ""
    task_id: int = 0
    features: tuple[int, int] = (0, 0)
    language: str = ""
    stratum: str = ""
    gold_has_conflict: bool | None = None

    # where it lives
    data_root: str = ""
    episode_dir: str = ""

    # how it was run
    harness: dict[str, Any] = field(default_factory=dict)
    base: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)

    # what came out
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["features"] = list(self.features)
        return d

    def write(self, path: Path | None = None) -> Path:
        target = path or Path(self.episode_dir) / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str))
        os.replace(tmp, target)   # atomic: a reader never sees a half-written manifest
        return target


def build_attempt_entry(
    attempt_dir: Path,
    *,
    attempt_id: str,
    status: str,
    disposition: str,
    disposition_reason: str,
    started_at: str,
    finished_at: str,
    agents: list[AgentManifest],
    classification: dict[str, Any] | None,
    cost_usd: float,
    root: Path | None = None,
) -> dict[str, Any]:
    """One attempt's slice of the manifest, with every artifact digested."""
    results = attempt_dir / "results"
    merge = attempt_dir / "merge"
    return {
        "attempt_id": attempt_id,
        "status": status,
        # `counted` vs `discarded`.  Discarded attempts stay on disk and stay in
        # the manifest; they are only excluded from headline rates, and the
        # exclusion is always reported with its count.
        "disposition": disposition,
        "disposition_reason": disposition_reason,
        "started_at": started_at,
        "finished_at": finished_at,
        "dir": str(attempt_dir),
        "cost_usd": round(cost_usd, 6),
        "agents": [asdict(a) for a in agents],
        "merge": {
            "report": describe(merge / "merge.json", root),
            "merged_diff": describe(merge / "merged.diff", root),
            "conflict": describe(merge / "conflict.txt", root),
        },
        "results": {
            "a_alone": describe(results / "a_alone.json", root),
            "b_alone": describe(results / "b_alone.json", root),
            "merged": describe(results / "merged.json", root),
            "classification": describe(results / "classification.json", root),
            "cooperbench_eval": describe(results / "cooperbench_eval.json", root),
        },
        "classification": classification,
    }


class CampaignIndex:
    """Append-only index of episodes across a campaign."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict[str, Any]] = []
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text()).get("episodes", [])
            except (json.JSONDecodeError, OSError):
                self.entries = []

    def upsert(self, manifest: EpisodeManifest) -> None:
        entry = {
            "episode_id": manifest.episode_id,
            "campaign": manifest.campaign,
            "repo": manifest.repo,
            "task_id": manifest.task_id,
            "features": list(manifest.features),
            "language": manifest.language,
            "stratum": manifest.stratum,
            "gold_has_conflict": manifest.gold_has_conflict,
            "episode_dir": manifest.episode_dir,
            "manifest_path": str(Path(manifest.episode_dir) / "manifest.json"),
            "attempts": [
                {
                    "attempt_id": a["attempt_id"],
                    "status": a["status"],
                    "disposition": a["disposition"],
                    "label": (a.get("classification") or {}).get("label"),
                    "cost_usd": a.get("cost_usd"),
                    "dir": a.get("dir"),
                }
                for a in manifest.attempts
            ],
        }
        self.entries = [e for e in self.entries
                        if e["episode_id"] != manifest.episode_id] + [entry]
        self.entries.sort(key=lambda e: e["episode_id"])

    def write(self, *, redact_paths: bool = False) -> Path:
        payload = {
            "schema": "conetic-farm/campaign-index/1",
            "generated_at": _utcnow(),
            "episode_count": len(self.entries),
            "episodes": self.entries,
        }
        if redact_paths:
            payload["note"] = (
                "Committed copy: episode payloads live outside this repository "
                "under FARM_DATA_ROOT; only paths and digests are recorded here."
            )
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        os.replace(tmp, self.path)
        return self.path
