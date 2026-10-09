"""The paired-versus-generalist review ratio: what pairing costs, measured on one artefact.

ARCH-063 says pairing roughly doubles review spend, because each pair carries its
own domain knowledge. This measures exactly that, once: a finished run's paired
review of one attempt is taken as it was recorded, and the same attempt is
reviewed again by the same reviewer implementation on the same model, effort and
bounds, with the role's promoted rubric less its two domain sections
(``rubric.generalist_of``) and a packet without the role's own library files.

The attempt is the one the paired review read: its packet record names it, and
the record is held to the digest the review line carries. The generalist review
writes its own run-event log in its own directory (``run_started``,
``subtask_planned``, the tokens, ``review_ran``), the instrument's shape. The ratio
is then read from the two review lines alone, and refused unless both read the
same trajectory, under the same seal, at the same commit, on the same model.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.observe.cost import DatedSheet
from physgate.evaluation.observe.exceptions import ManifestError
from physgate.evaluation.observe.manifest import Sha256, read_run_events
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator.budget import infra_retry_delay
from physgate.orchestrator.common import ModelString, NonEmptyStr
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import (
    EventLog,
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SubtaskPlanned,
    TokensUsed,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import ReviewResult, Usage
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.orchestrator.trajectory import Seal
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.packet import RECORD_NAME, Packet
from physgate.reviewers.places import review_dir
from physgate.reviewers.rubric import generalist_of, load_rubric

CONFIG_NAME = "generalist.json"
EVENTS_NAME = "events.jsonl"
BASELINE_NAME = "baseline.json"
_ZERO = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class GeneralistConfig(_Frozen):
    """What one generalist review was, recorded before it runs."""

    run_id: NonEmptyStr
    paired_run_id: NonEmptyStr
    #: The paired run's configuration digest, as its first event line carries it.
    paired_config_sha256: Sha256
    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    paired_review_session: NonEmptyStr
    paired_packet_sha256: Sha256
    paired_rubric_sha256: Sha256
    generalist_rubric_sha256: Sha256
    reviewer_model: ModelString
    claude_version: NonEmptyStr
    effort: NonEmptyStr
    max_output_tokens: Annotated[int, Field(gt=0)]


class ReviewCost(_Frozen):
    """One review's spend, priced."""

    rubric_kind: Literal["paired", "generalist"]
    session_id: NonEmptyStr
    tokens: Usage
    usd: Decimal
    nok: Decimal
    peak_context_tokens: Annotated[int, Field(ge=0)] | None


class Ratio(_Frozen):
    """Paired over generalist, on one attempt read under one seal: n = 1."""

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    trajectory_seal: Seal
    attempt_commit: NonEmptyStr
    reviewer_model: ModelString
    paired: ReviewCost
    generalist: ReviewCost
    token_ratio: Decimal
    usd_ratio: Decimal
    prices_date: NonEmptyStr
    prices_sha256: Sha256
    n: Literal[1] = 1


def _sum(result: ReviewResult) -> Usage:
    total = _ZERO
    for message in result.usage:
        total = Usage(
            **{f: getattr(total, f) + getattr(message.usage, f) for f in Usage.model_fields}
        )
    return total


def paired_review(run_dir: Path, subtask_id: str, attempt: int) -> tuple[ReviewRan, str]:
    """The paired review line of ``subtask_id``'s ``attempt``, and the run's config digest.

    Raises:
        ManifestError: the run recorded no paired review of that attempt.
    """
    events = read_run_events(run_dir)
    started = events[0]
    if not isinstance(started, RunStarted):
        msg = "the run's log does not begin with its start"
        raise ManifestError(msg, run_dir=str(run_dir))
    found = [
        e
        for e in events
        if isinstance(e, ReviewRan)
        and e.subtask_id == subtask_id
        and e.attempt == attempt
        and e.result.rubric_kind == "paired"
    ]
    if not found:
        msg = "the run recorded no paired review of this attempt"
        raise ManifestError(msg, subtask=subtask_id, attempt=str(attempt))
    return found[-1], started.config_sha256


def read_packet(review_root: Path, result: ReviewResult) -> Packet:
    """The packet record a review read, held to the digest its review line carries.

    Raises:
        ManifestError: the record is missing, or is not the one the line names.
    """
    path = review_dir(review_root, result.session_id) / RECORD_NAME
    if not path.is_file():
        msg = "the review's packet record is not where its review root keeps it"
        raise ManifestError(msg, path=str(path))
    packet = Packet.model_validate_json(path.read_bytes())
    if packet.sha256() != result.packet_sha256:
        msg = "the packet record is not the one the review line names"
        raise ManifestError(msg, path=str(path), recorded=str(result.packet_sha256))
    return packet


def review_ratio(
    paired: tuple[ReviewResult, Packet],
    generalist: tuple[ReviewResult, Packet],
    prices: DatedSheet,
) -> Ratio:
    """Paired over generalist tokens and cost, from the two review lines and their packets.

    Raises:
        ManifestError: the two are not one paired and one generalist review on the
            same model, of the same attempt read under the same seal at the same
            commit; or either spent nothing; or the sheet does not price the model.
    """
    (p_result, p_packet), (g_result, g_packet) = paired, generalist
    if (p_result.rubric_kind, g_result.rubric_kind) != ("paired", "generalist"):
        msg = "a ratio is one paired review over one generalist review"
        raise ManifestError(msg, paired=str(p_result.rubric_kind), other=str(g_result.rubric_kind))
    if p_result.reviewer_model != g_result.reviewer_model:
        msg = "the two reviews ran on different models"
        raise ManifestError(msg, paired=p_result.reviewer_model, other=g_result.reviewer_model)
    if p_packet.trajectory_seal != g_packet.trajectory_seal:
        msg = "the two reviews read the trajectory under different seals"
        raise ManifestError(msg)
    if p_packet.artefact is None or g_packet.artefact is None:
        msg = "a packet record does not name the attempt it was built from"
        raise ManifestError(msg)
    a, b = p_packet.artefact, g_packet.artefact
    if (a.subtask_id, a.attempt, a.attempt_commit) != (b.subtask_id, b.attempt, b.attempt_commit):
        msg = "the two reviews are not of the same attempt at the same commit"
        raise ManifestError(msg, paired=a.attempt_commit, other=b.attempt_commit)
    price = prices.sheet.usd_per_mtok.get(p_result.reviewer_model)
    if price is None:
        msg = "the price sheet has no price for the reviewer model"
        raise ManifestError(msg, model=p_result.reviewer_model, date=prices.sheet.date)
    rate = prices.sheet.exchange.usd_to_nok

    def cost(result: ReviewResult) -> ReviewCost:
        tokens = _sum(result)
        usd = price.usd(tokens)
        return ReviewCost(
            rubric_kind=result.rubric_kind or "paired",
            session_id=result.session_id,
            tokens=tokens,
            usd=usd,
            nok=usd * rate,
            peak_context_tokens=result.peak_context_tokens,
        )

    p_cost, g_cost = cost(p_result), cost(g_result)
    if g_cost.tokens.total() == 0 or g_cost.usd == 0:
        msg = "the generalist review spent nothing, so there is no ratio"
        raise ManifestError(msg)
    return Ratio(
        subtask_id=a.subtask_id,
        attempt=a.attempt,
        trajectory_seal=p_packet.trajectory_seal,
        attempt_commit=a.attempt_commit,
        reviewer_model=p_result.reviewer_model,
        paired=p_cost,
        generalist=g_cost,
        token_ratio=Decimal(p_cost.tokens.total()) / Decimal(g_cost.tokens.total()),
        usd_ratio=p_cost.usd / g_cost.usd,
        prices_date=prices.sheet.date,
        prices_sha256=prices.sha256,
    )


def review_retried_once(
    review: Callable[[], ReviewResult],
    log: EventLog,
    *,
    subtask_id: str,
    attempt: int,
    delays: tuple[float, ...],
    sleep: Callable[[float], None],
) -> ReviewResult:
    """The review's verdict, with one retry for an infrastructure cause, as the loop's review.

    An infrastructure end (an API error, no result, the wall clock) is retried once, with
    a fresh session, after ``delays``' first entry (at once if there is none). A refused or
    invalid verdict, an unfinished reading, a compaction or an overflow is final at once:
    a fresh session would repeat it. Every try's tokens and its ``review_unavailable``
    line, with whether it is retried, are logged before anything else happens.

    Raises:
        ReviewUnavailableError: the last try's, when no verdict came.
    """
    retried = False
    while True:
        try:
            return review()
        except ReviewUnavailableError as exc:
            for message in exc.usage:
                log.append(
                    TokensUsed(
                        **log.envelope(),
                        attribution=f"reviewer:{exc.session_id or 'none'}",
                        message_id=message.message_id,
                        usage=message.usage,
                    )
                )
            retry = exc.cause == "infrastructure" and not retried
            log.append(
                ReviewUnavailable(
                    **log.envelope(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    cause=exc.cause,
                    detail=str(exc) or exc.cause,
                    retry=retry,
                    session_id=exc.session_id,
                    reviewer_model=exc.reviewer_model,
                    spec_defects=exc.spec_defects,
                )
            )
            if not retry:
                raise
            retried = True
            sleep(infra_retry_delay(delays, 0) or 0.0)


def run_generalist(
    *,
    run_dir: Path,
    subtask_id: str,
    attempt: int,
    out: Path,
    run_id: str,
    review_root: Path,
    target: Path,
    install_bin: Path,
    binary: str,
    base_url: str | None,
    credential: Credential,
    library: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[ReviewRan, Packet]:
    """Review the paired review's attempt again, as a generalist, into ``out``.

    The review is retried once for an infrastructure cause, as the loop's own review is,
    after the first delay of the paired run's infrastructure retry schedule (at once if
    the schedule is empty); any other cause is final at once (:func:`review_retried_once`).

    Raises:
        ManifestError: as :func:`paired_review` and :func:`read_packet`; the
            packet names no attempt; ``out`` is not new; or the role's promoted
            rubric is not the one the paired review judged with.
        ReviewUnavailableError: the generalist review is not a verdict, after its one
            retry if its cause was infrastructure; every try is recorded in ``out``'s
            log first.
    """
    config: RunConfig = load_run_config(run_dir / "run.json")
    paired, config_sha256 = paired_review(run_dir, subtask_id, attempt)
    packet = read_packet(review_root, paired.result)
    artefact = packet.artefact
    if artefact is None:
        msg = "the paired review's packet does not name the attempt it read"
        raise ManifestError(msg, session=paired.result.session_id)
    role = artefact.assigned_role
    rubric = load_rubric(library / KNOWLEDGE_ROOT, role)
    if rubric.sha256 != paired.result.rubric_sha256:
        msg = "the role's promoted rubric is not the one the paired review judged with"
        raise ManifestError(msg, role=role, paired=str(paired.result.rubric_sha256))
    generalist = generalist_of(rubric)
    if Path(out).exists():
        msg = "a generalist review is written into a directory of its own, new"
        raise ManifestError(msg, out=str(out))
    out.mkdir(parents=True)
    record = GeneralistConfig(
        run_id=run_id,
        paired_run_id=config.run_id,
        paired_config_sha256=config_sha256,
        subtask_id=subtask_id,
        attempt=attempt,
        paired_review_session=paired.result.session_id,
        paired_packet_sha256=str(paired.result.packet_sha256),
        paired_rubric_sha256=rubric.sha256,
        generalist_rubric_sha256=generalist.sha256,
        reviewer_model=paired.result.reviewer_model,
        claude_version=config.claude_version,
        effort=config.effort,
        max_output_tokens=config.max_output_tokens,
    )
    raw = (json.dumps(record.model_dump(mode="json"), indent=1, sort_keys=True) + "\n").encode()
    (out / CONFIG_NAME).write_bytes(raw)
    setup = ReviewerSetup.of_run(
        config.model_copy(update={"run_id": run_id}),
        review_root=review_root,
        repo=target,
        install_bin=install_bin,
        binary=binary,
        base_url=base_url,
        credential=credential,
        library=library,
    )
    reviewer = ClaudeReviewer(role=role, setup=setup, rubric=generalist)
    log = EventLog(out / EVENTS_NAME, run_id=run_id, gate_mode=config.gate_mode)
    try:
        log.append(RunStarted(**log.envelope(), config_sha256=hashlib.sha256(raw).hexdigest()))
        log.append(
            SubtaskPlanned(
                **log.envelope(),
                subtask_id=subtask_id,
                spec_path=artefact.issued_spec.path if artefact.issued_spec else "-",
                assigned_role=role,
                module_dir="-",
            )
        )
        result = review_retried_once(
            lambda: reviewer.review(artefact),
            log,
            subtask_id=subtask_id,
            attempt=attempt,
            delays=config.bounds.infra_retry_delays_s,
            sleep=sleep,
        )
        for message in result.usage:
            log.append(
                TokensUsed(
                    **log.envelope(),
                    attribution=f"reviewer:{result.session_id}",
                    message_id=message.message_id,
                    usage=message.usage,
                )
            )
        ran = log.append(
            ReviewRan(**log.envelope(), subtask_id=subtask_id, attempt=attempt, result=result)
        )
    finally:
        log.close()
    return ran, read_packet(review_root, result)
