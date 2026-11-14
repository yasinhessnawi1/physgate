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
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.common import NonEmptyStr, Timestamp, utc_now, utc_stamp
from physgate.orchestrator.events import (
    RETRIED_CAUSE,
    ContractPairsPlanned,
    Decomposed,
    DecompositionRetried,
    DesignReviewRan,
    DesignUnavailable,
    Envelope,
    Event,
    EventLog,
    Followable,
    Halted,
    Incident,
    InstallChecked,
    PlanProposed,
    RunStarted,
    SubtaskPlanned,
    SubtaskRemoved,
    TokensUsed,
    require_writable,
)
from physgate.orchestrator.exceptions import (
    MergePreconditionError,
    QueueError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.managed import FlagCache, ObservedTraffic
from physgate.orchestrator.plan import CriterionWords, InterfaceConsumers, SystemRequirement
from physgate.orchestrator.protocols import MessageUsage, ReviewResult
from physgate.orchestrator.queue import (
    PLAN,
    ApprovalQueue,
    QueueItem,
    item_id_for,
    plan_consequence,
    plan_item,
    round_stream,
)
from physgate.orchestrator.replay import RunState, project_ledger
from physgate.orchestrator.run_config import RunConfig, require_recorded, write_run_config
from physgate.orchestrator.trajectory import Seal
from physgate.roles import owners_of
from physgate.state.exceptions import CorruptRecordError
from physgate.state.task_ledger import TaskLedger
from physgate.state.write_account import ACCOUNT_NAME, WriteAccount

if TYPE_CHECKING:
    from physgate.orchestrator.design_rounds import Journal


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
    flag_cache: FlagCache | None = None
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
    #: The interfaces the role that owns the cross nodes produces, by their digests; ``None``
    #: where none follows.
    followable: Followable | None = None


class ReviewInstall(BaseModel):
    """The hooks' installation the plan's review session ran under, as it was checked or built."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: NonEmptyStr
    action: Literal["checked", "built"]
    seconds: Annotated[float, Field(ge=0)]
    entries: Annotated[int, Field(ge=0)]


class RoundReview(BaseModel):
    """What one round's plan review came to, and what its session spent, as its round keeps it.

    One of a verdict, why there is none, or an exposure of held-out material in its stream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

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
    def _one_ending(self) -> RoundReview:
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


class PlanReviewed(RoundReview):
    """What the plan's review came to, for the run's opening, and the installation it ran under."""

    install: ReviewInstall


class RetriedCall(BaseModel):
    """A round's first call, whose output its schema refused, and so made once more (ARCH-001)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    round: Annotated[int, Field(ge=1)]
    call: DecompositionCall
    detail: NonEmptyStr


class Proposal(BaseModel):
    """What one round's call proposed and when, and when its review ran, as its opening records it.

    ``started`` and ``ended`` are the call's; ``review_started`` and ``review_ended`` the review's,
    ``None`` where none ran. ``plan_sha256`` names the plan, or ``cause`` why the round has none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    round: Annotated[int, Field(ge=1)]
    session_id: NonEmptyStr
    model: NonEmptyStr | None
    num_turns: Annotated[int, Field(ge=0)]
    plan_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None
    cause: NonEmptyStr | None
    started: Timestamp
    ended: Timestamp
    review_started: Timestamp | None
    review_ended: Timestamp | None
    #: The round's first call, or the second made after the first's output was refused.
    call: Literal[1, 2] = 1


class EarlierRound(BaseModel):
    """A round before the last, re-planned after its review did not pass: kept in the opening."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    call: DecompositionCall
    reviewed: PlanReviewed
    plan_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


#: What a run's first line says of how it reviews its plan; nothing for a run that does not.
DesignReviewSaid = Literal["observe", "on", "repair:1", "repair:2", "repair:3"] | None


class _Mark(TypedDict, total=False):
    """The completion mark, spread into a planning line only where it is set."""

    owns_completion: Literal[True]


#: The timestamp a line carries when it is only checked, never written: the run's clock is not
#: asked for it, so the lines that are written keep the times they always had.
_UNWRITTEN_TS = utc_stamp(datetime(1970, 1, 1, tzinfo=UTC))

#: What a run that acts on decisions writes on its first line of the rule it starts under: a
#: subtask's first dispatch waits while a subtask it reads from waits on a person.
PRODUCER_WAIT: Literal["hold"] | None = "hold"


def _fields(line: BaseModel, names: Sequence[str]) -> tuple[object, ...]:
    return tuple(getattr(line, name) for name in names)


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
        # Opened before every record it names, so what it holds then is every earlier process's.
        self.account = WriteAccount(self.run_dir / ACCOUNT_NAME)
        try:
            self._open(clock)
        except BaseException:
            self.account.close()
            raise

    def _open(self, clock: Callable[[], datetime]) -> None:
        config = self.config
        self.log = EventLog(
            self.run_dir / "events.jsonl",
            run_id=config.run_id,
            gate_mode=config.gate_mode,
            clock=clock,
            state=self.state,
            account=self.account,
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
                if said[0] is None and config.queue_decisions == "act":
                    msg = (
                        "the run's first line does not name the decision mode its config acts on: "
                        "a run recorded before its first line named it, or one edited since, and "
                        "nothing on the line tells the two apart; decompose it again to act on "
                        "decisions, or again under queue_decisions: record to keep it record-only"
                    )
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
        opening = self.run_dir / "ledger.jsonl"
        try:
            self.ledger = TaskLedger(opening, account=self.account)
            opening = self.run_dir / "queue.jsonl"
            self.queue = ApprovalQueue(
                opening,
                clock=clock,
                decisions_refused_later=True,
                account=self.account,
            )
            opening = self.run_dir / "ledger.jsonl"
            project_ledger(self.state, self.ledger)
        except (CorruptRecordError, QueueError, MergePreconditionError) as exc:
            self._refused_at_open(opening, exc)
            raise
        if (
            self.state.reviews_plan
            and (self.state.plan_sha256 is not None or self.state.earlier_reviews)
            and self.state.design_review is None
            and self.state.halted is None
        ):
            # The opening is written a line at a time: a decompose killed after the plan and
            # before its review's line left a run nothing may dispatch from, and nothing ever will.
            self.close()
            msg = (
                "the run's opening was cut before its review: nothing of it was dispatched; "
                "decompose it again into a fresh run directory"
            )
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if self.state.reviews_plan and self.log.events:
            self._require_rounds_ended()

    def _require_rounds_ended(self) -> None:
        """Refuse a run whose rounds' journal did not end, or is not the log's own rounds.

        The journal's terminal line is written once the run has started, so a decomposition killed
        between the two leaves an event log that reads as finished: only the journal says otherwise.

        Raises:
            RunStateError: the journal is missing, cut, ends void, or says other of its rounds than
                the log does: the arm, a call, a review or what either spent, which it names.
        """
        # Imported here: the rounds start the run through this record.
        from physgate.orchestrator.design_rounds import read_journal

        try:
            journal = read_journal(
                self.run_dir, last=self.state.replans + 1, holds=self.state.holds_plan
            )
            disagrees = next(
                (what for what, said, logged in self._rounds_said(journal) if said != logged),
                None,
            )
            if (
                not journal.complete
                or getattr(journal.lines[-1], "follows", "void") == "void"
                or disagrees is not None
            ):
                msg = (
                    "the decomposition was killed before its rounds ended, or its round journal is "
                    "not this run's rounds: nothing of it is dispatched; decompose again into a "
                    "fresh run directory"
                )
                raise RunStateError(msg, run_dir=str(self.run_dir), disagrees=disagrees or "none")
        except RunStateError:
            self.close()
            raise

    def _rounds_said(self, journal: Journal) -> Iterator[tuple[str, object, object]]:
        """What the journal and the log each say of the rounds, in the order they are compared.

        The arm; each round's call (its session, digest or cause, model, turns and times); each
        review that wrote a line (its ending, seal and times); and every token the opening spent,
        in turn, against each round's call usage and review usage.
        """
        from physgate.orchestrator.design_rounds import CallRefused, RoundEnded

        # The reader holds the first line to round 1's start, the one that names the arm.
        first, state = journal.lines[0], self.state
        named = ("design_review", "decomposition_model", "brief_sha256")
        arm = tuple(getattr(first, name, None) for name in named)
        config = self.config
        yield "arm", arm, (config.design_review, config.models.decomposition, config.brief_sha256)
        ended = [e for e in journal.lines if isinstance(e, RoundEnded)]
        call = ("round", "session_id", "plan_sha256", "model", "num_turns", "started")
        cause = [None if e.plan_sha256 else e.ending.plan_cause for e in ended]
        calls = [
            (*_fields(e, call), e.call_ended, why) for e, why in zip(ended, cause, strict=True)
        ]
        yield "calls", calls, [(*_fields(p, call), p.ended, p.cause) for p in state.proposals]
        again = [e for e in journal.lines if isinstance(e, CallRefused)]
        refused = ("round", "session_id", "model", "num_turns")
        yield (
            "refused calls",
            [(*_fields(e, refused), e.call_ended) for e in again],
            [(*_fields(p, refused), p.ended) for p in state.retried_calls],
        )
        seen = ("result", "unavailable", "stream_seal")
        ran = [(e, r) for e in ended if (r := e.review) is not None and not r.exposed]
        reviews = [(e.round, *_fields(r, seen), e.review_started, e.ended) for e, r in ran]
        lines = [*state.earlier_reviews, *filter(None, [state.design_review])]
        yield "reviews", reviews, [_fields(r, ("round", *seen, "started", "ended")) for r in lines]
        spent = []
        for e in ended:
            for first in (one for one in again if one.round == e.round):
                who = f"decomposition:{first.session_id}"
                spent += [(who, m.message_id, m.usage) for m in first.usage]
            spent += [(f"decomposition:{e.session_id}", m.message_id, m.usage) for m in e.usage]
            if e.review is not None:
                who = f"reviewer:{e.review.session_id or 'none'}"
                spent += [(who, m.message_id, m.usage) for m in e.review.usage]
        # The opening ends at the last round's review line, or at the halt that ends the run.
        events, last = self.log.events, len(state.proposals)
        ends = (
            isinstance(e, Halted) or isinstance(e, DesignReviewRan) and e.round == last
            for e in events
        )
        end = next((i for i, done in enumerate(ends) if done), len(events))
        tokens = [
            (e.attribution, e.message_id, e.usage)
            for e in events[:end]
            if isinstance(e, TokensUsed)
        ]
        yield "tokens", spent, tokens

    def _refused_at_open(self, record: Path, exc: Exception) -> None:
        """Put a held record refused at open on the record, where the event log takes a line.

        The task ledger or the approval queue holds what no orchestrator wrote, or what the log
        does not imply: an incident naming the record, and a halt, once. The refusal is raised
        after it all the same. A log that refuses to open takes no line, and its own refusal
        names it. A run halted for another cause, one a resume clears, is put on the record all
        the same; only a run already halted for a change to its records is not, again.
        """
        halted = self.state.halted
        if halted is not None and halted.detail == "run_records_changed":
            return
        detail = f"{record}: refused when the run opened: {exc}"
        self.log.append(
            Incident(
                **self.log.envelope(), subtask_id=None, cause="run_records_changed", detail=detail
            )
        )
        self.log.append(
            Halted(**self.log.envelope(), reason="incident", detail="run_records_changed")
        )

    def close(self) -> None:
        """Release every file handle."""
        if hasattr(self, "log"):
            self.log.close()
        if hasattr(self, "ledger"):
            self.ledger.close()
        self.account.close()

    def emit(self, event: Event) -> None:
        """Append one event, built by the caller, and bring the ledger up to it."""
        self.log.append(event)
        project_ledger(self.state, self.ledger)

    def envelope(self) -> Envelope:
        """The fields the next line carries, to spread into an event where it is built."""
        return self.log.envelope()

    def _begin(
        self,
        call: DecompositionCall | None,
        reviewed: PlanReviewed | None = None,
        earlier: Sequence[EarlierRound] = (),
        proposals: Sequence[Proposal] = (),
        retried: Sequence[RetriedCall] = (),
    ) -> None:
        if self.log.events:
            msg = "the run was already started"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        write_run_config(self.config_path, self.config)
        for line in self._opening(call, self.envelope, reviewed, earlier, proposals, retried):
            self.emit(line)

    def _require_proposals(
        self,
        earlier: Sequence[EarlierRound],
        proposals: Sequence[Proposal],
        retried: Sequence[RetriedCall] = (),
    ) -> None:
        """A run that reviews its plan proposes each round in turn; any other run proposes none.

        A round whose first call's output was refused proposes twice, its first call and then its
        second, and its refused call is given in ``retried``; a run that does not review its plan
        can have retried its one call alone.
        """
        reviews = self.config.design_review != "off"
        rounds = len(earlier) + 1 if reviews else 0
        firsts = [one.round for one in proposals if one.call == 1]
        seconds = [one.round for one in proposals if one.call == 2]
        again = [one.round for one in retried]
        if (
            firsts != list(range(1, rounds + 1))
            or (seconds if reviews else [1] * len(again)) != (again)
            or len(again) > (rounds if reviews else 1)
            or len(set(again)) != len(again)
        ):
            msg = "a run that reviews its plan records every round's proposal, and only such a run"
            raise RunConfigError(msg, design_review=self.config.design_review)

    def _opening(
        self,
        call: DecompositionCall | None,
        envelope: Callable[[], Envelope],
        reviewed: PlanReviewed | None = None,
        earlier: Sequence[EarlierRound] = (),
        proposals: Sequence[Proposal] = (),
        retried: Sequence[RetriedCall] = (),
    ) -> Iterator[Event]:
        """The run's start line, what its first call spent, the review's installation, each round.

        Each call's tokens are followed by its round's proposal, where the run reviews its plan.
        Each round before the last follows: its review's tokens and line, then the next call's
        tokens, so the last call's are the opening's last before its plan. Each line is built as
        it is asked for. A line's envelope is taken when the line is built, so a caller that writes
        each line before it asks for the next gives every line the sequence number it is written at.
        """
        yield RunStarted(
            **envelope(),
            config_sha256=self.config.sha256(),
            escalation_backend=self.config.escalation_backend,
            queue_decisions=self._said()[0],
            design_review=self._said()[1],
            # Each named only where the run differs from what every run before the switch did.
            reviewers=None if self.config.reviewers == "paired" else self.config.reviewers,
            skills=None if self.config.skills == "on" else self.config.skills,
            hooks=None if self.config.hooks == "on" else self.config.hooks,
            ablation=True if self.config.ablation else None,
            producer_wait=PRODUCER_WAIT if self._said()[0] == "act" else None,
        )
        calls = [*(one.call for one in earlier), *((call,) if call is not None else ())]
        if calls:
            yield from self._calls(1, calls[0], envelope, proposals, retried)
        ran = reviewed or (earlier[0].reviewed if earlier else None)
        if ran is not None:
            # The review's session ran under this installation, before anything was written.
            yield InstallChecked(**envelope(), **ran.install.model_dump())
        for index, one in enumerate(earlier):
            mine = [p for p in proposals if p.round == index + 1]
            timed = mine[-1] if mine else None
            yield from self._reviewing(one.reviewed, one.plan_sha256, envelope, timed, last=False)
            if index + 1 < len(calls):
                yield from self._calls(index + 2, calls[index + 1], envelope, proposals, retried)

    def _calls(
        self,
        round_: int,
        call: DecompositionCall,
        envelope: Callable[[], Envelope],
        proposals: Sequence[Proposal],
        retried: Sequence[RetriedCall],
    ) -> Iterator[Event]:
        """Round ``round_``'s calls: a refused first call and why, if there was one, then its own.

        In a run that reviews its plan the refused call's proposal names it; in any other run a
        line of its own does (:class:`DecompositionRetried`). Each call's tokens come before its
        line, so replay ties each to its session.
        """
        mine = [p for p in proposals if p.round == round_]
        for again in (one for one in retried if one.round == round_):
            yield from self._spent(again.call, envelope, mine[:1])
            if not proposals:
                yield DecompositionRetried(
                    **envelope(),
                    session_id=again.call.session_id,
                    cause=RETRIED_CAUSE,
                    detail=again.detail,
                )
            mine = mine[1:]
        yield from self._spent(call, envelope, mine)

    @staticmethod
    def _spent(
        call: DecompositionCall, envelope: Callable[[], Envelope], proposed: Sequence[Proposal]
    ) -> Iterator[Event]:
        """What a call spent, then its round's proposal where the run reviews its plan."""
        for message in call.usage:
            yield TokensUsed(
                **envelope(),
                attribution=f"decomposition:{call.session_id}",
                message_id=message.message_id,
                usage=message.usage,
            )
        for one in proposed:
            yield PlanProposed(
                **envelope(), **one.model_dump(exclude={"review_started", "review_ended"})
            )

    def _said(self) -> tuple[Literal["act"] | None, DesignReviewSaid]:
        """What the run's first line says of whether it acts on decisions and reviews its plan."""
        acts: Literal["act"] | None = "act" if self.config.queue_decisions == "act" else None
        review = self.config.design_review
        return acts, None if review == "off" else review

    def _reviewing(
        self,
        reviewed: RoundReview,
        plan_sha256: str,
        envelope: Callable[[], Envelope],
        timed: Proposal | None,
        *,
        last: bool = True,
    ) -> Iterator[Event]:
        """What a round's review spent, then its line, or the exposure its stream showed.

        Only the last round's line may hold the run: an earlier one was re-planned.
        """
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
        passed = reviewed.result is not None and reviewed.result.verdict == "pass"
        holds = last and self.config.design_review != "observe" and not passed
        yield DesignReviewRan(
            **envelope(),
            plan_sha256=plan_sha256,
            stream_seal=reviewed.stream_seal,
            result=reviewed.result,
            unavailable=reviewed.unavailable,
            held_item=item_id_for(self.config.run_id, PLAN, 1) if holds else None,
            round=timed.round if timed else None,
            started=timed.review_started if timed else None,
            ended=timed.review_ended if timed else None,
        )

    def plan_item(self) -> QueueItem | None:
        """The item the plan's review holds the run on, built from the log; ``None`` if none."""
        review = self.state.design_review
        if review is None or review.held_item is None:
            return None
        decomposed = next(e for e in self.log.events if isinstance(e, Decomposed))
        acts = self.config.queue_decisions == "act"
        earlier = tuple(self.state.earlier_reviews)
        return plan_item(
            review=review,
            spec_commit=decomposed.spec_commit,
            # Relative to the run, so a run moved between decompose and run builds it alike: the
            # held round's own stream, which its line sealed.
            stream=round_stream(len(earlier) + 1),
            consequence=plan_consequence() if acts else None,
            earlier=earlier,
        )

    def hold_plan(self) -> None:
        """List the item the plan's review holds the run on, once, while the hold is open."""
        item = self.plan_item() if self.state.plan_hold() is not None else None
        if item is not None and item.item_id not in {i.item_id for i in self.queue.items()}:
            self.queue.add(item)

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
                flag_cache=decomposed.flag_cache,
                plan_sha256=decomposed.plan_sha256,
                interface_consumers=decomposed.interface_consumers,
                system_requirements=decomposed.system_requirements,
                brief_words=decomposed.brief_words or None,
                followable=decomposed.followable,
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
        earlier: Sequence[EarlierRound] = (),
        proposals: Sequence[Proposal] = (),
        retried: Sequence[RetriedCall] = (),
    ) -> None:
        """Record the configuration, the decomposition call, the plan and its review, once.

        ``reviewed`` is what the plan's review came to, given exactly when the run reviews its
        plan; its lines end the opening, after the plan they judge. ``earlier`` are the rounds
        re-planned before it, each kept in the opening before the plan. ``proposals`` are every
        round's, the last included, given exactly when the run reviews its plan.

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
        self._require_proposals(earlier, proposals, retried)
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
        timed = proposals[-1] if proposals else None
        opening = [
            *self._opening(call, unwritten, reviewed, earlier, proposals, retried),
            *self._planning(plan, decomposed, marked, unwritten),
        ]
        if reviewed is not None and digest is not None:
            opening += self._reviewing(reviewed, digest, unwritten, timed)
        try:
            require_writable(opening, RunState())
        except ValueError as exc:
            raise RunConfigError(str(exc), run_dir=str(self.run_dir)) from None
        self._begin(call, reviewed, earlier, proposals, retried)
        for line in self._planning(plan, decomposed, marked, self.envelope):
            self.emit(line)
        if reviewed is not None and digest is not None:
            for line in self._reviewing(reviewed, digest, self.envelope, timed):
                self.emit(line)

    def fail_decomposition(
        self,
        call: DecompositionCall | None,
        detail: str,
        earlier: Sequence[EarlierRound] = (),
        proposals: Sequence[Proposal] = (),
        retried: Sequence[RetriedCall] = (),
    ) -> None:
        """Record a run whose last call produced no plan it could start, after ``earlier``."""
        self._require_proposals(earlier, proposals, retried)
        self._begin(call, None, earlier, proposals, retried)
        self.emit(Halted(**self.envelope(), reason="decomposition_failed", detail=detail))

    def remove(self, subtask_id: str, reason: str) -> None:
        """Take a subtask not yet dispatched out of the plan; its id stays visible."""
        self.emit(SubtaskRemoved(**self.envelope(), subtask_id=subtask_id, reason=reason))
