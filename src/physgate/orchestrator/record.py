"""A run's durable record: its configuration, event log, task ledger and queue.

Separate from the loop so the decomposition step can start a run without the
ports a loop needs to dispatch one: a run is started by recording its
configuration, the one model call and the plan it produced, and the loop then
opens the same record and drives it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.common import NonEmptyStr, utc_now
from physgate.orchestrator.events import (
    Decomposed,
    Envelope,
    Event,
    EventLog,
    Halted,
    RunStarted,
    SubtaskPlanned,
    SubtaskRemoved,
    TokensUsed,
)
from physgate.orchestrator.exceptions import RunConfigError, RunStateError
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.replay import RunState, project_ledger
from physgate.orchestrator.run_config import RunConfig, require_recorded, write_run_config
from physgate.state.task_ledger import TaskLedger


class DecompositionCall(BaseModel):
    """What the run's one model call spent and said, as the record keeps it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    session_id: NonEmptyStr
    usage: tuple[MessageUsage, ...]


class PlanEntry(BaseModel):
    """One subtask of the plan, as the run records it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    subtask_id: NonEmptyStr
    spec_path: NonEmptyStr
    assigned_role: NonEmptyStr
    module_dir: NonEmptyStr


class DecompositionSummary(BaseModel):
    """What the decomposition wrote, as the run's record of it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    session_id: NonEmptyStr
    model: NonEmptyStr
    num_turns: int
    subtasks: int
    interface_nodes: tuple[NonEmptyStr, ...]
    spec_commit: NonEmptyStr
    head_revision: int


class RunRecord:
    """The files one run is made of, opened and replayed."""

    def __init__(
        self, config: RunConfig, run_dir: Path, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        """Open the record in ``run_dir``, replaying whatever its log already holds.

        Raises:
            RunConfigError: the directory holds another configuration, or a log with
                no configuration.
        """
        self.config = config
        self.run_dir = Path(run_dir)
        self.config_path = self.run_dir / "run.json"
        self.state = RunState()
        self.log = EventLog(
            self.run_dir / "events.jsonl",
            run_id=config.run_id,
            gate_mode=config.gate_mode,
            clock=clock,
            state=self.state,
        )
        if self.config_path.exists():
            require_recorded(self.config_path, config)
        elif self.log.events:
            msg = "the run has events but no recorded configuration"
            raise RunConfigError(msg, run_dir=str(self.run_dir))
        self.ledger = TaskLedger(self.run_dir / "ledger.jsonl")
        self.queue = ApprovalQueue(self.run_dir / "queue.jsonl", clock=clock)
        project_ledger(self.state, self.ledger)

    def close(self) -> None:
        """Release every file handle."""
        self.log.close()
        self.ledger.close()

    def emit(self, event: Event) -> None:
        """Append one event, built by the caller, and bring the ledger up to it."""
        self.log.append(event)
        project_ledger(self.state, self.ledger)

    def envelope(self) -> Envelope:
        """The fields the next line carries, to spread into an event where it is built."""
        return self.log.envelope()

    def _begin(self, call: DecompositionCall | None) -> None:
        if self.log.events:
            msg = "the run was already started"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        write_run_config(self.config_path, self.config)
        self.emit(RunStarted(**self.envelope(), config_sha256=self.config.sha256()))
        if call is not None:
            for message in call.usage:
                self.emit(
                    TokensUsed(
                        **self.envelope(),
                        attribution=f"decomposition:{call.session_id}",
                        message_id=message.message_id,
                        usage=message.usage,
                    )
                )

    def start(
        self,
        plan: Sequence[PlanEntry],
        *,
        call: DecompositionCall | None = None,
        decomposed: DecompositionSummary | None = None,
    ) -> None:
        """Record the configuration, the decomposition call and the plan, once.

        Raises:
            RunStateError: the run was already started.
            RunConfigError: a subtask's role has no pinned model.
        """
        for entry in plan:
            if entry.assigned_role not in self.config.models.roles:
                msg = "a planned subtask's role has no pinned model"
                raise RunConfigError(msg, role=entry.assigned_role)
        self._begin(call)
        if decomposed is not None:
            self.emit(
                Decomposed(
                    **self.envelope(),
                    session_id=decomposed.session_id,
                    model=decomposed.model,
                    num_turns=decomposed.num_turns,
                    subtasks=decomposed.subtasks,
                    interface_nodes=decomposed.interface_nodes,
                    spec_commit=decomposed.spec_commit,
                    head_revision=decomposed.head_revision,
                )
            )
        for entry in plan:
            self.emit(
                SubtaskPlanned(
                    **self.envelope(),
                    subtask_id=entry.subtask_id,
                    spec_path=entry.spec_path,
                    assigned_role=entry.assigned_role,
                    module_dir=entry.module_dir,
                )
            )

    def fail_decomposition(self, call: DecompositionCall | None, detail: str) -> None:
        """Record a run whose one model call produced no usable plan. It ends there."""
        self._begin(call)
        self.emit(Halted(**self.envelope(), reason="decomposition_failed", detail=detail))

    def remove(self, subtask_id: str, reason: str) -> None:
        """Take a subtask not yet dispatched out of the plan; its id stays visible."""
        self.emit(SubtaskRemoved(**self.envelope(), subtask_id=subtask_id, reason=reason))
