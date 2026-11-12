"""The rounds of a reviewed decomposition: each call, its plan's start check and its review.

A run that reviews its plan makes round 1's call as every run does. Under ``repair:N`` a verdict
other than a pass is followed by a re-plan, at most N times: a call told the brief's prompt, the
plan and the review's findings (:func:`replan_prompt`), in its own directory, and reviewed again.
What follows each round is decided by its ending alone and by whether it is round N + 1
(:func:`what_follows`), so a ``repair:N`` run's rounds are, as a prefix, those of every shorter one.

Each round is journalled as it goes, every line synced where it is written: a start line before
its call, an end line when it ends (its ending, the call's session and spending, the plan's digest
or why there is none, its review, the call's end and the review's start), its plan in its own file,
synced before that end line, and one terminal line naming the round the rounds ended on, how, and
what followed. The syncs are of each file, as the event log's are: a directory entry is not synced
apart. So whatever a later round does, the earlier rounds
are kept; a killed decomposition leaves the rounds that ended, and is never resumed
(:func:`require_fresh` refuses its directory). A run that does not review its plan makes its one
call and writes none of this.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from physgate.flags import DesignReview, replans
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.common import NonEmptyStr, Timestamp, utc_now, utc_stamp
from physgate.orchestrator.decompose import (
    ROUNDS_JOURNAL,
    Outcome,
    ReplanFindings,
    canary_in_findings,
    replan_findings,
    replan_prompt,
    require_startable,
    retry_prompt,
    start_run,
)
from physgate.orchestrator.decomposition_review import review_over, review_spawned
from physgate.orchestrator.endings import (
    Canary,
    PlanCause,
    PlanClass,
    ReviewCause,
    ReviewClass,
    RoundEnding,
    round_ending,
    what_follows,
)
from physgate.orchestrator.events import RETRIED_CAUSE, DesignUnavailable, Sha256
from physgate.orchestrator.exceptions import (
    AccountingError,
    DecompositionError,
    HeldOutExposedError,
    InvocationError,
    LibraryRefusedError,
    ModelSeparationError,
    OrchestratorError,
    PlanRefusedError,
    ReviewUnavailableError,
    RunStateError,
)
from physgate.orchestrator.plan import plan_bytes, plan_sha256
from physgate.orchestrator.ports import RecordsSpawns
from physgate.orchestrator.protocols import MessageUsage, PlanReviewer, PlanUnderReview
from physgate.orchestrator.queue import STREAM_NAME, plan_parts, round_parts
from physgate.orchestrator.record import (
    DecompositionCall,
    EarlierRound,
    PlanReviewed,
    Proposal,
    RetriedCall,
    ReviewInstall,
    RoundReview,
    RunRecord,
)
from physgate.orchestrator.run_config import RunConfig
from physgate.reviewers.exceptions import ReviewError

#: The directory a round's second call runs in, beneath the round's own.
RETRY_NAME = "retry"
#: What a round's ending class is, plan or review, as the terminal line names it.
EndingClass = PlanClass | ReviewClass


class _Line(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    round: Annotated[int, Field(ge=1)]


class RoundStarted(_Line):
    """A round begun: written before its call, naming the session the call is made as.

    Round 1's names the run's ``design_review`` mode, the designer's pinned model and the brief's
    digest, so an attempt
    that ends void, with no run record, says from its journal alone what it was; no later round's.
    """

    kind: Literal["round_started"] = "round_started"
    session_id: NonEmptyStr
    started: Timestamp
    design_review: DesignReview | None = None
    decomposition_model: NonEmptyStr | None = None
    brief_sha256: Sha256 | None = None


#: Seconds on the monotonic clock: finite, as no clock gives infinity.
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Elapsed(BaseModel):
    """A round's times in seconds since its attempt began, on the monotonic clock no step moves.

    The wall-clock times beside them can step back (NTP), so order is read from these alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    started: Seconds
    call_ended: Seconds
    review_started: Seconds | None
    ended: Seconds

    def in_order(self, after: float) -> bool:
        """Whether the round's times run in turn, from ``after``, the round before's end."""
        review = () if self.review_started is None else (self.review_started,)
        times = [after, self.started, self.call_ended, *review, self.ended]
        return times == sorted(times)


class RoundEnded(_Line):
    """A round ended: how, what its call spent and gave, and what its review came to."""

    kind: Literal["round_ended"] = "round_ended"
    ending: RoundEnding
    session_id: NonEmptyStr
    model: str | None
    num_turns: int
    usage: tuple[MessageUsage, ...]
    #: The digest of the round's plan, whose canonical bytes are its plan file; ``None`` without.
    plan_sha256: Sha256 | None
    detail: str
    review: RoundReview | None
    #: The round's span: from before its start line to its review's end, or its own end.
    started: Timestamp
    ended: Timestamp
    #: When the call ended, and when the review began (``None`` where none ran): the call and the
    #: review timed apart.
    call_ended: Timestamp
    review_started: Timestamp | None
    elapsed: Elapsed


class CallRefused(_Line):
    """A round's first call, whose output its schema refused: what it spent, and the next call.

    Written between the round's start and end lines, once a round at most. The round's call is
    then made once more, as ``retry_session_id``, and the end line is that call's.
    """

    kind: Literal["call_refused"] = "call_refused"
    session_id: NonEmptyStr
    model: str | None
    num_turns: int
    usage: tuple[MessageUsage, ...]
    detail: str
    call_ended: Timestamp
    retry_session_id: NonEmptyStr


class RoundsEnded(_Line):
    """The rounds' end: the round they ended on, its class and cause, and what followed."""

    kind: Literal["rounds_ended"] = "rounds_ended"
    follows: Literal["start", "fail_run", "void"]
    ending_class: EndingClass
    cause: NonEmptyStr
    detail: str


JournalLine = Annotated[
    RoundStarted | CallRefused | RoundEnded | RoundsEnded, Field(discriminator="kind")
]
_LINE: TypeAdapter[JournalLine] = TypeAdapter(JournalLine)


class MakeCall(Protocol):
    """One decomposition call, as :func:`physgate.orchestrator.decompose.call` makes it."""

    def __call__(
        self, brief: str, *, workdir: Path, prompt: str | None, session_id: str
    ) -> Outcome:
        """Make the call in ``workdir`` as ``session_id``, sent ``prompt`` or the brief's."""
        ...


@dataclass(frozen=True)
class RoundsOutcome:
    """The run the rounds started, whether from a plan, why not, and its last round's review."""

    record: RunRecord
    ok: bool
    cause: str | None
    detail: str
    reviewed: PlanReviewed | None


def round_dir(run_dir: Path, k: int) -> Path:
    """Where round k's call runs: the decomposition's directory for round 1, its own after."""
    return run_dir.joinpath(*round_parts(k))


def retry_dir(run_dir: Path, k: int) -> Path:
    """Where round k's second call runs, once its first call's output was refused."""
    return round_dir(run_dir, k) / RETRY_NAME


def plan_path(run_dir: Path, k: int) -> Path:
    """Round k's plan file: the canonical bytes its digest is taken over."""
    return run_dir.joinpath(*plan_parts(k))


def _synced(path: Path, data: bytes, mode: Literal["ab", "wb"]) -> None:
    """Write ``data`` to ``path`` and sync it before returning: a kill after keeps it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _append(journal: Path, line: RoundStarted | CallRefused | RoundEnded | RoundsEnded) -> None:
    _synced(journal, line.model_dump_json().encode() + b"\n", "ab")


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@dataclass(frozen=True)
class Journal:
    """The round journal as read: its lines, and whether its rounds ended (a terminal line)."""

    lines: tuple[JournalLine, ...]
    complete: bool


#: The review causes that come with no review record: the review never ran as one.
_NO_REVIEW = frozenset({"invocation_error", "model_separation"})


def _paired(line: RoundEnded) -> bool:
    """Whether the end line carries a digest exactly with a plan, and a review exactly as it ran.

    A review began exactly where the round's review ended one way or another, and its record is
    kept, saying what the ending says, but where the review never ran as one.
    """
    ending, review, cause = line.ending, line.review, line.ending.review_cause
    said = (
        None
        if review is None
        else review.result.verdict
        if review.result
        else review.unavailable.cause
        if review.unavailable
        else "held_out_exposed"
    )
    return (
        (line.plan_sha256 is not None) == (ending.plan_class == "plan")
        and (line.review_started is not None) == (cause is not None)
        and said == (None if cause in _NO_REVIEW else cause)
    )


def _what_ended(ending: RoundEnding) -> tuple[str, str]:
    """The class and cause a terminal line names for a round that ended so."""
    return str(ending.review_class or ending.plan_class), str(
        ending.review_cause or ending.plan_cause
    )


def _refused(run_dir: Path, k: int, check: str, cause: str = "record_missing") -> RunStateError:
    msg = "the round journal is not what the rounds write, in the order they write it"
    return RunStateError(msg, run_dir=str(run_dir), round=str(k), cause=cause, check=check)


def read_journal(run_dir: Path, *, last: int, holds: bool = True) -> Journal:
    """The round journal, each line held to what the rounds write given every line before it.

    Rounds run from 1 to at most ``last``, each a start then an end under a session of its own, but
    the last, which may only have started (a kill, or a void its call or review raised). An end
    line names a plan's digest exactly when the round has a plan, and a review exactly when one
    ran, saying what its ending says. A round follows only a round that is re-planned
    (:func:`what_follows`, with ``holds`` as the run holds a plan). The one terminal line names
    the last round, and what that round gives: its class, cause and what followed, or a void after
    a round that raised, the run it went on to start. Each ended round's plan file digests to its
    line's ``plan_sha256``; a round that planned spent; each review is a session of its own; each
    round's times run in turn on the monotonic clock; round 1 alone names the run's arm.

    Raises:
        RunStateError: the journal is missing, a line is not a journal line, a plan file is not
            what its line names, or a line is not one the rounds could have written after the lines
            before it; the context names the round and the check that refused it.
    """
    try:
        lines = tuple(
            _LINE.validate_json(one) for one in (run_dir / ROUNDS_JOURNAL).read_bytes().splitlines()
        )
    except (OSError, ValidationError) as exc:
        msg = "the round journal is missing, or a line of it is not one the rounds write"
        raise RunStateError(msg, run_dir=str(run_dir), cause="record_missing") from exc
    k, session, terminal, opened = 0, "", False, ""
    retried = 0
    seen: set[str] = set()
    before: RoundEnded | None = None
    for line in lines:
        starts = isinstance(line, RoundStarted)
        if terminal or (starts and session) or line.round != (k + 1 if starts else k):
            raise _refused(run_dir, line.round, "order")
        if isinstance(line, RoundStarted):
            if line.round > last:
                raise _refused(run_dir, line.round, "budget")
            if line.session_id in seen:
                raise _refused(run_dir, line.round, "session")
            arm = (line.design_review, line.decomposition_model, line.brief_sha256)
            if arm.count(None) != (line.round > 1) * len(arm):
                raise _refused(run_dir, line.round, "arm")
            if (
                before is not None
                and what_follows(before.ending, last=before.round == last, holds=holds) != "replan"
            ):
                raise _refused(run_dir, before.round, "follows")
            k, session, opened = line.round, line.session_id, line.started
            seen.add(session)
        elif isinstance(line, CallRefused):
            # Once a round, by the call the round started with, made again as a session of its own.
            if not session or line.session_id != session or retried == k:
                raise _refused(run_dir, k, "order")
            if line.retry_session_id in seen:
                raise _refused(run_dir, k, "session")
            retried, session = k, line.retry_session_id
            seen.add(session)
        elif isinstance(line, RoundEnded):
            if not session or line.session_id != session:
                raise _refused(run_dir, k, "session" if session else "order")
            if not _paired(line):
                raise _refused(run_dir, k, "pairing")
            if line.plan_sha256 is not None and (not line.usage or line.num_turns < 1):
                raise _refused(run_dir, k, "spent")  # a call that planned spent
            reviewer = line.review.session_id if line.review else None
            if reviewer is not None and reviewer in seen:
                raise _refused(run_dir, k, "session")  # each review a session of its own
            seen.add(reviewer or session)
            at = line.elapsed
            if (
                line.started != opened
                or (at.review_started is None) != (line.review_started is None)
                or not at.in_order(before.elapsed.ended if before else 0.0)
            ):
                raise _refused(run_dir, k, "time")
            if line.plan_sha256 is not None and _digest(plan_path(run_dir, k)) != line.plan_sha256:
                raise _refused(run_dir, k, "digest", "plan_digest_mismatch")
            session, before = "", line
        else:
            terminal = True
            raised = (line.follows, line.ending_class) == ("void", "infrastructure")
            if k == 0 or (session and not raised):
                raise _refused(run_dir, line.round, "terminal")
            if not session and before is not None:
                follows = what_follows(before.ending, last=k == last, holds=holds)
                given = (follows if follows != "replan" else "void", *_what_ended(before.ending))
                # A void the loop raised follows only a round it went on to start a run from.
                if (line.follows, line.ending_class, line.cause) != given and not (
                    raised and follows in ("start", "fail_run")
                ):
                    raise _refused(run_dir, k, "terminal")
    return Journal(lines, terminal)


def review_round(
    reviewing: tuple[PlanReviewer, ReviewInstall],
    outcome: Outcome,
    *,
    config: RunConfig,
    brief: str,
    stream: Path,
) -> PlanReviewed:
    """What the review of a round's plan came to.

    The reviewer is handed the brief as the run's digest names it, the plan and its digest, and
    the round's stream with the seal the call took where it wrote it. A review that is not a
    verdict, or whose stream showed held-out material, is what the review came to.

    Raises:
        RunStateError: the call gave a plan and sealed no stream.
    """
    if outcome.plan is None or outcome.stream_seal is None:
        msg = "the call gave a plan and sealed no stream, so its plan cannot be reviewed"
        raise RunStateError(msg, session_id=outcome.session_id)
    reviewer, install = reviewing
    under = PlanUnderReview(
        brief=brief,
        brief_sha256=config.brief_sha256,
        plan=outcome.plan,
        plan_sha256=plan_sha256(outcome.plan),
        stream=str(stream),
        stream_seal=outcome.stream_seal,
        decomposition_model=config.models.decomposition,
        decomposition_session_id=outcome.session_id,
    )
    ending: dict[str, object]
    try:
        result = reviewer.review_plan(under)
        ending = {"session_id": result.session_id, "usage": result.usage, "result": result}
    except ReviewUnavailableError as exc:
        why = DesignUnavailable(
            cause=exc.cause,
            detail=str(exc) or exc.cause,
            session_id=exc.session_id,
            reviewer_model=exc.reviewer_model,
            spec_defects=exc.spec_defects,
        )
        ending = {"session_id": exc.session_id, "usage": exc.usage, "unavailable": why}
    except HeldOutExposedError as exc:
        ending = {"session_id": exc.session_id, "usage": exc.usage, "exposed": True}
    return PlanReviewed.model_validate(
        {"install": install, "stream_seal": outcome.stream_seal, **ending}
    )


@dataclass(frozen=True)
class _Ran:
    outcome: Outcome
    ending: RoundEnding
    detail: str
    reviewed: PlanReviewed | None
    findings: ReplanFindings | None
    call_ended: tuple[str, float]
    review_started: tuple[str, float] | None
    #: The round's first call, where its output was refused and the call made once more.
    refused: Outcome | None = None
    refused_ended: str | None = None


def _one_round(
    brief: str,
    k: int,
    *,
    loop: _Loop,
    prompt: str | None,
    session: str,
) -> _Ran:
    """Round k: its call, its plan's start check, its plan's review, the canary in its findings."""
    workdir = round_dir(loop.run_dir, k)
    outcome = loop.make_call(brief, workdir=workdir, prompt=prompt, session_id=session)
    call_ended = loop.now()
    refused: Outcome | None = None
    if outcome.cause == RETRIED_CAUSE:
        # The output was refused by its schema: the call is made once more, the first journalled.
        refused, again = outcome, str(uuid.uuid4())
        _append(
            loop.run_dir / ROUNDS_JOURNAL,
            CallRefused(
                round=k,
                session_id=outcome.session_id,
                model=outcome.model,
                num_turns=outcome.num_turns,
                usage=outcome.usage,
                detail=outcome.detail,
                call_ended=call_ended[0],
                retry_session_id=again,
            ),
        )
        workdir = retry_dir(loop.run_dir, k)
        # Sent the prompt as it was, and, where a unit of the plan was refused, why.
        told = retry_prompt(brief, sorted(loop.config.models.roles), prompt, refused)
        outcome = loop.make_call(brief, workdir=workdir, prompt=told, session_id=again)
        refused_ended, call_ended = call_ended[0], loop.now()
    cause: PlanCause | None = outcome.cause
    detail = outcome.detail
    if outcome.ok and outcome.plan is not None:
        try:
            require_startable(
                outcome.plan,
                config=loop.config,
                target_repo=loop.target_repo,
                library=loop.library,
                brief=brief,
            )
        except PlanRefusedError as exc:
            cause, detail = "plan_refused", str(exc)
        except LibraryRefusedError as exc:
            cause, detail = "library_refused", str(exc)
    reviewed, findings = None, None
    review_cause: ReviewCause | None = None
    canary: Canary | None = None
    review_started: tuple[str, float] | None = None
    if cause is None:
        review_started = loop.now()
        try:
            reviewed = review_round(
                loop.reviewing,
                outcome,
                config=loop.config,
                brief=brief,
                stream=workdir / STREAM_NAME,
            )
        except InvocationError as exc:
            review_cause, detail = "invocation_error", str(exc)
        except ModelSeparationError as exc:
            review_cause, detail = "model_separation", str(exc)
        else:
            result, why = reviewed.result, reviewed.unavailable
            review_cause = result.verdict if result else why.cause if why else "held_out_exposed"
            if result is not None and result.verdict != "pass":
                # Looked for in every reviewing mode, so a round's record names no budget.
                findings = replan_findings(result)
                canary = canary_in_findings(findings, loop.check)
    # The review's record is removed by the rounds once this round's end is journalled: what the
    # review came to is on no record before that line.
    # No budget is set on the designer's call (its argv names none), so a spent one is never its.
    ending = round_ending(cause, review_cause, budget_set=False, canary=canary)
    return _Ran(
        outcome,
        ending,
        detail,
        reviewed,
        findings,
        call_ended,
        review_started,
        refused,
        refused_ended if refused is not None else None,
    )


@dataclass(frozen=True)
class _Loop:
    """What every round of one decomposition is made with, and where it is journalled."""

    config: RunConfig
    run_dir: Path
    target_repo: Path
    library: Path | None
    reviewing: tuple[PlanReviewer, ReviewInstall]
    check: CanaryCheck
    make_call: MakeCall
    #: The attempt's start on the monotonic clock.
    origin: float

    def now(self) -> tuple[str, float]:
        """The wall-clock time, and the seconds since the attempt began on the monotonic clock."""
        return utc_stamp(utc_now()), time.monotonic() - self.origin

    def end(self, k: int, follows: str, ending_class: str, cause: str, detail: str) -> None:
        """Write the terminal line: the round the rounds ended on, how, and what followed."""
        _append(
            self.run_dir / ROUNDS_JOURNAL,
            RoundsEnded.model_validate(
                {
                    "round": k,
                    "follows": follows,
                    "ending_class": ending_class,
                    "cause": cause,
                    "detail": detail,
                }
            ),
        )


def _cause(exc: OrchestratorError | ReviewError) -> str:
    """The cause an exception that ended a round is named by on the terminal line."""
    if isinstance(exc, AccountingError):
        return "accounting_mismatch"  # one of the run-level voids
    return str(getattr(exc, "cause", None) or type(exc).__name__)


def decompose_in_rounds(
    brief: str,
    *,
    config: RunConfig,
    run_dir: Path,
    target_repo: Path,
    library: Path | None,
    reviewing: tuple[PlanReviewer, ReviewInstall] | None,
    check: CanaryCheck,
    make_call: MakeCall,
    review_root: Path | None = None,
) -> RoundsOutcome:
    """Decompose in rounds and start the run the last round leads to.

    ``review_root`` is where the plan reviewer's sessions run: the record of a review's spawn
    names its session directory there, so a command after a kill can scan its streams.

    Raises:
        DecompositionError: the rounds ended void: no run is started, and the journal says why.
        OrchestratorError: the call, the review or the start raised it; the journal's terminal
            line names it, and no run is started.
    """
    if reviewing is None:  # one call, no review, nothing journalled
        outcome = make_call(
            brief, workdir=round_dir(run_dir, 1), prompt=None, session_id=str(uuid.uuid4())
        )
        retried: tuple[RetriedCall, ...] = ()
        if outcome.cause == RETRIED_CAUSE:
            # Its output refused by its schema: the call is made once more, and both recorded.
            spent = DecompositionCall(session_id=outcome.session_id, usage=outcome.usage)
            retried = (RetriedCall(round=1, call=spent, detail=outcome.detail or RETRIED_CAUSE),)
            outcome = make_call(
                brief,
                workdir=retry_dir(run_dir, 1),
                # The brief's prompt as it was, and, where a unit of the plan was refused, why.
                prompt=retry_prompt(brief, sorted(config.models.roles), None, outcome),
                session_id=str(uuid.uuid4()),
            )
        found = start_run(
            outcome,
            config=config,
            run_dir=run_dir,
            target_repo=target_repo,
            library=library,
            brief=brief,
            retried=retried,
        )
        return RoundsOutcome(found, outcome.ok, outcome.cause, outcome.detail, None)
    loop = _Loop(
        config, run_dir, target_repo, library, reviewing, check, make_call, time.monotonic()
    )
    if isinstance(reviewing[0], RecordsSpawns):
        # The review's spawn is on no run record before the opening: it is written beside the
        # rounds, so a command after a kill during the review finds the session and stops it.
        reviewing[0].record_spawns(
            review_spawned(run_dir, review_root=review_root, canaries=config.held_out_canaries)
        )
    last = replans(config.design_review) + 1
    earlier: list[EarlierRound] = []
    proposals: list[Proposal] = []
    retried_calls: list[RetriedCall] = []
    prompt: str | None = None
    k = 0
    while True:
        k += 1
        session, (started, began) = str(uuid.uuid4()), loop.now()
        first = k == 1
        _append(
            run_dir / ROUNDS_JOURNAL,
            RoundStarted(
                round=k,
                session_id=session,
                started=started,
                design_review=config.design_review if first else None,
                decomposition_model=config.models.decomposition if first else None,
                brief_sha256=config.brief_sha256 if first else None,
            ),
        )
        try:
            ran = _one_round(brief, k, loop=loop, prompt=prompt, session=session)
        except (OrchestratorError, ReviewError) as exc:
            loop.end(k, "void", "infrastructure", _cause(exc), str(exc))
            # The void line is journalled: the review, if one ran, is over on the record.
            review_over(run_dir)
            raise
        outcome, ending, plan = ran.outcome, ran.ending, ran.outcome.plan
        digest = plan_sha256(plan) if plan is not None and ending.plan_class == "plan" else None
        if plan is not None and digest is not None:
            _synced(plan_path(run_dir, k), plan_bytes(plan), "wb")
        fields = RoundReview.model_fields
        review = (
            None
            if ran.reviewed is None
            else RoundReview(**{n: getattr(ran.reviewed, n) for n in fields})
        )
        ended, done = loop.now()
        call_ended, timed = ran.call_ended[0], ran.review_started
        review_started, review_began = (None, None) if timed is None else timed
        _append(
            run_dir / ROUNDS_JOURNAL,
            RoundEnded(
                round=k,
                ending=ending,
                session_id=outcome.session_id,
                model=outcome.model,
                num_turns=outcome.num_turns,
                usage=outcome.usage,
                plan_sha256=digest,
                detail=ran.detail,
                review=review,
                started=started,
                ended=ended,
                call_ended=call_ended,
                review_started=review_started,
                elapsed=Elapsed(
                    started=began,
                    call_ended=ran.call_ended[1],
                    review_started=review_began,
                    ended=done,
                ),
            ),
        )
        # The round's end is journalled with what its review came to: its record goes now.
        review_over(run_dir)
        refused_first = ran.refused
        if refused_first is not None and ran.refused_ended is not None:
            spent_first = DecompositionCall(
                session_id=refused_first.session_id, usage=refused_first.usage
            )
            retried_calls.append(
                RetriedCall(round=k, call=spent_first, detail=refused_first.detail or RETRIED_CAUSE)
            )
            proposals.append(
                Proposal(
                    round=k,
                    session_id=refused_first.session_id,
                    model=refused_first.model,
                    num_turns=refused_first.num_turns,
                    plan_sha256=None,
                    cause=RETRIED_CAUSE,
                    started=started,
                    ended=ran.refused_ended,
                    review_started=None,
                    review_ended=None,
                )
            )
        proposals.append(
            Proposal(
                call=2 if refused_first is not None else 1,
                round=k,
                session_id=outcome.session_id,
                model=outcome.model,
                num_turns=outcome.num_turns,
                plan_sha256=digest,
                cause=None if digest is not None else str(ending.plan_cause),
                started=started,
                ended=call_ended,
                review_started=review_started,
                review_ended=ended if review_started is not None else None,
            )
        )
        follows = what_follows(ending, last=k == last, holds=config.design_review != "observe")
        cls, cause = _what_ended(ending)
        if (
            follows == "replan"
            and plan is not None
            and digest is not None
            and ran.reviewed
            and ran.findings
        ):
            spent = DecompositionCall(session_id=outcome.session_id, usage=outcome.usage)
            earlier.append(EarlierRound(call=spent, reviewed=ran.reviewed, plan_sha256=digest))
            prompt = replan_prompt(
                brief,
                sorted(config.models.roles),
                plan,
                ran.findings,
                parts=config.parts_on_hand == "on",
            )
            continue
        if follows in ("void", "replan"):
            loop.end(k, "void", cls, cause, ran.detail)
            msg = f"round {k} of the decomposition ended void ({cls}: {cause}): no run is started"
            raise DecompositionError(msg, round=str(k), cause=cause, detail=ran.detail)
        refused = f"{cause}: {ran.detail}" if follows == "fail_run" and outcome.ok else None
        try:
            found = start_run(
                outcome,
                config=config,
                run_dir=run_dir,
                target_repo=target_repo,
                library=library,
                brief=brief,
                reviewed=ran.reviewed if refused is None else None,
                earlier=tuple(earlier),
                refused=refused,
                proposals=tuple(proposals),
                retried=tuple(retried_calls),
            )
        except OrchestratorError as exc:
            loop.end(k, "void", "infrastructure", _cause(exc), str(exc))
            raise
        loop.end(k, follows, cls, cause, ran.detail)
        # What was written is what the rounds write, read back.
        read_journal(run_dir, last=last, holds=config.design_review != "observe")
        ok = refused is None and outcome.ok
        return RoundsOutcome(
            found, ok, cause if refused else outcome.cause, ran.detail, ran.reviewed
        )
