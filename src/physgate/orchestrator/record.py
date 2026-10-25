"""A run's durable record: its configuration, event log, task ledger and queue.

Separate from the loop so the decomposition step can start a run without the
ports a loop needs to dispatch one: a run is started by recording its
configuration, the one model call and the plan it produced, and the loop then
opens the same record and drives it.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.common import NonEmptyStr, utc_now, utc_stamp
from physgate.orchestrator.events import (
    ContractPairsPlanned,
    Decomposed,
    Envelope,
    Event,
    EventLog,
    Halted,
    RunStarted,
    SubtaskPlanned,
    SubtaskRemoved,
    TokensUsed,
    require_writable,
)
from physgate.orchestrator.exceptions import RunConfigError, RunStateError
from physgate.orchestrator.managed import ObservedTraffic
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.replay import RunState, project_ledger
from physgate.orchestrator.run_config import RunConfig, require_recorded, write_run_config
from physgate.roles import owners_of
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
    policy_limits_sha256: str | None = None
    observed_traffic: ObservedTraffic | None = None
    #: The plan's digest, taken from the plan itself; ``None`` for a run started without one.
    plan_sha256: str | None = None
    #: The two lists the integration role checks; ``None`` in a run without that role.
    interface_consumers: tuple[InterfaceConsumers, ...] | None = None
    system_requirements: tuple[SystemRequirement, ...] | None = None
    #: The module pairs whose contract is tested, read from the plan; ``None`` without the
    #: consumers, so a run without the integration role records no such line.
    contract_pairs: tuple[ContractPair, ...] | None = None


class _Mark(TypedDict, total=False):
    """The completion mark, spread into a planning line only where it is set."""

    owns_completion: Literal[True]


#: The timestamp a line carries when it is only checked, never written: the run's clock is not
#: asked for it, so the lines that are written keep the times they always had.
_UNWRITTEN_TS = utc_stamp(datetime(1970, 1, 1, tzinfo=UTC))


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
            if self.log.events and self.state.escalation_backend != config.escalation_backend:
                # The first line names the binding as well as the configuration's digest;
                # a log that names another binding is not this run's.
                msg = "the run's first line names another escalation backend than its config"
                raise RunConfigError(
                    msg,
                    run_dir=str(self.run_dir),
                    logged=str(self.state.escalation_backend),
                    recorded=str(config.escalation_backend),
                )
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
        for line in self._opening(call, self.envelope):
            self.emit(line)

    def _opening(
        self, call: DecompositionCall | None, envelope: Callable[[], Envelope]
    ) -> Iterator[Event]:
        """The run's start line and what its one model call spent, each built as it is asked for.

        A line's envelope is taken when the line is built, so a caller that writes each line
        before it asks for the next gives every line the sequence number it is written at.
        """
        yield RunStarted(
            **envelope(),
            config_sha256=self.config.sha256(),
            escalation_backend=self.config.escalation_backend,
        )
        if call is not None:
            for message in call.usage:
                yield TokensUsed(
                    **envelope(),
                    attribution=f"decomposition:{call.session_id}",
                    message_id=message.message_id,
                    usage=message.usage,
                )

    def _planning(
        self,
        plan: Sequence[PlanEntry],
        decomposed: DecompositionSummary | None,
        marked: frozenset[str],
        envelope: Callable[[], Envelope],
    ) -> Iterator[Event]:
        """The decomposition's line, if there was one, a planning line per subtask, then the pairs.

        The pairs come last, so the opening holds every subtask a side names, and the first
        dispatch finds them on the record.
        """
        if decomposed is not None:
            yield Decomposed(
                **envelope(),
                session_id=decomposed.session_id,
                model=decomposed.model,
                num_turns=decomposed.num_turns,
                subtasks=decomposed.subtasks,
                interface_nodes=decomposed.interface_nodes,
                spec_commit=decomposed.spec_commit,
                head_revision=decomposed.head_revision,
                policy_limits_sha256=decomposed.policy_limits_sha256,
                observed_traffic=decomposed.observed_traffic,
                plan_sha256=decomposed.plan_sha256,
                interface_consumers=decomposed.interface_consumers,
                system_requirements=decomposed.system_requirements,
            )
        for entry in plan:
            # The mark is written only where it is set: every other line keeps the bytes it
            # always had, and an explicit null is no line the log reads.
            mark: _Mark = {"owns_completion": True} if entry.subtask_id in marked else {}
            yield SubtaskPlanned(
                **envelope(),
                subtask_id=entry.subtask_id,
                spec_path=entry.spec_path,
                assigned_role=entry.assigned_role,
                module_dir=entry.module_dir,
                **mark,
            )
        if decomposed is not None and decomposed.contract_pairs is not None:
            yield ContractPairsPlanned(**envelope(), pairs=decomposed.contract_pairs)

    def _unwritten(self) -> Callable[[], Envelope]:
        """Envelopes numbered from a log's first line, for lines checked and never written."""
        numbers = itertools.count()
        run_id, gate_mode = self.config.run_id, self.config.gate_mode
        return lambda: Envelope(
            seq=next(numbers), ts=_UNWRITTEN_TS, run_id=run_id, gate_mode=gate_mode
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
            RunConfigError: a subtask's role has no pinned model; or a line of the run's opening
                is one the log would refuse, the role register's check on the plan's marks
                among them. Either is raised before anything is written.
        """
        for entry in plan:
            if entry.assigned_role not in self.config.models.roles:
                msg = "a planned subtask's role has no pinned model"
                raise RunConfigError(msg, role=entry.assigned_role)
        # The subtask of the role that owns completion is marked on its line, as the register
        # says now.
        owners = owners_of("completion")
        marked = frozenset(entry.subtask_id for entry in plan if entry.assigned_role in owners)
        # The whole opening is held to every check its lines would meet as they are written,
        # the register's and the replay's, before the first is written: a plan that breaks one
        # leaves no part of itself on the record, and no run is started from part of it.
        unwritten = self._unwritten()
        opening = [
            *self._opening(call, unwritten),
            *self._planning(plan, decomposed, marked, unwritten),
        ]
        try:
            require_writable(opening, RunState())
        except ValueError as exc:
            raise RunConfigError(str(exc), run_dir=str(self.run_dir)) from None
        self._begin(call)
        for line in self._planning(plan, decomposed, marked, self.envelope):
            self.emit(line)

    def fail_decomposition(self, call: DecompositionCall | None, detail: str) -> None:
        """Record a run whose one model call produced no usable plan. It ends there."""
        self._begin(call)
        self.emit(Halted(**self.envelope(), reason="decomposition_failed", detail=detail))

    def remove(self, subtask_id: str, reason: str) -> None:
        """Take a subtask not yet dispatched out of the plan; its id stays visible."""
        self.emit(SubtaskRemoved(**self.envelope(), subtask_id=subtask_id, reason=reason))
