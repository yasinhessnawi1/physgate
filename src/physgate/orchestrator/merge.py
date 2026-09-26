"""Where a run's work lives in git, the write-scope check, and the merge.

A run works on a branch of its own in the target repository, merged into by the
orchestrator in an integration worktree under the run directory; no main working
tree is ever checked out or written. Each subtask has one branch and one
worktree, kept across its attempts, so a repair attempt starts from what the
rejected attempt left.

**The write-scope check** makes "one agent writes one module" (ARCH-005)
enforced rather than arranged. An attempt may change only its own module
directory and its own node-proposal files. It runs before the gate, so an
attempt out of scope costs no gate run and no review. It reads the attempt
commit, the loop records that commit, and the merge merges exactly it:
the merger refuses any other SHA, so nothing can reach the run branch between
the check and the merge.

**The merge** is ``git merge --no-ff`` of the checked commit itself, not of a
branch name that could have moved. It is idempotent, so a merge already made is
found and returned rather than made twice. Dispatch is serial and every attempt
stays in its module, so a conflict means an invariant broke; the merge is
aborted and the run halts, and the agent is not charged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from physgate.orchestrator.exceptions import GitError, MergeConflictError, MergeRefusedError
from physgate.orchestrator.git import (
    add_worktree,
    branch_exists,
    changes_between,
    commit_all,
    diff_text,
    git,
    git_timed,
    head_of,
    merge_base,
    merges_of,
)
from physgate.orchestrator.ports import WorktreeRemoval

#: Where an agent proposes graph nodes, one whole node per file (the hook layer's route).
PROPOSALS = PurePosixPath(".physgate/proposals")
_PROPOSAL = re.compile(r"^\.physgate/proposals/[a-z][a-z0-9_]*(\.[a-z0-9_]+)+\.json$")
_REGULAR = "100644"
_ABSENT = "000000"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _safe(name: str, what: str) -> str:
    if not _SAFE_ID.match(name):
        msg = f"{what} is not a plain identifier"
        raise GitError(msg, value=name)
    return name


@dataclass(frozen=True)
class RunGit:
    """The git layout of one run."""

    repo: Path
    run_dir: Path
    run_id: str

    @property
    def run_branch(self) -> str:
        """The branch accepted attempts are merged into."""
        return f"physgate/{_safe(self.run_id, 'run id')}/run"

    @property
    def integration(self) -> Path:
        """The orchestrator's own worktree on the run branch."""
        return self.run_dir / "worktrees" / "_integration"

    def subtask_branch(self, subtask_id: str) -> str:
        """The branch a subtask's attempts are committed on."""
        return f"physgate/{_safe(self.run_id, 'run id')}/{_safe(subtask_id, 'subtask id')}"

    def subtask_worktree(self, subtask_id: str) -> Path:
        """The worktree a subtask's sessions run in."""
        return self.run_dir / "worktrees" / _safe(subtask_id, "subtask id")

    def open_run_branch(self, start: str) -> None:
        """Create the run branch at ``start`` and its integration worktree, once."""
        add_worktree(self.repo, self.integration, self.run_branch, start)

    def open_subtask(self, subtask_id: str) -> Path:
        """The subtask's worktree, created from the run branch's head if new."""
        path = self.subtask_worktree(subtask_id)
        add_worktree(self.repo, path, self.subtask_branch(subtask_id), self.run_branch)
        return path


def commit_attempt(worktree: Path, subtask_id: str, attempt: int, session_id: str) -> str:
    """The orchestrator's commit of whatever a session left in its worktree.

    The message is a template. No text an agent wrote becomes a commit message.
    """
    message = (
        f"Attempt {attempt} of subtask {subtask_id}\n\n"
        f"Committed by the orchestrator at the end of session {session_id}.\n"
    )
    return commit_all(worktree, message)


def write_scope_violations(repo: Path, base: str, commit: str, module_dir: str) -> list[str]:
    """Every change from ``base`` to ``commit`` outside the attempt's own scope.

    In scope: regular files and executables under ``module_dir``, and regular
    files that are node proposals. Out of scope: any other path, and a symbolic
    link or a submodule anywhere, since either can point outside the module.
    """
    module = PurePosixPath(module_dir)
    if module.is_absolute() or ".." in module.parts or not module.parts:
        msg = "a module directory is a relative path inside the repository"
        raise GitError(msg, module_dir=module_dir)
    found: list[str] = []
    for change in changes_between(repo, base, commit):
        mode = change.new_mode if change.new_mode != _ABSENT else change.old_mode
        if mode not in (_REGULAR, "100755"):
            found.append(f"{change.path} (not a regular file)")
            continue
        path = PurePosixPath(change.path)
        if path.is_relative_to(module):
            continue
        if _PROPOSAL.match(change.path) and change.new_mode in (_REGULAR, _ABSENT):
            continue
        found.append(f"{change.path} (outside {module_dir})")
    return found


def merge_message(subtask_id: str, attempt: int, commit: str, gate: str, review: str) -> str:
    """The merge commit's message, from a template."""
    return (
        f"Merge subtask {subtask_id}, attempt {attempt}\n\n"
        f"Gate: {gate}. Review: {review}. Checked commit: {commit}.\n"
    )


class GitMerger:
    """The loop's merge port over a run's git layout."""

    def __init__(self, run: RunGit, *, removal_timeout_s: float) -> None:
        """Merge into ``run``'s run branch, which must already exist.

        ``removal_timeout_s`` bounds one worktree removal; on the server's network
        volume one removal was measured at 266 s, and a removal must never stall a run.
        """
        self._run = run
        self._removal_timeout_s = removal_timeout_s

    def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
        """Merge exactly ``attempt_commit`` into the run branch and return the merge.

        Raises:
            MergeRefusedError: the subtask's branch no longer points at the checked
                commit, so what would be merged is not what was checked.
            MergeConflictError: the merge did not apply cleanly; it was aborted.
        """
        run = self._run
        branch = run.subtask_branch(subtask_id)
        if not branch_exists(run.repo, branch) or head_of(run.repo, branch) != attempt_commit:
            msg = "the subtask's branch is not at the commit that was checked"
            raise MergeRefusedError(msg, subtask=subtask_id, checked=attempt_commit)
        base = merge_base(run.repo, run.run_branch, attempt_commit)
        already = merges_of(run.repo, run.run_branch, base).get(attempt_commit)
        if already is not None:
            return already
        try:
            git(run.integration, "merge", "--no-ff", "--no-edit", "-m", message, attempt_commit)
        except GitError as exc:
            git(run.integration, "merge", "--abort", check=False)
            msg = "an accepted attempt did not merge cleanly"
            raise MergeConflictError(
                msg, subtask=subtask_id, commit=attempt_commit, stderr=exc.context.get("stderr", "")
            ) from None
        return head_of(run.integration, "HEAD")

    def run_branch_moved(self, expected: str, pending: str | None) -> str | None:
        """Why the run branch is not at ``expected``, or ``None``.

        Read through git, so a ref moved in ``packed-refs`` is seen as well as a
        loose one. A merge of exactly ``pending`` onto ``expected`` is accepted: it
        is the merge a killed process made and did not record.
        """
        run = self._run
        head = head_of(run.repo, run.run_branch)
        if head == expected:
            return None
        if pending is not None:
            parents = git(run.repo, "rev-list", "--parents", "-n", "1", head).split()[1:]
            if parents == [expected, pending]:
                return None
        return (
            f"the run branch {run.run_branch} is at {head}, not at {expected}, "
            "where this run last left it"
        )

    def remove_worktree(self, subtask_id: str) -> WorktreeRemoval:
        """Remove a subtask's worktree with ``git worktree remove``, never forced.

        The branch stays, and so does everything under the run directory but the
        worktree. A removal git refuses (a modified or untracked file, a lock) is
        reported and left as it is. Never raises.
        """
        path = self._run.subtask_worktree(subtask_id)
        if not path.exists():
            return WorktreeRemoval(path=str(path), outcome="absent", seconds=0.0, detail=None)
        code, stderr, seconds = git_timed(
            self._run.repo, "worktree", "remove", str(path), timeout=self._removal_timeout_s
        )
        if code is None:
            detail = f"no answer within {self._removal_timeout_s:g} s"
            return WorktreeRemoval(
                path=str(path), outcome="timed_out", seconds=seconds, detail=detail
            )
        if code != 0:
            return WorktreeRemoval(
                path=str(path), outcome="refused", seconds=seconds, detail=stderr or f"exit {code}"
            )
        return WorktreeRemoval(path=str(path), outcome="removed", seconds=seconds, detail=None)

    def artefact_diff(self, attempt_commit: str) -> str:
        """The attempt's patch against where it left the run branch."""
        run = self._run
        return diff_text(
            run.repo, merge_base(run.repo, run.run_branch, attempt_commit), attempt_commit
        )
