"""Extract an agent's patch from what it actually wrote, not from what it published.

Campaign `c01` recorded `no_patch_both` on an episode where both agents had
demonstrably edited source.  The cause is not the agents:

`mini_swe_agent_v2` grades the *published* artifact.  `adapter.py:259-266` calls
`GitConnector.submitted_patch()`, which is literally

    git --no-pager diff <base_sha> origin/<agent_id>          (connectors/git.py:247-251)

— a diff against **the remote-tracking ref of a branch the agent pushed**.  When
no branch was pushed it returns `""` (`git.py:230-241`), and the adapter wraps the
whole thing in a bare `except Exception: pass`, so every failure degrades to an
empty patch indistinguishable from an agent that did nothing.

That rule is defensible for CooperBench's own question ("did the team ship?"): work
nobody can see was not shipped.  It is wrong for ours.  We are measuring whether two
independently-correct changes integrate, so we need the changes themselves, and an
agent that wrote a correct patch but failed the publication ritual is not the same
event as an agent that wrote nothing.  Collapsing the two destroys the measurement:
`p` collapses toward zero and `p²` with it, so integration failures cannot appear at
all (`docs/EXPECTATIONS.md` §2.1, §5).

So we take the diff between the task base and the agent's **final working tree**.

Two sources, in order of preference:

1. **The live container**, while it is still running at collection time.  This is
   the real final tree, quiesced, and it captures committed *and* uncommitted work.
2. **The checkpoint bundle**, post hoc.  Works for an episode whose containers are
   long gone, and is how an archived episode can be re-extracted.  It is second
   because it is a *sampled* view: the snapshotter fires on a debounce, so its last
   commit is the last sample, which need not be the last state.

Which source produced a patch is always recorded.  Neither is inferred from the
other, and a disagreement between them is worth knowing about rather than smoothing
over.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# `sed -i` writes a sibling temp file and renames it.  One left behind is an
# artifact of the editing tool, not a source change the agent intended, and it
# carries a random name that would make patches gratuitously irreproducible.
SED_TEMP_PATHSPEC = ":(exclude,glob)**/sed??????"

# Where the task repo lives inside a CooperBench task container.
DEFAULT_WORK_TREE = "/workspace/repo"


@dataclass
class ExtractedPatch:
    agent_id: str = ""
    text: str = ""
    source: str = "none"
    base_sha: str = ""
    files_changed: int = 0
    note: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def to_dict(self) -> dict:
        return {"agent_id": self.agent_id, "source": self.source,
                "base_sha": self.base_sha, "bytes": len(self.text),
                "files_changed": self.files_changed, "empty": self.is_empty,
                "note": self.note, "warnings": self.warnings}


def normalize_patch(text: str) -> str:
    """Byte-for-byte the harness's own normalisation (`_coop/runtime.py:153-168`).

    Deliberately not `strip()`: a blank context line in a unified diff is
    ``" \\n"``, and stripping would eat the terminator and desynchronise the hunk
    header from its body, which `git apply` then rejects.
    """
    if not text or not text.strip():
        return ""
    return text.lstrip("\n").rstrip("\n") + "\n"


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout)


def _in(container_id: str, script: str, timeout: int = 300) -> tuple[int, str, str]:
    r = _docker("exec", container_id, "/bin/sh", "-lc", script, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def agent_id_of(container_id: str, work_tree: str = DEFAULT_WORK_TREE) -> str:
    """Which agent a container belongs to, read from the container itself.

    `GitConnector.setup()` runs `git config user.name "<agent_id>"`
    (`connectors/git.py:109`) and `git checkout -b <agent_id>` (`:143`), so the
    container states its own identity.  Container *names* are random
    (``minisweagent-<hex>``, `environments/docker.py:80`) and creation order is a
    race, so neither is used.
    """
    rc, out, _ = _in(container_id, f"git -C {work_tree} config user.name || true")
    name = (out or "").strip()
    if name:
        return name
    rc, out, _ = _in(container_id, f"git -C {work_tree} rev-parse --abbrev-ref HEAD || true")
    return (out or "").strip()


def patch_from_container(container_id: str, base_sha: str, *,
                         work_tree: str = DEFAULT_WORK_TREE) -> ExtractedPatch:
    """Diff the task base against the container's final working tree.

    `git add -A` first, so untracked new files count as work: an agent that adds a
    module has changed the tree, and a diff that ignored it would understate what
    it did.  Staging mutates the agent's index, which is safe because grading
    always runs in a *fresh* container (`farm/episode.py`), never this one.
    """
    res = ExtractedPatch(base_sha=base_sha, source="container")
    res.agent_id = agent_id_of(container_id, work_tree)

    rc, _, err = _in(container_id, f"git -C {work_tree} add -A -- . '{SED_TEMP_PATHSPEC}'")
    if rc != 0:
        res.warnings.append(f"git add failed: {err.strip()[:200]}")

    # Confirm the recorded base is really present before diffing against it;
    # diffing against a missing object yields a confusing wall of "new file".
    rc, _, _ = _in(container_id, f"git -C {work_tree} cat-file -e {base_sha}^{{commit}}")
    if rc != 0:
        res.warnings.append(f"base {base_sha[:12]} not found in container; using HEAD")
        base_sha = "HEAD"
        res.base_sha = "HEAD"

    rc, out, err = _in(
        container_id,
        f"git -C {work_tree} --no-pager diff --cached --binary "
        f"{base_sha} -- . '{SED_TEMP_PATHSPEC}'")
    if rc != 0:
        res.note = f"diff failed: {err.strip()[:200]}"
        return res
    res.text = normalize_patch(out)

    rc, out, _ = _in(container_id,
                     f"git -C {work_tree} --no-pager diff --cached --name-only "
                     f"{base_sha} -- . '{SED_TEMP_PATHSPEC}'")
    res.files_changed = len([l for l in (out or "").splitlines() if l.strip()])
    return res


def patch_from_bundle(bundle: Path, *, agent_id: str = "") -> ExtractedPatch:
    """Diff the checkpointer's first snapshot against its last.

    The snapshotter's first commit is the `baseline` trigger, taken at attach time
    before the agent has run, so it stands in for the task base; the last commit is
    the final sampled tree.  Sampled is the operative word -- see the module
    docstring.
    """
    res = ExtractedPatch(agent_id=agent_id, source="checkpoint_bundle")
    bundle = Path(bundle)
    if not bundle.exists():
        res.note = f"no bundle at {bundle}"
        return res

    tmp = Path(tempfile.mkdtemp(prefix="farm-patchgen-"))
    try:
        r = subprocess.run(["git", "clone", "--no-checkout", "-q", str(bundle), str(tmp / "ck")],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            res.note = f"bundle clone failed: {r.stderr.strip()[:200]}"
            return res
        repo = tmp / "ck"

        def git(*a: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *a],
                                  capture_output=True, text=True, timeout=600).stdout

        commits = [c for c in git("log", "--reverse", "--format=%H").splitlines() if c.strip()]
        if len(commits) < 2:
            res.note = f"only {len(commits)} checkpoint(s); nothing to diff"
            return res
        first, last = commits[0], commits[-1]
        res.base_sha = first
        res.text = normalize_patch(
            git("--no-pager", "diff", "--binary", first, last, "--", ".", SED_TEMP_PATHSPEC))
        names = git("--no-pager", "diff", "--name-only", first, last, "--", ".", SED_TEMP_PATHSPEC)
        res.files_changed = len([l for l in names.splitlines() if l.strip()])
        res.note = f"{len(commits)} checkpoints"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def checkpoint_bundles(attempt_dir: Path) -> dict[str, Path]:
    """Every checkpoint bundle in an attempt, keyed by short container id."""
    root = Path(attempt_dir) / "checkpoints_raw"
    if not root.is_dir():
        return {}
    return {d.name: d / "checkpoints.bundle"
            for d in sorted(root.iterdir())
            if d.is_dir() and (d / "checkpoints.bundle").exists()}


def wrote_but_submitted_nothing(attempt_dir: Path) -> list[str]:
    """Container ids whose checkpoints show writes.  Evidence, not inference.

    Used to catch the c01 failure directly: if the harness reports an empty patch
    while the snapshotter recorded source writes, the two disagree and the episode
    must not be silently labelled `no_patch`.
    """
    out: list[str] = []
    root = Path(attempt_dir) / "checkpoints_raw"
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        idx = d / "index.jsonl"
        if not idx.exists():
            continue
        writes = 0
        for line in idx.read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("trigger") != "baseline" and (row.get("paths") or row.get("files_changed")):
                writes += 1
        if writes:
            out.append(d.name)
    return out
