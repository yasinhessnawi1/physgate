"""What the loop needs from the world, as narrow Protocols it is handed.

The loop decides; these do. A session is spawned and waited for, an attempt's
changes are checked before the gate, an accepted attempt's nodes are written
into the canonical store and the attempt merged, and the graph is diffed. Each
is a Protocol so the stage machine is tested over fakes with no process, no git
and no tokens, and so the real implementations
(the dispatcher, the git plumbing, the proposal apply) plug in without the loop
changing. None of them decides anything the loop should decide.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.run_config import RunBounds
from physgate.orchestrator.trajectory import Seal
from physgate.state.store import JournalLine, Payload

SessionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SessionRequest(_Frozen):
    """One attempt to hand to a fresh role session."""

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    assigned_role: NonEmptyStr
    spec_path: NonEmptyStr
    module_dir: NonEmptyStr
    model: NonEmptyStr
    repair_instruction: NonEmptyStr | None
    bounds: RunBounds


class SessionReport(_Frozen):
    """What a finished session left behind."""

    session_id: SessionId
    end: SessionEnd
    attempt_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")] | None
    trajectory: NonEmptyStr | None
    worktree: NonEmptyStr | None
    reading_verified: bool
    node_files_halted: bool
    #: The hook log's record of every append to the graph journal during the session.
    hook_journal_appends: tuple[NonEmptyStr, ...] = ()
    usage: tuple[MessageUsage, ...]
    #: What changed in the managed-settings tier during the session, if anything.
    managed_drift: NonEmptyStr | None = None
    #: The captured stream's digest and length when the session ended.
    trajectory_seal: Seal | None = None
    #: Why the stream is not one the runtime alone wrote (a forged tail), if it is not.
    trajectory_tampered: NonEmptyStr | None = None


class Leftover(_Frozen):
    """A session a previous orchestrator left without an end, found at a resume.

    ``stopped`` is whether it was still running and had to be stopped. Its usage
    is what its captured stream shows, each message's final usage; ``complete``
    is whether the stream holds the binary's result (a stopped session's never
    does, so its usage is partial and has nothing to be checked against).
    """

    session_id: SessionId
    pid: Annotated[int, Field(ge=1)]
    killed: Annotated[int, Field(ge=0)]
    stopped: bool
    usage: tuple[MessageUsage, ...] = ()
    complete: bool = False
    #: The stream's seal as the resume read it.
    seal: Seal | None = None
    #: Why the stream is not the runtime's alone (a tail, or an account the result
    #: does not bear out), if it is not. Then its usage ends at the runtime's result.
    tampered: NonEmptyStr | None = None


class ChangeCheck(_Frozen):
    """The verdict on an attempt's changes before the gate sees them."""

    refused_by: Literal["proposal", "write_scope"] | None
    reason: NonEmptyStr | None
    #: The offending paths or node id, for the finding's key.
    subject: NonEmptyStr | None = None
    graph_root: NonEmptyStr


class WorktreeRemoval(_Frozen):
    """What happened when a subtask's worktree was removed, and how long it took."""

    path: NonEmptyStr
    outcome: Literal["removed", "refused", "timed_out", "absent"]
    seconds: Annotated[float, Field(ge=0)]
    detail: NonEmptyStr | None


class Dispatcher(Protocol):
    """Runs one attempt in a fresh session in the subtask's worktree."""

    def run(self, request: SessionRequest) -> SessionReport:
        """Spawn, wait within the request's bounds, stop, and report."""
        ...

    def stop_leftovers(self) -> list[Leftover]:
        """Stop every session a previous orchestrator left running; say which, and what it spent."""
        ...

    def environment(self) -> InstallFacts | None:
        """What the hooks' installation and the session state directory are, on this machine."""
        ...


class ChangeChecker(Protocol):
    """Checks an attempt's write scope and pre-checks its node proposals."""

    def check(self, subtask_id: str, attempt_commit: str, role: str) -> ChangeCheck:
        """Check the attempt commit's changes; never writes the canonical store."""
        ...


class Merger(Protocol):
    """Applies an accepted attempt and merges it into the run branch."""

    def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
        """Merge exactly ``attempt_commit`` and return the merge commit.

        Idempotent: a merge already made is returned, not redone. Refuses a commit
        that is no longer what the subtask's branch points at.
        """
        ...

    def artefact_diff(self, attempt_commit: str) -> str:
        """The attempt's diff against where it started, for a person to read."""
        ...

    def run_branch_moved(self, expected: str, pending: str | None) -> str | None:
        """Why the run branch is not where the run left it, or ``None`` if it is.

        ``expected`` is the last merge the run recorded (or where the run started).
        ``pending`` is a checked commit whose merge may have landed without being
        recorded, when a process died between the two; a merge of exactly it onto
        ``expected`` is where the run left the branch, too.
        """
        ...

    def remove_worktree(self, subtask_id: str) -> WorktreeRemoval:
        """Remove a subtask's worktree without force; never its branch. Never raises."""
        ...


class GraphPort(Protocol):
    """The canonical graph store, as the loop reads and writes it.

    The loop holds one store handle across steps. Reading the journal's newest
    records never opens a store, since opening runs recovery, which writes; the
    handle is opened only after that read has found nothing foreign.
    """

    def records_after(self, revision: int) -> list[JournalLine]:
        """Every canonical journal record after ``revision``, read-only."""
        ...

    def hold(self) -> None:
        """Open the store handle if it is not open, and keep it.

        Called right after the journal was found to hold nothing foreign, so any
        later append the orchestrator did not make leaves the handle stale and
        its next write refuses, instead of being replayed by a later open.
        """
        ...

    def commit(self, message: str) -> None:
        """Commit the store's files, so the graph is committed (ARCH-010)."""
        ...

    def proposals(self, subtask_id: str, attempt_commit: str) -> list[Payload]:
        """The node proposals the attempt commit added or changed, validated."""
        ...

    def write(self, payload: Payload, role: str) -> int:
        """Write one node through the store's guards and return its revision.

        Raises ``StoreRefusalError`` for a refusal and ``StoreStaleError`` when the
        journal moved underneath the handle.
        """
        ...

    def divergences(self, since: int, acting_role: str) -> tuple[str, ...]:
        """Every node changed after ``since`` by a role that does not own it."""
        ...

    def reopen(self) -> tuple[int, tuple[str, ...]]:
        """Close and reopen the store; return the node files recovery repaired and moved aside."""
        ...
