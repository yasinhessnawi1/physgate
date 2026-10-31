"""The rounds of a reviewed decomposition: each call, its plan's start check and its review.

A run that reviews its plan makes round 1's call as every run does. Under ``repair:N`` a verdict
other than a pass is followed by a re-plan, at most N times: a call told the brief's prompt, the
plan and the review's findings (:func:`replan_prompt`), in its own directory, and reviewed again.
What follows each round is decided by its ending alone and by whether it is round N + 1
(:func:`what_follows`), so a ``repair:N`` run's rounds are, as a prefix, those of every shorter one.

Each round is journalled as it goes, every line synced where it is written: a start line before
its call, an end line when it ends (its ending, the call's session and spending, the plan's digest
or why there is none, its review), its plan in its own file, and one terminal line naming the round
the rounds ended on, how, and what followed. So whatever a later round does, the earlier rounds
are kept; a killed decomposition leaves the rounds that ended, and is never resumed
(:func:`require_fresh` refuses its directory). A run that does not review its plan makes its one
call and writes none of this.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from physgate.flags import replans
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.common import NonEmptyStr, utc_now, utc_stamp
from physgate.orchestrator.decompose import (
    ROUNDS_JOURNAL,
    Outcome,
    ReplanFindings,
    canary_in_findings,
    replan_findings,
    replan_prompt,
    require_startable,
    start_run,
)
from physgate.orchestrator.endings import (
    Canary,
    PlanCause,
    ReviewCause,
    RoundEnding,
    round_ending,
    what_follows,
)
from physgate.orchestrator.events import DesignUnavailable, Sha256
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
from physgate.orchestrator.protocols import MessageUsage, PlanReviewer, PlanUnderReview
from physgate.orchestrator.queue import DECOMPOSITION_NAME, STREAM_NAME
from physgate.orchestrator.record import (
    DecompositionCall,
    EarlierRound,
    PlanReviewed,
    ReviewInstall,
    RoundReview,
    RunRecord,
)
from physgate.orchestrator.run_config import RunConfig
from physgate.reviewers.exceptions import ReviewError

#: What a round's ending class is, plan or review, as the terminal line names it.
EndingClass = Literal["plan", "no_plan", "infrastructure", "verdict", "unavailable", "exposure"]


class _Line(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    round: Annotated[int, Field(ge=1)]


class RoundStarted(_Line):
    """A round begun: written before its call, naming the session the call is made as."""

    kind: Literal["round_started"] = "round_started"
    session_id: NonEmptyStr
    started: NonEmptyStr


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
    started: NonEmptyStr
    ended: NonEmptyStr


class RoundsEnded(_Line):
    """The rounds' end: the round they ended on, its class and cause, and what followed."""

    kind: Literal["rounds_ended"] = "rounds_ended"
    follows: Literal["start", "fail_run", "void"]
    ending_class: EndingClass
    cause: NonEmptyStr
    detail: str


JournalLine = Annotated[RoundStarted | RoundEnded | RoundsEnded, Field(discriminator="kind")]
_LINE: TypeAdapter[JournalLine] = TypeAdapter(JournalLine)


class MakeCall(Protocol):
    """One decomposition call, as :func:`physgate.orchestrator.decompose.call` makes it."""

    def __call__(
        self, brief: str, *, workdir: Path, prompt: str | None, session_id: str
    ) -> Outcome:
        """Make the call in ``workdir`` as ``session_id``, sent ``prompt`` or the brief's."""
        ...


@dataclass(frozen=True)
class Decomposed:
    """The run the rounds started, whether from a plan, why not, and its last round's review."""

    record: RunRecord
    ok: bool
    cause: str | None
    detail: str
    reviewed: PlanReviewed | None


def round_dir(run_dir: Path, k: int) -> Path:
    """Where round k's call runs: the decomposition's directory for round 1, its own after."""
    base = run_dir / DECOMPOSITION_NAME
    return base if k == 1 else base / f"round-{k}"


def plan_path(run_dir: Path, k: int) -> Path:
    """Round k's plan file: the canonical bytes its digest is taken over."""
    return run_dir / DECOMPOSITION_NAME / f"round-{k}" / "plan.json"


def _synced(path: Path, data: bytes, mode: Literal["ab", "wb"]) -> None:
    """Write ``data`` to ``path`` and sync it before returning: a kill after keeps it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _append(journal: Path, line: RoundStarted | RoundEnded | RoundsEnded) -> None:
    _synced(journal, line.model_dump_json().encode() + b"\n", "ab")


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read_journal(run_dir: Path) -> tuple[RoundStarted | RoundEnded | RoundsEnded, ...]:
    """The round journal, held to how the rounds write it.

    Rounds run from 1, each a start then an end, but the last, which may only have started (a kill,
    or a void its call or review raised); one terminal line ends it, naming that round; each ended
    round's plan file digests to its line's ``plan_sha256``.

    Raises:
        RunStateError: the journal is missing, a line is not a journal line, a plan file is not
            what its line names, or the lines are not in the order the rounds write them.
    """
    try:
        lines = tuple(
            _LINE.validate_json(one) for one in (run_dir / ROUNDS_JOURNAL).read_bytes().splitlines()
        )
    except (OSError, ValidationError) as exc:
        msg = "the round journal is missing, or a line of it is not one the rounds write"
        raise RunStateError(msg, run_dir=str(run_dir), cause="record_missing") from exc
    k, session, terminal = 0, "", False
    for line in lines:
        cause = "record_missing"
        if isinstance(line, RoundStarted):
            ok, k, session = (
                not terminal and not session and line.round == k + 1,
                k + 1,
                line.session_id,
            )
        elif isinstance(line, RoundEnded):
            ok = not terminal and line.round == k and line.session_id == session
            session = ""
            if (
                ok
                and line.plan_sha256 is not None
                and _digest(plan_path(run_dir, k)) != line.plan_sha256
            ):
                ok, cause = False, "plan_digest_mismatch"
        else:
            ok = (
                not terminal
                and k > 0
                and line.round == k
                and (not session or line.follows == "void")
            )
            terminal = True
        if not ok:
            msg = "the round journal is not what the rounds write, in the order they write it"
            raise RunStateError(msg, run_dir=str(run_dir), round=str(line.round), cause=cause)
    return lines


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
    if cause is None:
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
    # No budget is set on the designer's call (its argv names none), so a spent one is never its.
    ending = round_ending(cause, review_cause, budget_set=False, canary=canary)
    return _Ran(outcome, ending, detail, reviewed, findings)


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
) -> Decomposed:
    """Decompose in rounds and start the run the last round leads to.

    Raises:
        DecompositionError: the rounds ended void: no run is started, and the journal says why.
        OrchestratorError: the call, the review or the start raised it; the journal's terminal
            line names it, and no run is started.
    """
    if reviewing is None:  # one call, no review, nothing journalled
        outcome = make_call(
            brief, workdir=round_dir(run_dir, 1), prompt=None, session_id=str(uuid.uuid4())
        )
        found = start_run(
            outcome,
            config=config,
            run_dir=run_dir,
            target_repo=target_repo,
            library=library,
            brief=brief,
        )
        return Decomposed(found, outcome.ok, outcome.cause, outcome.detail, None)
    loop = _Loop(config, run_dir, target_repo, library, reviewing, check, make_call)
    last = replans(config.design_review) + 1
    earlier: list[EarlierRound] = []
    prompt: str | None = None
    k = 0
    while True:
        k += 1
        session, started = str(uuid.uuid4()), utc_stamp(utc_now())
        _append(
            run_dir / ROUNDS_JOURNAL, RoundStarted(round=k, session_id=session, started=started)
        )
        try:
            ran = _one_round(brief, k, loop=loop, prompt=prompt, session=session)
        except (OrchestratorError, ReviewError) as exc:
            loop.end(k, "void", "infrastructure", _cause(exc), str(exc))
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
                ended=utc_stamp(utc_now()),
            ),
        )
        follows = what_follows(ending, last=k == last, holds=config.design_review != "observe")
        cls, cause = (
            ending.review_class or ending.plan_class,
            str(ending.review_cause or ending.plan_cause),
        )
        if (
            follows == "replan"
            and plan is not None
            and digest is not None
            and ran.reviewed
            and ran.findings
        ):
            spent = DecompositionCall(session_id=outcome.session_id, usage=outcome.usage)
            earlier.append(EarlierRound(call=spent, reviewed=ran.reviewed, plan_sha256=digest))
            prompt = replan_prompt(brief, sorted(config.models.roles), plan, ran.findings)
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
            )
        except OrchestratorError as exc:
            loop.end(k, "void", "infrastructure", _cause(exc), str(exc))
            raise
        loop.end(k, follows, cls, cause, ran.detail)
        read_journal(run_dir)  # what was written is what the rounds write, read back
        ok = refused is None and outcome.ok
        return Decomposed(found, ok, cause if refused else outcome.cause, ran.detail, ran.reviewed)
