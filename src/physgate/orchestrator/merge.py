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
aborted and the run halts, and the agent is not charged. The merge leaves an
attempt's disputes out: the change check read them from the attempt's commit and
the run's log records them, so the run branch, and every worktree opened from it,
never holds one, and two subtasks that dispute one quantity add no file to collide.
That merge takes three git calls; a process killed between them leaves the merge of
exactly the checked commit in progress, and the next process finishes it.

**Every git call here holds to the commit's rule.** A repository or worktree a
session could have touched has its ``.git`` pointer verified once per operation,
and each command of that operation runs pinned to the admin directory that check
returned, so nothing re-reads a pointer between the check and the use. History
(merge bases, a branch's merges, a commit's parents) is read in the clean object
store after the names are resolved, so the repository's ``shallow``, graft and
commit-graph files cannot reshape it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from physgate.orchestrator.declaration import DECLARATION_PATH
from physgate.orchestrator.dispute import DISPUTES_DIR
from physgate.orchestrator.exceptions import GitError, MergeConflictError, MergeRefusedError
from physgate.orchestrator.git import (
    GitDir,
    add_worktree,
    branch_exists,
    changes_between,
    commit_all,
    common_dir,
    diff_text,
    git,
    git_timed,
    head_of,
    merge_base,
    merges_of,
    utf8_name,
    verified_git_dir,
)
from physgate.orchestrator.ports import WorktreeRemoval

#: Where an agent proposes graph nodes, one whole node per file (the hook layer's route).
PROPOSALS = PurePosixPath(".physgate/proposals")
DISPUTES = PurePosixPath(DISPUTES_DIR)
_PROPOSAL = re.compile(r"^\.physgate/proposals/[a-z][a-z0-9_]*(\.[a-z0-9_]+)+\.json$")
_REGULAR = "100644"
_ABSENT = "000000"

#: Directories a build tool makes for its own output, by name, wherever they lie in a module.
BUILD_DIRECTORIES = frozenset({".pio"})
#: What a built file's name ends in: an executable image, its hex, raw and EEPROM forms, an
#: object file, an archive of them. A module's own binary data goes under another name.
BUILD_SUFFIXES = (".elf", ".hex", ".bin", ".eep", ".o", ".a")
#: What an attempt is told about each. A build writes into the session's temporary
#: directory; what it left in the module is removed, not committed.
BUILD_ARTEFACT = (
    "a built file inside the module: build into the session's temporary directory, and remove this"
)
BUILD_DIRECTORY = (
    "a build directory inside the module: build into the session's temporary directory, and "
    "remove this"
)
#: The most built files named one by one; past it the rest are counted.
MAX_ARTEFACTS_NAMED = 20
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

#: Where a run's interface contract files are: ``decompose.INTERFACES_DIR``, spelled here as well
#: because ``decompose`` imports this module.
CONTRACTS_DIR = ".physgate/interfaces"


def _safe(name: str, what: str) -> str:
    if not _SAFE_ID.fullmatch(name):
        msg = f"{what} is not a plain identifier"
        raise GitError(msg, value=name)
    return name


def _reopened(subtask_id: str, reopen: int) -> str:
    name = _safe(subtask_id, "subtask id")
    return f"{name}.reopen-{reopen}" if reopen else name


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

    def subtask_branch(self, subtask_id: str, reopen: int = 0) -> str:
        """The branch a subtask's attempts are committed on.

        After its ``reopen``-th reopen, a sibling of its own: ``.`` is outside a plain identifier,
        so no subtask's own branch is named so.
        """
        return f"physgate/{_safe(self.run_id, 'run id')}/{_reopened(subtask_id, reopen)}"

    def subtask_worktree(self, subtask_id: str, reopen: int = 0) -> Path:
        """The worktree a subtask's sessions run in; a fresh one after each reopen."""
        return self.run_dir / "worktrees" / _reopened(subtask_id, reopen)

    def open_run_branch(self, start: str) -> None:
        """Create the run branch at ``start`` and its integration worktree, once."""
        add_worktree(self.repo, self.integration, self.run_branch, start)

    def open_subtask(self, subtask_id: str, reopen: int = 0) -> Path:
        """The subtask's worktree, created from the run branch's head if new."""
        path = self.subtask_worktree(subtask_id, reopen)
        add_worktree(self.repo, path, self.subtask_branch(subtask_id, reopen), self.run_branch)
        return path


def attempt_message(subtask_id: str, attempt: int, session_id: str) -> str:
    """The template every attempt commit's message is: no text an agent wrote is one."""
    return (
        f"Attempt {attempt} of subtask {subtask_id}\n\n"
        f"Committed by the orchestrator at the end of session {session_id}.\n"
    )


def attempt_head(worktree: Path, *, repo: Path) -> tuple[str, str] | None:
    """The commit at the worktree's head and its message, or ``None`` if it has no commit."""
    admin = verified_git_dir(worktree, linked=True, common=common_dir(repo))
    try:
        shown = git(worktree, "log", "-1", "--format=%H%x00%B", git_dir=admin)
    except GitError:
        return None
    commit, _, message = shown.partition("\0")
    return commit.strip(), message.rstrip("\n") + "\n"


def commit_attempt(
    worktree: Path,
    subtask_id: str,
    attempt: int,
    session_id: str,
    *,
    repo: Path,
    replaces: str | None = None,
) -> str:
    """The orchestrator's commit of whatever a session left in its worktree.

    The message is a template. No text an agent wrote becomes a commit message. ``repo`` is the
    repository the worktree was made in: the worktree's admin directory must belong to it.
    ``replaces`` is this attempt's commit at the worktree's head from a session whose end was
    never recorded: the new commit takes its place, on its parent, so the attempt has one commit.
    """
    message = attempt_message(subtask_id, attempt, session_id)
    return commit_all(worktree, message, linked=True, common=common_dir(repo), replaces=replaces)


def write_scope_violations(
    repo: Path,
    base: str,
    commit: str,
    module_dir: str,
    *,
    declares: bool = False,
    disputes: bool = False,
    git_dir: GitDir | None = None,
) -> list[str]:
    """Every change from ``base`` to ``commit`` outside the attempt's own scope.

    In scope: regular files and executables under ``module_dir``, regular files that
    are node proposals, for an attempt of the role that owns completion
    (``declares``) the completion declaration as a regular file, and for an attempt of
    a role that may dispute (``disputes``) a regular file in the disputes directory,
    which the change check reads as a dispute, directly in it. Out of scope: a name that is not
    UTF-8, any
    other path, and a symbolic link or a submodule anywhere, since either can point
    outside the module. ``git_dir`` is the repository's verified git directory, if the
    caller has one.

    Out of scope inside the module too: what a build left there. The commit holds everything
    a session left in its worktree, so a build that wrote into the module would put its tree
    into the attempt, the review's diff and the run branch. A file the commit adds or changes
    beneath a build directory (:data:`BUILD_DIRECTORIES`) is named by that directory, once,
    with the number of files; a built file elsewhere (:data:`BUILD_SUFFIXES`) is named by its
    path, the first :data:`MAX_ARTEFACTS_NAMED` of them. Names are matched in any case.
    Removing one is in scope: that is the repair.
    """
    module = PurePosixPath(module_dir)
    if module.is_absolute() or ".." in module.parts or not module.parts:
        msg = "a module directory is a relative path inside the repository"
        raise GitError(msg, module_dir=module_dir)
    found: list[str] = []
    trees: dict[str, int] = {}
    built: list[str] = []
    for change in changes_between(repo, base, commit, git_dir=git_dir):
        escaped = utf8_name(change.path)
        if escaped is not None:
            # First, so no later rule and no line ever holds a name no reader can decode.
            found.append(f"{escaped} (not a UTF-8 name)")
            continue
        mode = change.new_mode if change.new_mode != _ABSENT else change.old_mode
        if mode not in (_REGULAR, "100755"):
            found.append(f"{change.path} (not a regular file)")
            continue
        path = PurePosixPath(change.path)
        if path.is_relative_to(module):
            if change.new_mode != _ABSENT:
                tree = _build_directory(path, len(module.parts))
                if tree is not None:
                    trees[tree] = trees.get(tree, 0) + 1
                elif path.name.casefold().endswith(BUILD_SUFFIXES):
                    built.append(change.path)
            continue
        if _PROPOSAL.fullmatch(change.path) and change.new_mode in (_REGULAR, _ABSENT):
            continue
        if declares and change.path == DECLARATION_PATH and change.new_mode == _REGULAR:
            continue
        if disputes and path.parent == DISPUTES and change.new_mode in (_REGULAR, _ABSENT):
            continue
        found.append(f"{change.path} (outside {module_dir})")
    # Both in the order git lists changes, which is by path.
    found += [f"{tree}/ ({BUILD_DIRECTORY}, {count} files)" for tree, count in trees.items()]
    found += [f"{path} ({BUILD_ARTEFACT})" for path in built[:MAX_ARTEFACTS_NAMED]]
    if len(built) > MAX_ARTEFACTS_NAMED:
        rest = len(built) - MAX_ARTEFACTS_NAMED
        found.append(f"{module_dir} ({rest} more built files, not named)")
    return found


def _build_directory(path: PurePosixPath, module_depth: int) -> str | None:
    """The outermost build directory inside the module that ``path`` lies beneath, if any."""
    parts = path.parts
    for depth in range(module_depth, len(parts) - 1):
        if parts[depth].casefold() in BUILD_DIRECTORIES:
            return "/".join(parts[: depth + 1])
    return None


def merge_message(
    subtask_id: str,
    attempt: int,
    commit: str,
    gate: str,
    review: str,
    *,
    approved_by: tuple[str, str, str] | None = None,
) -> str:
    """The merge commit's message, from a template.

    ``approved_by`` is who approved the attempt from the queue, the item and the digest of the
    item line they were shown (ARCH-133). Who decided is quoted as JSON, so a name that holds a
    line break cannot add a line of its own to the message.
    """
    text = (
        f"Merge subtask {subtask_id}, attempt {attempt}\n\n"
        f"Gate: {gate}. Review: {review}. Checked commit: {commit}.\n"
    )
    if approved_by is not None:
        who, item, shown = approved_by
        text += f"Approved by {json.dumps(who)} on queue item {item}, as shown ({shown}).\n"
    return text


class GitMerger:
    """The loop's merge port over a run's git layout."""

    def __init__(self, run: RunGit, *, removal_timeout_s: float) -> None:
        """Merge into ``run``'s run branch, which must already exist.

        ``removal_timeout_s`` bounds one worktree removal; on the server's network
        volume one removal was measured at 266 s, and a removal must never stall a run.
        """
        self._run = run
        self._removal_timeout_s = removal_timeout_s

    def merge(
        self,
        subtask_id: str,
        attempt: int,
        attempt_commit: str,
        message: str,
        reopen: int = 0,
        contracts: Mapping[str, str] | None = None,
    ) -> str:
        """Merge exactly ``attempt_commit`` into the run branch and return the merge.

        The merge commit's parents are the run branch and ``attempt_commit``; its tree is the
        merged tree without the disputes directory, with each of ``contracts`` (an interface's
        contract file, by path under the interfaces directory) holding the bytes given: the
        revisions the attempt followed, so later sessions read them.

        Raises:
            MergeRefusedError: the subtask's branch no longer points at the checked
                commit, so what would be merged is not what was checked.
            MergeConflictError: the merge did not apply cleanly; it was aborted.
        """
        run = self._run
        branch = run.subtask_branch(subtask_id, reopen)
        pinned = verified_git_dir(run.repo, linked=False)
        if (
            not branch_exists(run.repo, branch, git_dir=pinned)
            or head_of(run.repo, branch, git_dir=pinned) != attempt_commit
        ):
            msg = "the subtask's branch is not at the commit that was checked"
            raise MergeRefusedError(msg, subtask=subtask_id, checked=attempt_commit)
        base = merge_base(run.repo, run.run_branch, attempt_commit, git_dir=pinned)
        already = merges_of(run.repo, run.run_branch, base, git_dir=pinned).get(attempt_commit)
        if already is not None:
            return already
        admin = verified_git_dir(run.integration, linked=True, common=common_dir(run.repo))
        disputed = git(
            run.repo, "ls-tree", "--name-only", attempt_commit, "--", DISPUTES_DIR,
            objects_only=True, git_dir=pinned,
        )  # fmt: skip
        rewritten = dict(contracts or {})
        for path in rewritten:
            if PurePosixPath(path).parent != PurePosixPath(CONTRACTS_DIR) or not path.endswith(
                ".json"
            ):
                msg = "a merge rewrites interface contract files only"
                raise MergeRefusedError(msg, subtask=subtask_id, path=path)
        try:
            if (disputed or rewritten) and self._mid_merge_of(attempt_commit, admin):
                # A process killed between the calls left this very merge in progress: it is
                # finished, never aborted, so the run does not halt on a conflict no one had.
                if disputed:
                    git(run.integration, "rm", "-r", "-q", "-f", "--ignore-unmatch", "--",
                        DISPUTES_DIR, git_dir=admin)  # fmt: skip
                self._write_contracts(rewritten, admin)
                git(run.integration, "commit", "--no-edit", git_dir=admin)
            elif disputed or rewritten:
                git(
                    run.integration, "merge", "--no-ff", "--no-commit", "-m", message,
                    attempt_commit, git_dir=admin,
                )  # fmt: skip
                if disputed:
                    git(run.integration, "rm", "-r", "-q", "-f", "--", DISPUTES_DIR,
                        git_dir=admin)  # fmt: skip
                self._write_contracts(rewritten, admin)
                git(run.integration, "commit", "--no-edit", git_dir=admin)
            else:
                git(
                    run.integration, "merge", "--no-ff", "--no-edit", "-m", message,
                    attempt_commit, git_dir=admin,
                )  # fmt: skip
        except GitError as exc:
            git(run.integration, "merge", "--abort", check=False, git_dir=admin)
            msg = "an accepted attempt did not merge cleanly"
            raise MergeConflictError(
                msg, subtask=subtask_id, commit=attempt_commit, stderr=exc.context.get("stderr", "")
            ) from None
        # Through the admin directory the merge ran in: the pointer is not read again.
        return head_of(run.integration, "HEAD", git_dir=admin)

    def _write_contracts(self, contracts: Mapping[str, str], admin: GitDir) -> None:
        """Write each contract file into the merge in progress and stage it."""
        if not contracts:
            return
        for path, text in sorted(contracts.items()):
            target = self._run.integration / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        git(self._run.integration, "add", "--", *sorted(contracts), git_dir=admin)

    def _mid_merge_of(self, attempt_commit: str, admin: GitDir) -> bool:
        """Whether the integration worktree is mid-merge of exactly ``attempt_commit``.

        Only from the run branch's head: the loop holds the branch to where the run left it just
        before every merge, so a merge in progress from anywhere else, or of any other commit, is
        no merge of this run's and is aborted as before.
        """
        run = self._run
        found = git(run.integration, "rev-parse", "-q", "--verify", "MERGE_HEAD",
                    check=False, git_dir=admin).strip()  # fmt: skip
        if found != attempt_commit:
            return False
        pinned = verified_git_dir(run.repo, linked=False)
        here = head_of(run.integration, "HEAD", git_dir=admin)
        return here == head_of(run.repo, run.run_branch, git_dir=pinned)

    def run_branch_moved(self, expected: str, pending: str | None) -> str | None:
        """Why the run branch is not at ``expected``, or ``None``.

        Read through git, so a ref moved in ``packed-refs`` is seen as well as a
        loose one. A merge of exactly ``pending`` onto ``expected`` is accepted: it
        is the merge a killed process made and did not record.
        """
        run = self._run
        pinned = verified_git_dir(run.repo, linked=False)
        head = head_of(run.repo, run.run_branch, git_dir=pinned)
        if head == expected:
            return None
        if pending is not None:
            # The commit's own parents, read through the clean object store: a ``shallow``
            # or graft file in the repository would otherwise hide or replace them.
            parents = git(
                run.repo, "rev-list", "--parents", "-n", "1", head,
                objects_only=True, git_dir=pinned,
            ).split()[1:]  # fmt: skip
            if parents == [expected, pending]:
                return None
        return (
            f"the run branch {run.run_branch} is at {head}, not at {expected}, "
            "where this run last left it"
        )

    def remove_worktree(self, subtask_id: str, reopen: int = 0) -> WorktreeRemoval:
        """Remove a subtask's worktree with ``git worktree remove``, never forced.

        The branch stays, and so does everything under the run directory but the
        worktree. A removal git refuses (a modified or untracked file, a lock) is
        reported and left as it is. Never raises.
        """
        path = self._run.subtask_worktree(subtask_id, reopen)
        if not path.exists():
            return WorktreeRemoval(path=str(path), outcome="absent", seconds=0.0, detail=None)
        try:
            pinned = verified_git_dir(self._run.repo, linked=False)
        except GitError as exc:
            detail = f"{exc}: the repository's git directory did not verify"
            return WorktreeRemoval(path=str(path), outcome="refused", seconds=0.0, detail=detail)
        code, stderr, seconds = git_timed(
            self._run.repo, "worktree", "remove", str(path),
            timeout=self._removal_timeout_s, git_dir=pinned,
        )  # fmt: skip
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

    def review_base(self, attempt_commit: str) -> str:
        """Where the attempt left the run branch: the commit its review diffs against."""
        run = self._run
        pinned = verified_git_dir(run.repo, linked=False)
        return merge_base(run.repo, run.run_branch, attempt_commit, git_dir=pinned)

    def artefact_diff(self, attempt_commit: str) -> str:
        """The attempt's patch against where it left the run branch, without its disputes.

        A dispute's reason is its session's text: a person reads it on the record, not here.
        """
        run = self._run
        pinned = verified_git_dir(run.repo, linked=False)
        base = merge_base(run.repo, run.run_branch, attempt_commit, git_dir=pinned)
        excluded = f":(exclude){DISPUTES_DIR}"
        return diff_text(run.repo, base, attempt_commit, excluded, git_dir=pinned)
