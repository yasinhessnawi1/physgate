"""One artefact made real: the base design and one patch in a store, a worktree and a trajectory.

The base is written first, through the real store, and its head is the baseline:
nodes at or below it are the given design, which owes nothing. The patch is
then written as one revision above it, the way one merged attempt would be, and
the pair of commits is what a reviewer reads and what the gate judges.

**The reviewer's input is neutral and the same in form for every artefact.** An
injected artefact comes from no role session, so there is no trajectory for a
reviewer to read. In its place the instrument writes one fixed template: that a
revision of the design is proposed, where the design is, and the patch's node
files in full. It names no class, no check, no description and no corpus, and
the runner refuses to show a reviewer anything that does (``require_blind``).

Every byte is fixed by the corpus: commits carry a fixed author, date and
message, so the same patch gives the same commit and the same files every time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from physgate.evaluation.inject.corpus import Base, Patch, strings_of, telltales
from physgate.evaluation.inject.exceptions import BlindnessError, CorpusError
from physgate.state.store import Store

#: Where the design sits in a materialised worktree.
DESIGN_DIRNAME = "design"
TRAJECTORY_NAME = "trajectory.md"
#: Names that belong to a gate result or to the corpus. None may reach a reviewer.
ANSWER_FIELDS: tuple[str, ...] = (
    "verdict",
    "failing_check",
    "catalogue_sha256",
    "reviewer_had_passed",
    "gate_ran",
    "gate_mode",
    "error_class",
    "expected_check",
    "description",
    "injected",
)

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "design",
    "GIT_AUTHOR_EMAIL": "design@example.invalid",
    "GIT_COMMITTER_NAME": "design",
    "GIT_COMMITTER_EMAIL": "design@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


@dataclass(frozen=True)
class Materialised:
    """One base and one patch, on disk."""

    worktree: Path
    graph_root: Path
    trajectory: Path
    #: The store's head after the base: the given design ends here.
    baseline: int
    #: The revisions the patch wrote, in order: its one change set.
    revisions: tuple[int, ...]
    #: The worktree's head once the patch is written.
    commit: str
    #: The commit holding the given design alone: the patch's change is read against it.
    base_commit: str


def _git(worktree: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=worktree,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **_GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(worktree: Path, message: str) -> str:
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "--allow-empty", "-m", message)
    return _git(worktree, "rev-parse", "HEAD")


def materialise(base: Base, patch: Patch | None, into: Path) -> Materialised:
    """Write ``base``, then ``patch`` as one revision, into a new worktree at ``into``.

    With no patch, the base itself is the one revision, over an empty design:
    how the base alone is gated before any artefact is written over it.

    Raises:
        CorpusError: ``into`` exists, or the store refuses a write.
    """
    into = Path(into)
    if into.exists():
        msg = "an artefact is materialised into a directory that does not exist yet"
        raise CorpusError(msg, into=str(into))
    worktree = into / "worktree"
    graph_root = worktree / DESIGN_DIRNAME
    worktree.mkdir(parents=True)
    _git(worktree, "init", "-q", "-b", "main")
    given = base.nodes if patch is not None else ()
    written = patch.nodes if patch is not None else base.nodes
    store = Store(graph_root)
    try:
        for payload in given:
            _write(store, payload)
        baseline = store.head_revision()
        base_commit = _commit(worktree, "the given design")
        revisions = tuple(_write(store, payload) for payload in written)
    finally:
        store.close()
    commit = _commit(worktree, "a proposed revision")
    trajectory = into / TRAJECTORY_NAME
    trajectory.write_text(neutral_trajectory(written))
    return Materialised(
        worktree=worktree,
        graph_root=graph_root,
        trajectory=trajectory,
        baseline=baseline,
        revisions=revisions,
        commit=commit,
        base_commit=base_commit,
    )


def _write(store: Store, payload: dict[str, object]) -> int:
    """Write one node as its owner; return its revision.

    Raises:
        CorpusError: the store refuses it.
    """
    result = store.write_node(dict(payload), str(payload["owner_role"]))
    if not result.accepted or result.revision is None:
        msg = "the store refused a node of the corpus"
        raise CorpusError(msg, node=str(payload["id"]), reason=str(result.reason))
    return result.revision


def neutral_trajectory(nodes: tuple[dict[str, object], ...]) -> str:
    """The reviewer's account of the revision: the same template for every artefact."""
    parts = [
        "# A proposed revision of the design\n",
        f"The design is the graph under `{DESIGN_DIRNAME}/` in the worktree: one file per "
        f"node in `{DESIGN_DIRNAME}/nodes/`, and every write in "
        f"`{DESIGN_DIRNAME}/journal.jsonl`. The worktree's last commit is the revision. "
        "It wrote the nodes below, which now read as follows.\n",
    ]
    for payload in nodes:
        body = json.dumps(payload, indent=1, sort_keys=True)
        parts.append(f"## {payload['id']}\n\n```json\n{body}\n```\n")
    return "\n".join(parts)


def _as_token(answer: str) -> re.Pattern[str]:
    """``answer`` as a whole token: ``a01`` is not found inside a digest's hex."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(answer)}(?![A-Za-z0-9])")


def require_blind(materialised: Materialised, answers: tuple[str, ...]) -> None:
    """Refuse to show a reviewer this worktree and trajectory if they hold an answer.

    The two paths the reviewer is given, every file of the worktree but git's own,
    and the trajectory are read as text and
    held to the telltale words, to the names of a gate result's and the corpus's
    fields (files only), and to ``answers``: the artefact's own id, description
    and the like.

    Raises:
        BlindnessError: one of them is found.
    """
    paths = f"{materialised.worktree}\n{materialised.trajectory}"
    named = telltales(paths) + [a for a in answers if a and _as_token(a).search(paths)]
    if named:
        msg = "the paths a reviewer would be given state an answer"
        raise BlindnessError(msg, found=",".join(sorted(set(named))[:5]))
    files = [p for p in sorted(materialised.worktree.rglob("*")) if p.is_file()]
    files = [p for p in files if ".git" not in p.relative_to(materialised.worktree).parts]
    for path in [*files, materialised.trajectory]:
        text = path.read_text()
        found = telltales(text)
        found += [f for f in ANSWER_FIELDS if f'"{f}"' in text]
        found += [a for a in answers if a and _as_token(a).search(text)]
        if path.suffix == ".json" or path.name.endswith(".jsonl"):
            for line in text.splitlines():
                if line.strip():
                    found += [w for s in strings_of(json.loads(line)) for w in telltales(s)]
        if found:
            msg = "what a reviewer would be shown states an answer"
            raise BlindnessError(msg, file=path.name, found=",".join(sorted(set(found))[:5]))
