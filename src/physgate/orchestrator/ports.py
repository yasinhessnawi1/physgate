"""What the loop needs from the world, as narrow Protocols it is handed.

The loop decides; these do. A session is spawned and waited for, an attempt's
changes are checked before the gate, an accepted attempt is merged, and the
graph is diffed. Each is a Protocol so the stage machine is tested over fakes
with no process, no git and no tokens, and so the real implementations
(the dispatcher, the git plumbing, the proposal apply) plug in without the loop
changing. None of them decides anything the loop should decide.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.run_config import RunBounds

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
    usage: tuple[MessageUsage, ...]


class ChangeCheck(_Frozen):
    """The verdict on an attempt's changes before the gate sees them."""

    refused_by: Literal["proposal", "write_scope"] | None
    reason: NonEmptyStr | None
    graph_root: NonEmptyStr


class Dispatcher(Protocol):
    """Runs one attempt in a fresh session in the subtask's worktree."""

    def run(self, request: SessionRequest) -> SessionReport:
        """Spawn, wait within the request's bounds, stop, and report."""
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


class GraphDiff(Protocol):
    """Diffs the graph off the durable record after a subtask's step."""

    def divergences(self, subtask_id: str) -> tuple[str, ...]:
        """Every node written in the step by a role that does not own it, described."""
        ...
