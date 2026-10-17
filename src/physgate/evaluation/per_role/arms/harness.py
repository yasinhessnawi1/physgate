"""The harness arm's answer: the one answer file a run left on its run branch.

Both arms are told the same thing in the same bytes: write the answer to a file of a
given name in the directory you work in. A raw session works in one directory, so its
answer is there. A harness run decomposes the brief into modules, and each role session
works in its module's directory, the only place it may write, so the answer is the one
file of that name directly inside a module directory on the run branch after the last
merge. None is no answer; two are no answer either, since nothing says which one counts.

The read goes through the clean object store and a pinned git directory, as every read
of a role-written repository does, so nothing the run left in its repository can make the
read run a program; the file must be a regular blob no larger than any answer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.per_role.answer import MAX_ANSWER_BYTES
from physgate.orchestrator.git import git, head_of, verified_git_dir
from physgate.orchestrator.merge import RunGit

#: How the extraction ended. ``contract_lost`` is no answer file anywhere a module may
#: write: the brief's answer contract did not survive decomposition, or no session kept it.
Status = Literal["found", "contract_lost", "ambiguous", "not_a_file", "too_large", "not_text"]
_REGULAR = {"100644", "100755"}


class Extraction(BaseModel):
    """What was found on the run branch, and where the answer was written for the scorer."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: Status
    commit: str
    paths: tuple[str, ...]
    sha256: str | None = None


def extract(repo: Path, run_id: str, answer_name: str, out: Path) -> Extraction:
    """The answer the run ``run_id`` left in ``repo``, written to ``out`` when there is one.

    Every path directly inside a module directory named ``answer_name`` is looked at,
    whatever its type, so a link or a directory of that name is seen and refused rather
    than skipped.
    """
    pinned = verified_git_dir(repo, linked=False)
    commit = head_of(
        repo, RunGit(repo=repo, run_dir=repo, run_id=run_id).run_branch, git_dir=pinned
    )
    listing = git(repo, "ls-tree", "-r", "-t", commit, "modules", objects_only=True, git_dir=pinned)
    entries: list[tuple[str, str]] = []
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        mode = meta.split(" ", 1)[0]
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "modules" and parts[2] == answer_name:
            entries.append((mode, path))
    paths = tuple(sorted(path for _, path in entries))
    if not entries:
        return Extraction(status="contract_lost", commit=commit, paths=paths)
    if len(entries) > 1:
        return Extraction(status="ambiguous", commit=commit, paths=paths)
    mode, path = entries[0]
    if mode not in _REGULAR:
        return Extraction(status="not_a_file", commit=commit, paths=paths)
    spec = f"{commit}:{path}"
    if int(git(repo, "cat-file", "-s", spec, objects_only=True, git_dir=pinned)) > MAX_ANSWER_BYTES:
        return Extraction(status="too_large", commit=commit, paths=paths)
    try:
        raw = git(repo, "cat-file", "blob", spec, objects_only=True, git_dir=pinned).encode()
    except UnicodeDecodeError:
        return Extraction(status="not_text", commit=commit, paths=paths)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return Extraction(
        status="found", commit=commit, paths=paths, sha256=hashlib.sha256(raw).hexdigest()
    )
