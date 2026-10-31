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
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.common import NonEmptyStr, utc_now, utc_stamp
from physgate.orchestrator.events import (
    ContractPairsPlanned,
    Decomposed,
    DesignReviewRan,
    DesignUnavailable,
    Envelope,
    Event,
    EventLog,
    Halted,
    Incident,
    InstallChecked,
    RunStarted,
    SubtaskPlanned,
    SubtaskRemoved,
    TokensUsed,
    require_writable,
)
from physgate.orchestrator.exceptions import RunConfigError, RunStateError
from physgate.orchestrator.managed import ObservedTraffic
from physgate.orchestrator.plan import CriterionWords, InterfaceConsumers, SystemRequirement
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.replay import RunState, project_ledger
from physgate.orchestrator.run_config import RunConfig, require_recorded, write_run_config
from physgate.orchestrator.trajectory import Seal
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
    #: The brief's own words for each system requirement the plan gives by number; ``None`` or
    #: empty when there are none, and then left out of the line.
    brief_words: tuple[CriterionWords, ...] | None = None


class ReviewInstall(BaseModel):
    """The hooks' installation the plan's review session ran under, as it was checked or built."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: NonEmptyStr
    action: Literal["checked", "built"]
    seconds: Annotated[float, Field(ge=0)]
    entries: Annotated[int, Field(ge=0)]


class PlanReviewed(BaseModel):
    """What the plan's review came to, for the run's opening, and what its session spent.

    One of a verdict, why there is none, or an exposure of held-out material in its stream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    install: ReviewInstall
    #: The seal the review held the call's stream to: the one the call took.
    stream_seal: Seal
    #: The review's session, which its tokens are attributed to; ``None`` if none ran.
    session_id: NonEmptyStr | None
    usage: tuple[MessageUsage, ...]
    result: ReviewResult | None = None
    unavailable: DesignUnavailable | None = None
    #: The review's stream showed one of the run's held-out canaries (ARCH-141).
    exposed: bool = False

    @model_validator(mode="after")
    def _one_ending(self) -> PlanReviewed:
        endings = (self.result is not None, self.unavailable is not None, self.exposed)
        if sum(endings) != 1:
            msg = "a plan's review ends in a verdict, in none, or in an exposure: one of them"
            raise ValueError(msg)
        if self.exposed and self.session_id is None:
            msg = "an exposure names the review session whose stream showed it"
            raise ValueError(msg)
        ending = self.result or self.unavailable
        if ending is not None and ending.session_id != self.session_id:
            msg = "a review's tokens are attributed to the session its ending names"
            raise ValueError(msg)
        return self


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
            first = self.log.events[0] if self.log.events else None
            said = (
                (first.queue_decisions, first.design_review)
                if isinstance(first, RunStarted)
                else None
            )
            if said is not None and said != self._said():
                # Replay reads both switches from the first line alone: one that says other than
                # the configuration would drive this run by another run's rules.
                msg = "the run's first line says other than its config of the switches it names"
                raise RunConfigError(
                    msg,
                    run_dir=str(self.run_dir),
                    logged=f"queue_decisions={said[0]}, design_review={said[1]}",
                    recorded=f"queue_decisions={config.queue_decisions}, "
                    f"design_review={config.design_review}",
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

    def _begin(self, call: DecompositionCall | None, reviewed: PlanReviewed | None = None) -> None:
        if self.log.events:
            msg = "the run was already started"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        write_run_config(self.config_path, self.config)
        for line in self._opening(call, self.envelope, reviewed):
            self.emit(line)

    def _opening(
        self,
        call: DecompositionCall | None,
        envelope: Callable[[], Envelope],
        reviewed: PlanReviewed | None = None,
    ) -> Iterator[Event]:
        """The run's start line, what its one model call spent, and the review's installation.

        Each line is built as it is asked for. A line's envelope is taken when the line is
        built, so a caller that writes each line before it asks for the next gives every line
        the sequence number it is written at.
        """
        yield RunStarted(
            **envelope(),
            config_sha256=self.config.sha256(),
            escalation_backend=self.config.escalation_backend,
            queue_decisions=self._said()[0],
            design_review=self._said()[1],
        )
        if call is not None:
            for message in call.usage:
                yield TokensUsed(
                    **envelope(),
                    attribution=f"decomposition:{call.session_id}",
                    message_id=message.message_id,
                    usage=message.usage,
                )
        if reviewed is not None:
            # The review's session ran under this installation, before anything was written.
            yield InstallChecked(**envelope(), **reviewed.install.model_dump())

    def _said(self) -> tuple[Literal["act"] | None, Literal["observe"] | None]:
        """What the run's first line says of whether it acts on decisions and reviews its plan."""
        acts: Literal["act"] | None = "act" if self.config.queue_decisions == "act" else None
        return acts, "observe" if self.config.design_review == "observe" else None

    def _reviewing(
        self, reviewed: PlanReviewed, plan_sha256: str, envelope: Callable[[], Envelope]
    ) -> Iterator[Event]:
        """What the plan's review spent, then its line, or the exposure its stream showed."""
        for message in reviewed.usage:
            yield TokensUsed(
                **envelope(),
                attribution=f"reviewer:{reviewed.session_id or 'none'}",
                message_id=message.message_id,
                usage=message.usage,
            )
        if reviewed.exposed:
            # The held-out tier counts as exposed (ARCH-141): the exposure, then one halt, and
            # nothing is dispatched. The canary is never recorded.
            detail = f"held-out material in the stream of review session {reviewed.session_id}"
            yield Incident(**envelope(), subtask_id=None, cause="held_out_read", detail=detail)
            yield Halted(**envelope(), reason="incident", detail="held_out_read")
            return
        yield DesignReviewRan(
            **envelope(),
            plan_sha256=plan_sha256,
            stream_seal=reviewed.stream_seal,
            result=reviewed.result,
            unavailable=reviewed.unavailable,
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
                brief_words=decomposed.brief_words or None,
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
        reviewed: PlanReviewed | None = None,
    ) -> None:
        """Record the configuration, the decomposition call, the plan and its review, once.

        ``reviewed`` is what the plan's review came to, given exactly when the run reviews its
        plan; its lines end the opening, after the plan they judge.

        Raises:
            RunStateError: the run was already started.
            RunConfigError: a subtask's role has no pinned model; a review is given to a run that
                does not review its plan, or none to one that does, or one with no plan's digest
                to name; or a line of the run's opening is one the log would refuse, the role
                register's check on the plan's marks among them. Each is raised before anything
                is written.
        """
        reviews = self.config.design_review != "off"
        if (reviewed is not None) != reviews:
            msg = "a run that reviews its plan records the review, and only such a run records one"
            raise RunConfigError(msg, design_review=self.config.design_review)
        digest = decomposed.plan_sha256 if decomposed is not None else None
        if reviewed is not None and digest is None:
            msg = "a plan's review names the plan by its digest, and this run records none"
            raise RunConfigError(msg, run_dir=str(self.run_dir))
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
            *self._opening(call, unwritten, reviewed),
            *self._planning(plan, decomposed, marked, unwritten),
        ]
        if reviewed is not None and digest is not None:
            opening += self._reviewing(reviewed, digest, unwritten)
        try:
            require_writable(opening, RunState())
        except ValueError as exc:
            raise RunConfigError(str(exc), run_dir=str(self.run_dir)) from None
        self._begin(call, reviewed)
        for line in self._planning(plan, decomposed, marked, self.envelope):
            self.emit(line)
        if reviewed is not None and digest is not None:
            for line in self._reviewing(reviewed, digest, self.envelope):
                self.emit(line)

    def fail_decomposition(self, call: DecompositionCall | None, detail: str) -> None:
        """Record a run whose one model call produced no usable plan. It ends there."""
        self._begin(call)
        self.emit(Halted(**self.envelope(), reason="decomposition_failed", detail=detail))

    def remove(self, subtask_id: str, reason: str) -> None:
        """Take a subtask not yet dispatched out of the plan; its id stays visible."""
        self.emit(SubtaskRemoved(**self.envelope(), subtask_id=subtask_id, reason=reason))
