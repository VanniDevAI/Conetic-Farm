"""Publish each finished episode into the repository, before the next one starts.

Why this exists: the campaign runs in an ephemeral container.  Episode data
lives at ``$FARM_DATA_ROOT``, outside the repository and outside git, exactly as
``docs/DESIGN.md`` intends -- but a container reclaim takes that directory with
it.  Everything spent on an episode is then gone, and spend is the one thing a
re-run cannot recover.  So each completed episode is archived into the repo and
pushed before the next episode begins.

Three properties this module is responsible for:

* **No credential ever reaches git.**  Agent transcripts are model output and
  harness logs; nothing guarantees they are clean.  Every file that goes into an
  archive is scanned for credential shapes first, and a hit aborts the publish
  rather than redacting silently -- a redaction would hide that a key leaked
  into a transcript at all, which is itself something to know about.

* **The archive stays a sane size.**  ``base/base.bundle`` is a full clone of the
  upstream repository under test; it is large, identical across attempts, and
  reconstructible from the pinned commit that sits beside it.  It is never
  archived.  If an episode is still oversize after that, optional components are
  dropped largest-first and *recorded* in the archive's summary -- a silent
  truncation would read as "we kept everything" when we did not.

* **A failed push never silently loses an episode.**  The push is retried with
  backoff; if it still fails the caller is told, so the campaign can stop rather
  than run 19 more episodes into a container that cannot save them.
"""

from __future__ import annotations

import json
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from farm.env import KEY_SHAPE

# Never archived: a full clone of the upstream repo, reconstructible from
# base/base_commit.txt plus the pinned dataset.  Keeping it would add hundreds of
# megabytes per episode for nothing.
ALWAYS_EXCLUDE = {"base.bundle"}

# Dropped only if the archive is otherwise too large, largest-first.  These are
# process data: valuable, but not the evidence a label rests on.
# NB: farm/episode.py copies the harness output into `raw/` while leaving the
# originals under `harness_logs/`, so the two are near-duplicates.  Dropping only
# `raw` therefore frees almost nothing, which made the size cap unenforceable.
OPTIONAL_DIRS = ("checkpoints_raw", "harness_logs", "raw")

# A single git object this large is refused by most remotes and is a bad idea in
# any case.  Well under GitHub's hard 100 MB limit.
MAX_ARCHIVE_BYTES = 60 * 1024 * 1024

# Everything is scanned.  An earlier version used an extension allowlist, which
# was worse than useless: it silently skipped `checkpoints.bundle` while this
# module's own docstring claimed bundles were covered.  An allowlist cannot be
# right here -- the set of extensions an episode contains is decided by the
# harness and the repo under test, not by this file.
#
# Honest limit, since the previous version overstated this one: a git bundle
# stores most content zlib-deflated, so a credential inside a *committed blob*
# will not appear in a byte scan.  Scanning catches it in loose regions (refs,
# names, headers) and in every plain file, which is where a leaked key from a
# transcript or a log actually lands.  It is not a proof of absence for
# compressed content, and this module no longer pretends otherwise.
MAX_SCAN_BYTES = 256 * 1024 * 1024


@dataclass
class PublishResult:
    episode_id: str
    archive: Path | None = None
    archive_bytes: int = 0
    dropped: list[str] = field(default_factory=list)
    pushed: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"episode_id": self.episode_id,
                "archive": str(self.archive) if self.archive else None,
                "archive_bytes": self.archive_bytes,
                "dropped_components": self.dropped,
                "pushed": self.pushed,
                "error": self.error}


class CredentialInArtifact(Exception):
    """A credential shape was found in something about to be committed."""


class ArchiveTooLarge(Exception):
    """The archive would not fit, even after dropping every optional part."""


def scan_for_credentials(root: Path) -> list[str]:
    """Return repo-relative paths of files containing a credential shape.

    Read as bytes and decoded leniently: a transcript can carry invalid UTF-8
    from a truncated tool output, and failing to scan it is not an option.
    """
    hits: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink() or p.name in ALWAYS_EXCLUDE:
            continue
        try:
            if p.stat().st_size > MAX_SCAN_BYTES:
                hits.append(f"{p.relative_to(root)} (UNSCANNED: too large)")
                continue
            text = p.read_bytes().decode("utf-8", "replace")
        except OSError:
            hits.append(f"{p.relative_to(root)} (UNSCANNED: unreadable)")
            continue
        if KEY_SHAPE.search(text):
            hits.append(str(p.relative_to(root)))
    return hits


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def build_archive(episode_dir: Path, dest: Path,
                  log: Callable[[str], None] = lambda _: None) -> PublishResult:
    """Archive one episode, dropping optional components only if oversize."""
    res = PublishResult(episode_id=episode_dir.name)

    leaked = scan_for_credentials(episode_dir)
    if leaked:
        raise CredentialInArtifact(
            f"credential shape found in {len(leaked)} file(s) under "
            f"{episode_dir}: {leaked[:5]}; refusing to commit.  Rotate the key "
            f"and investigate how it reached an artifact before republishing.")

    exclude_dirs: set[str] = set()

    def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(ti.name).parts
        if Path(ti.name).name in ALWAYS_EXCLUDE:
            return None
        if any(d in parts for d in exclude_dirs):
            return None
        # Archives are evidence, not a filesystem restore: drop ownership so the
        # bytes are identical regardless of who ran the campaign.
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    def _write() -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 in the gzip header, so re-archiving identical data does not
        # produce a different blob and a spurious commit.
        with open(dest, "wb") as raw:
            import gzip
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w") as tf:  # type: ignore[arg-type]
                    tf.add(episode_dir, arcname=episode_dir.name, filter=_filter)
        return dest.stat().st_size

    size = _write()

    def _present(name: str) -> int:
        return sum(_dir_size(d) for d in episode_dir.rglob(name) if d.is_dir())

    # Drop largest-first until it fits.  Ranked by on-disk size as a proxy, but
    # the *decision* to keep dropping is re-checked against the real compressed
    # size after each pass, and a directory that is not there is never recorded
    # as dropped -- a false drop record would misreport what the archive holds.
    for name in sorted(OPTIONAL_DIRS, key=_present, reverse=True):
        if size <= MAX_ARCHIVE_BYTES:
            break
        if not _present(name):
            continue
        exclude_dirs.add(name)
        before = size
        size = _write()
        res.dropped.append(name)
        log(f"    archive {before/1e6:.1f} MB > cap; dropped '{name}' "
            f"-> {size/1e6:.1f} MB")

    res.archive, res.archive_bytes = dest, size
    if size > MAX_ARCHIVE_BYTES:
        # Committing it would risk a blob the remote refuses, and an unpushable
        # branch loses every *later* episode as well as this one.  Keep the
        # evidence smallest-possible instead, and say exactly what is missing.
        dest.unlink(missing_ok=True)
        raise ArchiveTooLarge(
            f"{episode_dir.name}: {size/1e6:.1f} MB after dropping "
            f"{res.dropped or 'nothing'}, over the {MAX_ARCHIVE_BYTES/1e6:.0f} MB "
            f"limit; not committing an archive the remote may reject")
    return res


def _git(repo: Path, *args: str, check: bool = True,
         timeout: int = 300, retries: int = 3) -> subprocess.CompletedProcess:
    """Run git, retrying only the one failure that is genuinely transient.

    A concurrent `git` in the same clone (a person, another tool, this session)
    holds `index.lock` for a moment.  Without a retry that collision propagates
    up and stops the whole campaign -- an expensive way to lose to a race that
    resolves itself in milliseconds.  Every *other* non-zero exit is returned or
    raised as-is: retrying a real error just delays it.

    A timeout is not optional here.  Git talks to a remote, and a stalled push
    with no timeout hangs the campaign forever rather than failing it, which is
    strictly worse than stopping.
    """
    last = None
    for attempt in range(retries):
        try:
            r = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            if check:
                raise RuntimeError(f"git {' '.join(args[:2])} timed out after {timeout}s")
            return subprocess.CompletedProcess(args, 1, "", f"timed out after {timeout}s")
        last = r
        if r.returncode == 0:
            return r
        blob = (r.stderr or "") + (r.stdout or "")
        if "index.lock" in blob and attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    assert last is not None
    if check and last.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(last.stderr or last.stdout).strip()}")
    return last


def push_with_backoff(repo: Path, branch: str, log: Callable[[str], None],
                      attempts: int = 5) -> bool:
    """Push, retrying transient network failures with exponential backoff."""
    delay = 2
    for i in range(1, attempts + 1):
        # Push HEAD explicitly.  `git push origin <branch>` pushes the *local ref
        # of that name*, which is not necessarily the commit just made: on a
        # detached HEAD, or with HEAD on a different branch, git happily reports
        # "Everything up-to-date" and exits 0 while the episode stays local.  A
        # false success here is the worst outcome this module has, because the
        # campaign then keeps going and keeps not saving anything.
        r = _git(repo, "push", "-u", "origin", f"HEAD:refs/heads/{branch}", check=False)
        if r.returncode == 0:
            return True
        blob = (r.stderr or r.stdout)
        msg = blob.strip().splitlines()[-1:] or [""]
        log(f"    push attempt {i}/{attempts} failed: {msg[0][:160]}")
        # A non-fast-forward is permanent for a bare re-push: someone else moved
        # the branch.  Integrate once, then let the loop try again.
        if "non-fast-forward" in blob or "fetch first" in blob or "rejected" in blob:
            log("    remote has moved; rebasing onto it before retrying")
            _git(repo, "fetch", "origin", branch, check=False, timeout=300)
            rb = _git(repo, "rebase", f"origin/{branch}", check=False, timeout=300)
            if rb.returncode != 0:
                _git(repo, "rebase", "--abort", check=False)
                log("    rebase failed; leaving the branch alone")
                return False
        if i == attempts:
            return False
        time.sleep(delay)
        delay *= 2
    return False


def publish_episode(episode_dir: Path, *, repo_root: Path, campaign: str,
                    branch: str, index_files: dict[str, Path] | None = None,
                    summary: dict[str, Any] | None = None,
                    log: Callable[[str], None] = print) -> PublishResult:
    """Archive one episode into the repo, commit, and push.  Never raises on a
    push failure -- it reports one, so the caller decides whether to continue."""
    out_root = repo_root / "results" / "campaigns" / campaign
    # NB: not "episodes/" -- .gitignore excludes any directory of that name.
    archive_path = out_root / "artifacts" / f"{episode_dir.name}.tar.gz"

    res = build_archive(episode_dir, archive_path, log=log)

    # A browsable, uncompressed summary so the repo is readable without
    # extracting anything.
    if summary is not None:
        sdir = out_root / "summary"
        sdir.mkdir(parents=True, exist_ok=True)
        payload = {**summary, "archive": str(archive_path.relative_to(repo_root)),
                   "archive_bytes": res.archive_bytes,
                   "dropped_components": res.dropped}
        (sdir / f"{episode_dir.name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")

    # Campaign-level index files (manifest, ledger) refreshed every episode.
    for name, src in (index_files or {}).items():
        if src.exists():
            (out_root / name).parent.mkdir(parents=True, exist_ok=True)
            (out_root / name).write_bytes(src.read_bytes())

    # The summary and the copied index files are committed too, so they are
    # scanned too.  Scanning only the episode dir left a hole: the ledger and
    # manifest are written by us, but "we wrote it" is not evidence it is clean.
    leaked_meta = scan_for_credentials(out_root)
    if leaked_meta:
        raise CredentialInArtifact(
            f"credential shape found in published metadata: {leaked_meta[:5]}")

    _git(repo_root, "add", "--force", str(out_root.relative_to(repo_root)))
    staged = _git(repo_root, "diff", "--cached", "--name-only", "--",
                  str(out_root.relative_to(repo_root)), check=False).stdout.strip()
    if not staged:
        log(f"    nothing new to publish for {episode_dir.name}")
        res.pushed = True
        return res

    label = summary.get("label") if summary else None
    cost = summary.get("cost") if summary else None
    subject = f"c{campaign.lstrip('c')}: {episode_dir.name}"
    if label:
        subject += f" -> {label}"
    body = (f"Archived after the episode completed, before the next one starts, "
            f"so a container reclaim cannot take the spend with it.\n\n"
            f"label: {label}\ncost: {cost}\n"
            f"archive: {res.archive_bytes/1e6:.2f} MB"
            + (f"\ndropped: {', '.join(res.dropped)}" if res.dropped else "")
            + "\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
              "Claude-Session: https://claude.ai/code/session_01VMvpNYyXoqEbmrqFvzpqsz\n")
    # Pathspec-scoped: `git commit` with no pathspec commits the *entire* index,
    # so anything else staged in this clone would ride along under an episode
    # subject, unscanned and unintended.
    _git(repo_root, "commit", "-q", "-m", subject, "-m", body,
         "--", str(out_root.relative_to(repo_root)))

    res.pushed = push_with_backoff(repo_root, branch, log)
    if not res.pushed:
        res.error = "push failed after retries"
        log(f"    !! {episode_dir.name} is committed locally but NOT pushed")
    else:
        log(f"    published {episode_dir.name} "
            f"({res.archive_bytes/1e6:.2f} MB){' minus ' + ', '.join(res.dropped) if res.dropped else ''}")
    return res
