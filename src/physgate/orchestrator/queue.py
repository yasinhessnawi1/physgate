"""The approval queue: what a person decides, with what they need to decide it.

Two append-only files per run. The items file is written only by the
orchestrator, between sessions. An item carries the five things ARCH-130
names: the decision required, the artefact diff, the finding that triggered it,
the most relevant quantities (at most three), and a link to every trajectory
involved.

A person's decision goes into its own file, because a person decides while a
session may be running. The items file is put back by the hook layer if it
changes during a session; the decisions file is only refused to the session's
tools, so a decision appended by ``physgate queue resolve`` meanwhile stands.
Each decision names an open item. Nothing is ever edited, so the two files say
what was asked, what was decided, and when. Every decision is written by one
function, :func:`record_decision`, under a lock on the decisions file, so two
people deciding at once cannot both find an item open.

The item's wording is a template filled by code. The queue is where a model
would be most tempting, since it is prose for a person, and there is none.

**Reading is not writing.** :class:`ApprovalQueue` is the one writer: opening it
creates the files it writes and cuts a torn final line. Anything that only reads
(``physgate queue list``, the operator UI) goes through :func:`read_queue` and
:func:`queue_listing`, which create nothing and cut nothing, and hold every line
to exactly the rules the writer holds it to, through the same parser.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import os
import re
import stat
import time
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_serializer,
    model_validator,
)

from physgate.orchestrator.arbitration import Held, Standing
from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.common import (
    NonEmptyStr,
    Timestamp,
    first_problem,
    utc_now,
    utc_stamp,
)
from physgate.orchestrator.escalation import CONFIDENCE_FLOOR, Decision
from physgate.orchestrator.events import (
    ContractRuled,
    ContractTested,
    ContractValue,
    DecisionTaken,
    Event,
    LeftoverRead,
    OsLayerChecked,
    Position,
    SessionEnded,
    StageEntered,
    parse_events,
    read_jsonl,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, QueueError, StaleViewError
from physgate.orchestrator.protocols import GateResult, IndicatorKind, QuantityRef, SpecDefect
from physgate.orchestrator.repair import Finding, Writer, held_line
from physgate.orchestrator.trajectory import Seal, seal
from physgate.reviewers.scan import ScanHit

#: The queue's sources (ARCH-130); a blocked review and one with no verdict are kept apart,
#: and a subtask the escalation decision sent to a person while it had attempts left is its
#: own source: no rule forced it there, a backend's answer or its confidence did (ARCH-131).
QueueSource = Literal[
    "gate_escalation",
    "repair_budget_exhausted",
    "review_unavailable",
    "review_blocked",
    "arbitration",
    "escalation_decision",
    "contract",
]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_id: NonEmptyStr
    ts: Timestamp


#: What approving an item does: merge the attempt it names, or record the decision only.
OnApprove = Literal["merge_attempt", "record_only"]
#: What rejecting an item does: start the next attempt from the note, order the one fix a
#: blocked review gets, end the subtask, or record the decision only.
OnReject = Literal["retry", "fix", "end_subtask", "record_only"]
#: Why approving an item records only. ``gate``, ``change_check`` and ``reading``: an automated
#: check refused the attempt, and a person overrides the reviewer alone. ``indicator_in_history``:
#: a review of some attempt of the subtask confirmed a reward-hacking indicator.
#: ``scan_hit``: the scan that runs before review found one, and no review judged it.
#: ``source``: the item's source is not one an approve merges from (an integration failure, an
#: arbitration). ``legacy``: the item was written before items said what a verb does.
WhyRecordOnly = Literal[
    "gate", "change_check", "reading", "indicator_in_history", "scan_hit", "source", "legacy"
]
Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
#: What choosing a position does: order the next attempt to the graph's value, order the one fix
#: to it, end the subtask, resize (the subtask waits for sizing's closing pass, ordered to write
#: the domain's value, then returns to the gate), or record the decision only.
OnChoose = Literal["retry", "fix", "end_subtask", "resize", "record_only"]
#: The positions each kind of item offers, in the order the item states them: an arbitration's
#: sizing (the graph's value stands) and domain (the disputing subtask's); a failed contract's
#: producer and consumer (whose merged work stands). No other kind offers any.
POSITIONS: Mapping[QueueSource, tuple[Position, ...]] = {
    "arbitration": ("sizing", "domain"),
    "contract": ("producer", "consumer"),
}


class ConfirmedIndicator(BaseModel):
    """A reward-hacking indicator a review of the subtask confirmed: which attempt, which kind."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    attempt: Annotated[int, Field(ge=1)]
    kind: IndicatorKind


class ItemConsequence(BaseModel):
    """What each verb will do to an item, and why approve records only when it does (ARCH-133).

    Computed by code from the run's event log when the item is listed, and part of the item's
    line, so a decision bound to the line's digest is bound to this too. The loop computes it
    again when it takes the decision; an item that says otherwise than the log halts the run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The attempt the item concerns, and the commit that attempt's change check checked: the
    #: only commit an approve may merge. ``None`` for an item about no one attempt.
    attempt: Annotated[int, Field(ge=1)] | None
    attempt_commit: Sha1 | None
    on_approve: OnApprove
    on_reject: OnReject
    why_record_only: WhyRecordOnly | None
    #: Every indicator a review of any attempt of the subtask confirmed, oldest first.
    confirmed_indicators: tuple[ConfirmedIndicator, ...]
    #: What the scan before review found in the attempt's sealed streams, for an item whose
    #: review never judged them; empty otherwise. Every field is written out: a line that
    #: leaves one out is not one the orchestrator wrote, and is refused rather than read as none.
    scan_hits: tuple[ScanHit, ...]
    #: What choosing each position does, for an item whose kind offers positions; left out of
    #: every other item's line, so it is written exactly as before positions existed.
    on_choose: dict[Position, OnChoose] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_choice(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.on_choose is None:
            data.pop("on_choose", None)
        return data

    @model_validator(mode="after")
    def _approve_says_what_it_merges_or_why_it_does_not(self) -> ItemConsequence:
        merges = self.on_approve == "merge_attempt"
        if merges == (self.why_record_only is not None):
            msg = "approve merges with no reason not to, or records only and says why"
            raise ValueError(msg)
        if merges and (self.attempt is None or self.attempt_commit is None):
            msg = "an approve that merges names the attempt and the commit it merges"
            raise ValueError(msg)
        return self


class QueueItem(_Record):
    """One decision a person has to take."""

    kind: Literal["item"] = "item"
    run_id: NonEmptyStr
    subtask_id: NonEmptyStr
    source: QueueSource
    decision_required: NonEmptyStr
    artefact_diff: str
    triggering_finding: NonEmptyStr
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]
    trajectories: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    #: What each verb will do. ``None`` on an item written before items said so, or by a run
    #: that only records decisions; either is taken as recording only.
    consequence: ItemConsequence | None = None

    @model_validator(mode="after")
    def _the_positions_are_its_kind_s(self) -> QueueItem:
        # Held in the set's own order: a dict keeps the order it was read in, so a line with the
        # positions reordered would otherwise read, and write back, in a form no writer wrote.
        stated = None if self.consequence is None else self.consequence.on_choose
        if stated is not None and tuple(stated) != POSITIONS.get(self.source):
            msg = "an item states the positions its kind offers, in their order, and no others"
            raise ValueError(msg)
        if stated is None and self.consequence is not None and self.source in POSITIONS:
            msg = "an item whose kind offers positions states what choosing each does"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_consequence(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Left out when absent, so an item with none is written exactly as before it existed.
        data: dict[str, Any] = handler(self)
        if self.consequence is None:
            data.pop("consequence", None)
        return data


#: The words a person decides with, mapped onto the free-text decision.
Verb = Literal["approve", "reject", "choose"]


def position_problem(verb: Verb | None, position: Position | None) -> str | None:
    """Why ``position`` cannot go with ``verb``, or ``None``: a position goes with choose alone."""
    if (verb == "choose") != (position is not None):
        return "a position is chosen with choose, and only with it"
    return None


#: The longest note a person's decision carries, in characters: a bound on what reaches a
#: session's prompt, and so a size, not a threshold on anything measured.
MAX_NOTE = 4000
#: The most lines a note holds. With :data:`MAX_NOTE` it keeps the longest note, quoted into the
#: one fix's instruction and again into what that fix's reviewer is told, inside what one read of
#: the review packet shows whole (2,000 lines, 20,000 bytes): a note can never be what makes
#: an order unreadable. A size, like the cap on characters.
MAX_NOTE_LINES = 200

#: Control characters a note may not hold: every C0 control but the tab and the line break,
#: the delete character, and the C1 controls. A note is quoted into a session's prompt, where an
#: escape sequence or a carriage return could make it read as something it is not.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
#: A run of three of the quotation's own fence characters. The note is quoted between fences
#: made longer than any run it holds, so a note made of them would stretch its fences without
#: bound; it holds none, and its quotation stays the size of the note.
_FENCE = re.compile(r"<<<|>>>")


def note_problem(note: str) -> str | None:
    """Why ``note`` cannot be a person's note, or ``None`` if it can.

    One rule for every place a note is held to: where a decision is made, and where a decision
    line is read, so a line the writer would refuse is never read as one it wrote (ARCH-133).
    Besides its size and the control characters, a note holds no Unicode format character (a
    bidirectional override or isolate, a zero-width character, a byte-order mark) and no line or
    paragraph separator: each makes the text a reader sees differ from the text a session reads.
    """
    if not note.strip():
        return "a note says something; leave it out rather than send it blank"
    if len(note) > MAX_NOTE:
        return f"a note is at most {MAX_NOTE} characters"
    if note.count("\n") >= MAX_NOTE_LINES:
        return f"a note is at most {MAX_NOTE_LINES} lines"
    if _CONTROL.search(note):
        return "a note holds no control character but a tab or a line break"
    if any(unicodedata.category(char) in ("Cf", "Zl", "Zp") for char in note):
        return "a note holds no format character, and no line or paragraph separator"
    if _FENCE.search(note):
        return "a note holds no run of three '<' or '>', which its quotation is fenced with"
    return None


class QueueResolution(_Record):
    """A person's decision on one item.

    ``verb``, ``note`` and ``shown_sha256`` are written for a decision taken with a verb on a
    view of the item (ARCH-133); a free-text decision, and every line written before they
    existed, carries none of them and binds to nothing.
    """

    kind: Literal["resolution"] = "resolution"
    decision: NonEmptyStr
    resolved_by: NonEmptyStr
    verb: Verb | None = None
    position: Position | None = None
    note: NonEmptyStr | None = None
    shown_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None

    @model_validator(mode="after")
    def _one_meaning(self) -> QueueResolution:
        # The free text is what every reader of the file reads, and the verb is what the run
        # acts on: one line may not say two things. A verb comes with the digest of the view it
        # was taken on and its text is exactly the verb's; with no verb, nothing binds.
        if (problem := position_problem(self.verb, self.position)) is not None:
            raise ValueError(problem)
        if self.verb is None:
            if self.note is not None or self.shown_sha256 is not None:
                msg = "a note or a view's digest belongs to a decision with a verb"
                raise ValueError(msg)
            return self
        if self.shown_sha256 is None:
            msg = "a decision with a verb names the digest of the view it was taken on"
            raise ValueError(msg)
        if self.verb == "reject" and self.note is None:
            msg = "a rejection carries its note"
            raise ValueError(msg)
        if self.note is not None and (problem := note_problem(self.note)) is not None:
            raise ValueError(problem)
        said = self.verb if self.position is None else f"{self.verb} {self.position}"
        if self.decision != (said if self.note is None else f"{said}: {self.note}"):
            msg = "a decision's text is exactly its verb, position and note"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_unbound_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name in ("verb", "position", "note", "shown_sha256"):
            if data.get(name) is None:
                data.pop(name, None)
        return data


class PersonDecision(BaseModel):
    """A person's decision with a verb: what the decision function binds to a view."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    verb: Verb
    note: Annotated[str, StringConstraints(max_length=MAX_NOTE)] | None
    position: Position | None = None

    @model_validator(mode="after")
    def _a_note_is_clean_and_a_rejection_has_one(self) -> PersonDecision:
        if (problem := position_problem(self.verb, self.position)) is not None:
            raise ValueError(problem)
        if self.note is not None:
            if (problem := note_problem(self.note)) is not None:
                raise ValueError(problem)
        elif self.verb == "reject":
            msg = "a rejection says why: its note is required"
            raise ValueError(msg)
        return self

    def text(self) -> str:
        """The free-text decision every reader of the decisions file already reads."""
        return decision_text(self.verb, self.note or "", self.position)


#: The items file, in the run directory.
QUEUE_NAME = "queue.jsonl"

#: The decisions file, beside the items file.
DECISIONS_NAME = "queue_decisions.jsonl"

# -- bounds on every read and every wait --------------------------------------------------
#
# A file in a run directory can be replaced by anything the same user can make: a file far
# larger than any run writes, one that keeps growing, a named pipe that blocks whoever
# opens it. Every read here is therefore capped, every open is non-blocking, and the one
# wait, for the decisions file's lock, ends. Each cap is far above anything a run writes:
# the largest records seen are event logs of about 40 KB and a trajectory of 6.3 MB, and a
# decision line is a few hundred bytes.

#: The most bytes read of the items file, whose items carry an artefact diff each.
QUEUE_READ_CAP = 64 << 20

#: The most bytes read of the decisions file.
DECISIONS_READ_CAP = 16 << 20

#: The most bytes read of a run's event log or of one session's captured stream.
RECORD_READ_CAP = 256 << 20

#: How long a decision waits for the decisions file's lock before it is refused. A decision
#: holds the lock only to read two small files and append one line.
LOCK_WAIT_S = 10.0

#: How often a waiting decision tries the lock again.
LOCK_POLL_S = 0.05


class FileTooLargeError(OSError):
    """A file is larger than the reader's cap, so it is not read at all."""


def _read_fd(fd: int, cap: int) -> bytes:
    """All of ``fd``'s bytes, refusing more than ``cap``: by its size first, then while reading.

    Raises:
        FileTooLargeError: the file is, or grows while it is read, past ``cap``.
    """
    if os.fstat(fd).st_size > cap:
        raise FileTooLargeError(errno.EFBIG, f"larger than {cap} bytes")
    data = bytearray()
    while len(data) <= cap:
        chunk = os.read(fd, min(1 << 20, cap + 1 - len(data)))
        if not chunk:
            return bytes(data)
        data += chunk
    raise FileTooLargeError(errno.EFBIG, f"grew past {cap} bytes while it was read")


def _read_path(path: Path, cap: int) -> bytes | None:
    """The bytes of the regular file at ``path``, or ``None`` if there is none.

    For readers that take the path as given (the writer's own files, a read-only view the
    operator UI has already held to its allowlist). It holds the file to the rules the
    decision function holds it to under its lock: never through a link, a regular file with
    one name. The open never blocks, so a named pipe put in a file's place is refused instead
    of waited on.

    Raises:
        OSError: a link, a second name, not a regular file, or past ``cap``
            (``FileTooLargeError``).
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        _plain(fd)
        return _read_fd(fd, cap)
    finally:
        os.close(fd)


def _unreadable(path: Path, exc: OSError) -> QueueError:
    """The refusal for a queue file that is not read: too large, or not a plain file."""
    if isinstance(exc, FileTooLargeError):
        msg = "an approval-queue file is larger than this reader reads, so nothing is done with it"
        return QueueError(msg, file=str(path), reason=str(exc.strerror))
    msg = "an approval-queue file is not a plain file with one name, so it is not read"
    return QueueError(msg, file=str(path), reason=exc.strerror or os.strerror(exc.errno or 0))


_ITEM: TypeAdapter[QueueItem] = TypeAdapter(QueueItem)
_DECISION: TypeAdapter[QueueResolution] = TypeAdapter(QueueResolution)


def escalation_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    findings: tuple[Finding, ...],
    artefact_diff: str,
    trajectories: tuple[str, ...],
    ts: str,
    spent_by_person: int = 0,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for a subtask whose every attempt was rejected.

    The triggering finding is the last one. The quantities are the last
    finding's that has any, because the most recent evidence is the most
    relevant. An attempt a person rejected from the queue left no finding of its own, so
    ``spent_by_person`` counts those; every attempt is still one finding or one of them.

    Raises:
        QueueError: fewer findings or trajectories than attempts were given.
    """
    if (
        not findings
        or spent_by_person < 0
        or len(findings) + spent_by_person != REPAIR_BUDGET
        or len(trajectories) != REPAIR_BUDGET
    ):
        msg = "an exhausted budget is escalated with every attempt's finding and trajectory"
        raise QueueError(msg, findings=str(len(findings)), trajectories=str(len(trajectories)))
    with_quantities = [f for f in findings if f.quantities]
    rejected = (
        f"was rejected on all {REPAIR_BUDGET} attempts"
        if not spent_by_person
        else f"has no attempt left of {REPAIR_BUDGET}: a person rejected {spent_by_person} of "
        "them from the queue, and the others were rejected"
    )
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source="repair_budget_exhausted",
        decision_required=(
            f"Subtask {subtask_id} {rejected}. Decide whether "
            "to accept the last attempt as it stands, rewrite the subtask's specification, or "
            "split the subtask."
        ),
        artefact_diff=artefact_diff,
        triggering_finding=findings[-1].text,
        quantities=with_quantities[-1].quantities if with_quantities else (),
        trajectories=trajectories,
        consequence=consequence,
    )


def decided_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    decision: Decision,
    findings: tuple[Finding, ...],
    artefact_diff: str,
    trajectories: tuple[str, ...],
    ts: str,
    attempt: int | None = None,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for a rejected subtask the escalation decision sent to a person, attempts left.

    Only a decision that was not forced makes one: a backend that answered yes, or one whose
    confidence fell below the floor. The finding and the quantities are chosen as for an
    exhausted budget, from the attempts made so far, each of which links its trajectory.

    Raises:
        QueueError: the decision was forced or does not route, or the attempts made so far
            are not each given with a finding and a trajectory.
    """
    if decision.forced or decision.basis not in ("answer", "floor"):
        msg = "only a decision that routed by its answer or its confidence makes this item"
        raise QueueError(msg, basis=str(decision.basis), forced=str(decision.forced))
    # An attempt a person rejected from the queue has a trajectory and no finding, so there may
    # be fewer findings than trajectories; never more, and never an attempt past the budget.
    number = len(trajectories) if attempt is None else attempt
    if (
        not findings
        or len(findings) > len(trajectories)
        or number != len(trajectories)
        or number >= REPAIR_BUDGET
    ):
        msg = "a decided escalation is sent with each attempt's finding and trajectory so far"
        raise QueueError(msg, findings=str(len(findings)), trajectories=str(len(trajectories)))
    why = (
        f"it answered {decision.answer}"
        if decision.basis == "answer"
        else f"its confidence, {decision.confidence}, is below {CONFIDENCE_FLOOR}"
    )
    with_quantities = [f for f in findings if f.quantities]
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source="escalation_decision",
        decision_required=(
            f"Subtask {subtask_id} was rejected on attempt {number} of {REPAIR_BUDGET}, "
            f"and the escalation backend {decision.backend_id} sent it to a person because {why}. "
            "Decide whether to accept the last attempt as it stands, rewrite the subtask's "
            "specification, or split the subtask."
        ),
        artefact_diff=artefact_diff,
        triggering_finding=findings[-1].text,
        quantities=with_quantities[-1].quantities if with_quantities else (),
        trajectories=trajectories,
        consequence=consequence,
    )


def arbitration_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    attempt: int,
    fix: bool,
    rulings: tuple[tuple[QuantityRef, Held, Writer | None, str, Standing], ...],
    artefact_diff: str,
    trajectories: tuple[str, ...],
    ts: str,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for an attempt whose dispute the precedence rule sends to a person (level 3).

    ``rulings`` is each dispute of the attempt ruled above the gate: the domain's typed position,
    sizing's held value and who wrote it, the level and the standing. Both positions are shown,
    and never the dispute's reason, which stays on the run's record; the quantities are the first
    three held values ruled for the queue in a unit the gate's parser takes, and a fix (``fix``)
    is named as the fix a person ordered, never by its place in the budget.
    """
    from physgate.orchestrator.integration_state import measure

    queued = [(held, standing) for _, held, _, level, standing in rulings if level == "queue"]
    why = []
    if any(s.counted_before for _, s in queued):
        why.append("the quantity was disputed in an earlier attempt")
    if fix:
        why.append("this is a fix a person ordered")
    elif any(not s.attempt_left for _, s in queued):
        why.append("this is the subtask's last attempt")
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source="arbitration",
        decision_required=(
            f"Subtask {subtask_id}, attempt {attempt}{'' if fix else f' of {REPAIR_BUDGET}'}, "
            "disputes a value of a cross node that sizing wrote, and the precedence rule sends it "
            f"to a person: {', and '.join(why)}. Decide which value stands; the reason each "
            "dispute gives is on the run's record."
        ),
        artefact_diff=artefact_diff,
        triggering_finding="\n".join(
            f"{held_line(held, writer)} The disputing subtask holds it at "
            f"{measure(position.value, position.unit)}."
            for position, held, writer, _, _ in rulings
        ),
        quantities=tuple(h.position for h, _ in queued if parses(h.position))[:3],
        trajectories=trajectories,
        consequence=consequence,
    )


def parses(position: QuantityRef) -> bool:
    """Whether the gate's parser takes ``position``'s unit: no other is shown on an item."""
    from physgate.gate.units import UnitRefusedError, parse

    try:
        parse(position.value, position.unit)
    except UnitRefusedError:
        return False
    return True


#: What a run id or a subtask id is, when an item id is made of it.
_ID_PART = re.compile(r"[A-Za-z0-9_-]{1,128}")


def item_id_for(run_id: str, subtask_id: str, round_: int) -> str:
    """An item's id: the run and the subtask, and from a subtask's second item on, its round.

    A subtask can come back to the queue after a person's reject started another attempt, or
    after the fix a blocked review gets; each time it is a new item, never a reuse of the last.
    The first keeps the id items always had.

    Raises:
        QueueError: the round is not a positive number.
    """
    if isinstance(round_, bool) or round_ < 1:
        msg = "an item's round counts from one"
        raise QueueError(msg, round=str(round_))
    for name in (run_id, subtask_id):
        # An id is a plain token, held whole, so nothing a run or a plan named can make an item
        # id that reads as a path (a separator, a parent step, a line break after the token).
        if _ID_PART.fullmatch(name) is None:
            msg = "an item id is made of plain identifiers"
            raise QueueError(msg, part=name)
    base = f"{run_id}-{subtask_id}"
    return base if round_ == 1 else f"{base}-r{round_}"


#: The subtask field of the item the integration call escalates: it is about the
#: whole design, not one subtask.
INTEGRATION = "integration"


def unavailable_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    attempt: int,
    source: Literal["review_unavailable", "review_blocked"],
    cause: str,
    detail: str,
    spec_defects: tuple[SpecDefect, ...],
    artefact_diff: str,
    trajectory: str,
    ts: str,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for a subtask whose review blocked it or reached no verdict; no attempt spent.

    A blocked review names what the issued specification lacks, which only the
    decomposition can supply; any other cause names why no verdict was reached. The
    source is the caller's, from the line it escalates, so a no-verdict line a log
    recorded with the legacy blocked cause stays a ``review_unavailable`` item.
    """
    if cause == "blocking_spec_defect":
        lacking = "; ".join(d.finding for d in spec_defects if d.blocking) or detail
        decision = (
            f"The review of subtask {subtask_id}, attempt {attempt}, was blocked: it could "
            f"not decide a safety-critical check because the issued specification lacks its input: "
            f"{lacking}. Decide whether to revise the specification and dispatch again, or "
            "to decide the check yourself. No repair attempt was spent."
        )
    else:
        decision = (
            f"The review of subtask {subtask_id}, attempt {attempt}, reached no verdict "
            f"({cause}: {detail}). Decide whether to review it again, review it yourself, or "
            "set the attempt aside. No repair attempt was spent."
        )
    notes = [f"specification defect: {d.finding}" for d in spec_defects if not d.blocking]
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source=source,
        decision_required=decision if not notes else decision + " Notes: " + "; ".join(notes),
        artefact_diff=artefact_diff,
        triggering_finding=detail,
        quantities=(),
        trajectories=(trajectory,),
        consequence=consequence,
    )


def integration_item(
    *,
    item_id: str,
    run_id: str,
    result: GateResult,
    run_span: tuple[str, str],
    trajectories: tuple[str, ...],
    ts: str,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for an integrated design the gate refused (a physics-gate escalation).

    No subtask owns a whole-system failure, so it goes to a person rather than to
    a repair session. ``run_span`` is the run branch's start and head, the design
    that was judged.

    Raises:
        QueueError: the refusal did not block, or no attempt left a trajectory.
    """
    if result.verdict != "fail" or result.mode != "on":
        msg = "only a blocking integration failure is escalated"
        raise QueueError(msg, verdict=result.verdict, mode=result.mode)
    if not trajectories:
        msg = "an integration item links every merged attempt's trajectory"
        raise QueueError(msg)
    start, head = run_span
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=INTEGRATION,
        source="gate_escalation",
        decision_required=(
            f"The integrated design failed the physics gate's {result.failing_check} check at "
            "system scope, after every subtask had merged. No one subtask owns this. Decide "
            "which module changes, or whether to accept the design as it stands."
        ),
        artefact_diff=(
            f"The run branch from {start} to {head}: see `git diff {start} {head}` in the "
            "target repository."
        ),
        triggering_finding=result.finding,
        quantities=result.quantities,
        trajectories=trajectories,
        consequence=consequence,
    )


#: The subtask field of a failed contract's item: it is about a pair of modules, not one subtask.
CONTRACT = "contract"


def contract_item_id(run_id: str, pair_number: int, round_: int) -> str:
    """A failed contract's item id: the run, the pair's number, and from its second item, the round.

    The pair's number is its place in the run's recorded pairs, from one.

    Raises:
        QueueError: the pair's number or the round is not a positive number, or the run id is
            not a plain identifier.
    """
    if isinstance(pair_number, bool) or pair_number < 1:
        msg = "a pair's number counts from one"
        raise QueueError(msg, pair=str(pair_number))
    return item_id_for(run_id, f"{CONTRACT}-{pair_number}", round_)


def contract_item(
    *,
    item_id: str,
    run_id: str,
    tested: ContractTested,
    rulings: tuple[ContractRuled, ...],
    round_: int,
    run_span: tuple[str, str],
    trajectories: tuple[str, ...],
    ts: str,
    consequence: ItemConsequence | None = None,
) -> QueueItem:
    """The item for a failed contract, a clause of which the precedence rule sends to a person.

    Both modules merged, so neither waits on it. Built from the result and its rulings alone: the
    pair by its modules and the subtasks that planned them, which side deviates, and per ruled
    clause the interface's value and each failing node's, with their revisions, each part held to
    its form. Never a node's free-text provenance, nor the clause's own words for a refused unit.

    Raises:
        QueueError: no ruling sends a clause to a person, or no merged attempt left a trajectory.
    """
    from physgate.orchestrator import integration_state as render
    from physgate.orchestrator.arbitration import clause_conflicts

    queued = [r for r in rulings if r.level == "queue"]
    if not queued or not trajectories:
        msg = "a contract item follows a clause ruled for a person, and links the merged work"
        raise QueueError(msg, item=item_id)
    pair = tested.result.pair
    held = {c.conflict: c for c in clause_conflicts(tested.result)}
    unjoined = {c.interface: c.not_joined for c in tested.result.interfaces}

    def side(name: str, subtask: str, module: str) -> str:
        sub = render.held(
            subtask, render.SUBTASK_PATTERN, render.PLANNED_ID_MAX_LENGTH, render.REFUSED_SUBTASK
        )
        return f"module {render.q(module)} ({name}, subtask {sub})"

    deviating = {s for r in queued for s in held[r.conflict].sides}
    who = (
        "Both modules' nodes deviate"
        if len(deviating) == 2
        else f"The {next(iter(deviating))}'s nodes deviate"
    )
    again = f" again (round {round_})" if round_ > 1 else ""
    producer = side("producer", pair.producer.subtask_id, pair.producer.module)
    consumer = side("consumer", pair.consumer.subtask_id, pair.consumer.module)
    start, head = run_span
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=CONTRACT,
        source="contract",
        decision_required=(
            f"The interface contract of {producer} to {consumer} failed{again} "
            "after both merged. The interfaces are fixed at decomposition, and no run changes "
            f"them. {who} from the interface. Decide whose merged work stands: choose producer or "
            "choose consumer. In this build a choice is recorded, and no merged module is reopened."
        ),
        artefact_diff=(
            f"The run branch from {start} to {head}: see `git diff {start} {head}` in the "
            "target repository."
        ),
        triggering_finding="\n".join(
            _clause_line(r, held[r.conflict].failing, unjoined[r.conflict.interface])
            for r in rulings
        ),
        quantities=tuple(
            r.wanted.position for r in queued if r.wanted is not None and parses(r.wanted.position)
        )[:3],
        trajectories=trajectories,
        consequence=consequence,
    )


def _clause_line(ruling: ContractRuled, failing: tuple[str, ...], unjoined: tuple[str, ...]) -> str:
    """One ruled clause, as the item states it: each value by the registry's names and revision."""
    from physgate.orchestrator import integration_state as render
    from physgate.orchestrator.dispute import QUANTITY_MAX, QUANTITY_PATTERN

    conflict = ruling.conflict
    where = f"Interface {render.held(conflict.interface)}"
    whose = " and the ".join(unjoined)
    joined = f"the {whose} {'is' if len(unjoined) == 1 else 'are'} not joined to it"
    level = "the gate" if ruling.level == "gate" else "a person"
    if conflict.quantity is None or ruling.wanted is None:
        return f"{where} has no quantity, and {joined}. Ruled for {level}."
    name = conflict.quantity
    named = (
        render.q(name)
        if len(name) <= QUANTITY_MAX and QUANTITY_PATTERN.fullmatch(name)
        else "a quantity name the dispute path refuses"
    )

    def holds(value: ContractValue) -> str:
        position = value.position
        return f"{render.measure(position.value, position.unit)} (revision {value.revision})"

    parts = [f"{where}, quantity {named}: the interface holds {holds(ruling.wanted)}"]
    carried = {v.position.node_id: v for v in ruling.found}
    for node in failing:
        found = carried.get(node)
        said = f"holds {holds(found)}" if found is not None else "does not carry it"
        parts.append(f"node {render.held(node)} {said}")
    if unjoined:
        parts.append(joined)
    return "; ".join(parts) + f". Ruled for {level}."


class _Records:
    """The queue's lines read so far, and what they make legal next.

    Shared by the writer and every reader, so a line one accepts the other accepts.
    """

    def __init__(self) -> None:
        self.items: dict[str, QueueItem] = {}
        self.resolved: dict[str, QueueResolution] = {}
        #: Each item's line as recorded, without its terminator: what a view shows is held
        #: to these bytes, not to a re-serialisation of them.
        self.lines: dict[str, bytes] = {}

    def check(self, record: QueueItem | QueueResolution) -> None:
        """Raise ``ValueError`` unless ``record`` may be the next line."""
        if isinstance(record, QueueItem):
            if record.item_id in self.items:
                msg = f"item {record.item_id!r} listed twice"
                raise ValueError(msg)
        elif record.item_id not in self.items or record.item_id in self.resolved:
            msg = f"a decision on {record.item_id!r}, which is not an open item"
            raise ValueError(msg)
        elif record.verb == "choose":
            offered = POSITIONS.get(self.items[record.item_id].source, ())
            if not offered:
                msg = (
                    "a choice is made only on an item whose kind offers positions: an arbitration "
                    "or a failed contract"
                )
                raise ValueError(msg)
            if record.position not in offered:
                msg = f"a position the item's kind does not offer: it offers {', '.join(offered)}"
                raise ValueError(msg)

    def record(self, record: QueueItem | QueueResolution) -> None:
        """Take ``record`` as read; :meth:`check` has passed it."""
        if isinstance(record, QueueItem):
            self.items[record.item_id] = record
        else:
            self.resolved[record.item_id] = record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return [i for k, i in self.items.items() if k not in self.resolved]


def _parse(
    source: Path | bytes,
    adapter: TypeAdapter[QueueItem] | TypeAdapter[QueueResolution],
    records: _Records,
    at: list[tuple[int, QueueResolution]] | None = None,
    *,
    name: str | None = None,
) -> int:
    """Admit every complete line into ``records``; the offset the good lines end at.

    ``source`` is the file, or its bytes as a caller read them through its own descriptor
    (``name`` then names it in a refusal). A final line without its terminator is a write
    still in progress and is not read. With ``at``, each decision is also listed with the
    byte offset its line starts at.

    Raises:
        QueueError: a complete line is not a record of the file's kind, or does not follow
            from the lines before it.
        FileNotFoundError: there is no file at ``source``.
    """
    offset = 0

    def admit(raw: bytes) -> QueueItem | QueueResolution:
        nonlocal offset
        record = adapter.validate_json(raw)
        if record.model_dump_json().encode() + b"\n" != raw:
            # Only the form the writer writes is read. A line the parser takes in another form
            # (a key given twice, of which it keeps the last; keys reordered; an escape for a
            # plain character; space or a carriage return around the record) would have one
            # meaning here and its digest would bind other bytes than any reader of the file
            # sees, so it is refused, never normalised.
            msg = "the line is not in the one form the queue's writer writes"
            raise ValueError(msg)
        records.check(record)
        records.record(record)
        if isinstance(record, QueueItem):
            records.lines[record.item_id] = raw.removesuffix(b"\n")
        elif at is not None:
            at.append((offset, record))
        offset += len(raw)
        return record

    _, good_end, corrupt = read_jsonl(source, admit)
    if corrupt is not None:
        bad_at, reason = corrupt
        msg = "the approval queue holds a line this package could not have written"
        where = name if name is not None else str(source)
        raise QueueError(msg, queue=where, offset=str(bad_at), reason=reason)
    return good_end


@dataclass(frozen=True)
class QueueView:
    """A run's queue as read from disk: every item, and every decision with its line's offset."""

    items: tuple[QueueItem, ...]
    decisions: tuple[tuple[int, QueueResolution], ...]
    #: Each item's digest: the sha256 of its line as recorded (see :func:`item_sha256`).
    digests: Mapping[str, str] = field(default_factory=dict)

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        decided = {decision.item_id for _, decision in self.decisions}
        return [item for item in self.items if item.item_id not in decided]


def read_queue(run_dir: Path, *, decisions: bytes | None = None) -> QueueView:
    """The queue of the run at ``run_dir``, read without writing anything.

    ``decisions`` is the decisions file's bytes as a caller already read them
    (:func:`decisions_file_bytes`), parsed in place of a second read, so what the caller checked
    of the file is exactly what is parsed.

    Nothing is created: a run directory, or either file, that is missing reads as empty. A
    torn final line is left where it is and not read, since its writer may still be completing
    it; only the writer, which knows no write of its own is in progress, may cut one.

    Raises:
        QueueError: a complete line is not a record, or does not follow from the lines
            before it (an item listed twice, a decision on no open item); or a file is not
            a regular file, or is past its cap.
    """
    records = _Records()
    at: list[tuple[int, QueueResolution]] = []
    if decisions is None:
        files = _read_run_files(
            run_dir, (QUEUE_NAME, QUEUE_READ_CAP), (DECISIONS_NAME, DECISIONS_READ_CAP)
        )
        (items_name, items), (decided_name, decided) = files
    else:
        # The decisions as the caller read them, once: what it checked is what is parsed.
        ((items_name, items),) = _read_run_files(run_dir, (QUEUE_NAME, QUEUE_READ_CAP))
        decided_name, decided = DECISIONS_NAME, decisions
    if items is not None:
        _parse(items, _ITEM, records, at, name=str(Path(run_dir) / items_name))
    if decided is not None:
        _parse(decided, _DECISION, records, at, name=str(Path(run_dir) / decided_name))
    return QueueView(
        items=tuple(records.items.values()),
        decisions=tuple(at),
        digests={k: item_sha256(line) for k, line in records.lines.items()},
    )


def _read_run_files(run_dir: Path, *wanted: tuple[str, int]) -> list[tuple[str, bytes | None]]:
    """Each named file's bytes in ``run_dir``, read as the decision function reads them.

    Never through a link, and only a regular file with one name within its cap, exactly the
    rules :func:`record_decision` holds the same files to under its lock, so every reader of
    the queue reads the bytes a decision was bound to and no others. A file that is not there
    reads as ``None``.

    Raises:
        QueueError: a file is a link, has a second name, is not a regular file or is past its
            cap.
    """
    found: list[tuple[str, bytes | None]] = []
    for name, cap in wanted:
        path = Path(run_dir) / name
        try:
            found.append((name, _read_path(path, cap)))
        except OSError as exc:
            raise _unreadable(path, exc) from None
    return found


def whole_lines(data: bytes) -> bytes:
    """``data`` up to and including its last line break: the lines a reader reads.

    A final line without its terminator is a write still in progress, or one that died; it is
    not read, and the writer may cut it (as :func:`_parse` and the writer treat it).
    """
    return data[: data.rfind(b"\n") + 1]


def decisions_file_bytes(run_dir: Path) -> bytes:
    """The decisions file's bytes, read as every reader of the queue reads them; empty if none.

    Raises:
        QueueError: the file is a link, has a second name, is not a regular file or is past its
            cap.
    """
    ((_, data),) = _read_run_files(run_dir, (DECISIONS_NAME, DECISIONS_READ_CAP))
    return b"" if data is None else data


def _events_of_run(run_dir: Path) -> list[Event] | None:
    """The run's event log, read without writing; ``None`` when there is none.

    Raises:
        CorruptEventLogError: the log is not a file this reader reads, or holds a line the
            loop could not have written.
    """
    events_path = Path(run_dir) / EVENTS_NAME
    try:
        ((_, log),) = _read_run_files(run_dir, (EVENTS_NAME, RECORD_READ_CAP))
    except QueueError as exc:
        msg = "the run-event log is not a file this reader reads"
        raise CorruptEventLogError(msg, log=str(events_path), **exc.context) from None
    return None if log is None else parse_events(log, log=str(events_path))


def _windows(events: list[Event]) -> list[tuple[int, int | None, str, bool]]:
    """Each session's window as (start, end, session, whether the OS layer was present).

    A session ran under the state the last ``os_layer_checked`` line before its spawn records;
    with none recorded, it is taken as having run without the layer.
    """
    windows: list[tuple[int, int | None, str, bool]] = []
    layer = False
    open_at: int | None = None
    open_layer = False
    for event in events:
        if isinstance(event, OsLayerChecked):
            layer = event.state.state == "present"
        elif isinstance(event, StageEntered) and event.decisions_bytes is not None:
            open_at, open_layer = event.decisions_bytes, layer
        elif (
            isinstance(event, SessionEnded | LeftoverRead)
            and open_at is not None
            and event.decisions_bytes is not None
        ):
            windows.append((open_at, event.decisions_bytes, event.session_id, open_layer))
            open_at = None
    if open_at is not None:
        windows.append((open_at, None, "still running or not yet resumed", open_layer))
    return windows


def _taken_of(events: list[Event]) -> dict[str, dict[str, object]]:
    """Each decision the run took, by item: its effect, whether it acted, why not, who confirmed.

    A confirmation of a held decision replaces what the held line said, since it is what acted.
    """
    taken: dict[str, dict[str, object]] = {}
    for event in events:
        if isinstance(event, DecisionTaken):
            taken[event.item_id] = {
                "effect": event.effect,
                "acts": event.acts,
                "why_not": event.why_not,
                "confirmed_by": event.confirmed_by,
                "order_too_long": event.order_too_long,
            }
    return taken


def windows_of(events: list[Event]) -> list[tuple[int, int | None, str]]:
    """The decisions file's byte ranges written while each session ran: (start, end, session).

    A session's window opens at its spawn stage and closes at its end, or at the resume that
    found it left over; a window still open has no end.
    """
    return [(start, end, session) for start, end, session, _ in _windows(events)]


def held_windows_of(events: list[Event]) -> list[tuple[int, int | None]]:
    """The windows of the sessions that ran without the OS layer: (start, end).

    A decision line starting in one may have been written by that session's own shell, which
    nothing but the layer keeps from the decisions file, so it acts only once an operator
    confirms it (ARCH-133). The same windows as :func:`windows_of`, by the same reading.
    """
    return [(start, end) for start, end, _, present in _windows(events) if not present]


def within(offset: int, windows: list[tuple[int, int | None]]) -> bool:
    """Whether a decision line starting at ``offset`` was written inside one of ``windows``."""
    return any(start <= offset and (end is None or offset < end) for start, end in windows)


def session_windows(run_dir: Path) -> list[tuple[int, int | None, str]]:
    """The decisions file's byte ranges written while each session ran: (start, end, session).

    From the event log (:func:`windows_of`). No event log, no windows.
    """
    events = _events_of_run(run_dir)
    return [] if events is None else windows_of(events)


def queue_listing(
    run_dir: Path, *, read_stream: Callable[[str], bytes | None] | None = None
) -> dict[str, object]:
    """What ``physgate queue list`` prints: the open items, and every decision with its mark.

    Each open item is listed with its line's digest and each trajectory's seal status, which is
    what a decision bound to it names (ARCH-133). ``read_stream`` returns a session's stream by
    its id, as :func:`trajectory_statuses` takes it; by default it is read from the run
    directory's sessions.

    A decision is not refused for being made while a session ran, since a person may decide
    then; but a session's hidden write could add one too, so a decision whose line starts
    inside a session's window is marked for a person to confirm. Read without writing.

    Raises:
        QueueError: the queue holds a line the writer could not have written.
        CorruptEventLogError: the event log does.
    """
    view = read_queue(run_dir)
    events = _events_of_run(run_dir) or []
    windows = windows_of(events)
    taken = _taken_of(events)
    decided = []
    for offset, decision in view.decisions:
        during = [
            sid for start, end, sid in windows if start <= offset and (end is None or offset < end)
        ]
        flag = f"made while session {during[0]} ran; confirm" if during else None
        entry: dict[str, object] = {**decision.model_dump(), "flag": flag}
        if decision.item_id in taken:
            # What the run did with it, from its own record; absent until it takes the decision,
            # and in every run that only records, whose listing is as it always was.
            entry["taken"] = taken[decision.item_id]
        decided.append(entry)
    with _stream_reader(run_dir, read_stream) as reader:
        listed = [
            {
                **item.model_dump(),
                "item_sha256": view.digests[item.item_id],
                "trajectory_statuses": list(trajectory_statuses(item, events, reader)),
            }
            for item in view.open_items()
        ]
    return {"open": listed, "decided": decided}


@contextlib.contextmanager
def _stream_reader(
    run_dir: Path, given: Callable[[str], bytes | None] | None
) -> Iterator[Callable[[str], bytes | None]]:
    """``given``, or a reader of a session's stream beneath the run directory, never via a link.

    The default opens the run directory once and walks ``sessions/<id>/stdout.jsonl`` beneath
    it without following a link at any step, holding the file to one name, as the decision
    function reads it under its lock. A session directory or a stream that is a link (to a copy
    of the sealed bytes, to anything outside the run) is refused, so it reads as tampered rather
    than as whatever it points at. The id is only ever one :func:`trajectory_session` matched.
    """
    if given is not None:
        yield given
        return
    try:
        dir_fd = os.open(run_dir, _DIR_FLAGS)
    except FileNotFoundError:
        yield lambda session_id: None
        return
    except OSError as exc:
        raise _unreadable(Path(run_dir), exc) from None
    try:
        yield lambda session_id: _read_in(
            dir_fd, SESSIONS_NAME, session_id, STREAM_NAME, cap=RECORD_READ_CAP
        )
    finally:
        os.close(dir_fd)


def item_sha256(line: bytes) -> str:
    """The digest a view of an item carries: of its line as recorded, without the terminator."""
    return hashlib.sha256(line).hexdigest()


# -- what a person saw of an item's trajectories ----------------------------------------

#: The run directory's sessions, each in a directory named by its id, its captured stream in it.
SESSIONS_NAME = "sessions"
STREAM_NAME = "stdout.jsonl"
EVENTS_NAME = "events.jsonl"

#: A session id as the event log's own model accepts it.
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

#: What an item's trajectory link is found to be, when its view is built and again when a
#: decision is recorded on that view.
TrajectoryStatus = Literal[
    "holds", "tampered", "missing", "no_seal", "not_in_this_run", "too_large"
]


def trajectory_session(link: str) -> str | None:
    """The session id an item's trajectory link names, or ``None`` if it names none.

    A link is the path the session's stream had on the machine that ran it. It is never
    opened as written: only its last three components are read, and they must be the
    sessions directory, a session id, and the stream's name.
    """
    parts = Path(link).parts
    if len(parts) < 3 or parts[-3] != SESSIONS_NAME or parts[-1] != STREAM_NAME:
        return None
    return parts[-2] if _SESSION_ID.fullmatch(parts[-2]) else None


def recorded_seal(events: list[Event], session_id: str) -> Seal | None:
    """The seal recorded for a session's stream: at its end, or when a resume read it left over."""
    for event in events:
        if (
            isinstance(event, SessionEnded | LeftoverRead)
            and event.session_id == session_id
            and event.trajectory_seal is not None
        ):
            return event.trajectory_seal
    return None


def trajectory_statuses(
    item: QueueItem, events: list[Event], read: Callable[[str], bytes | None]
) -> tuple[TrajectoryStatus, ...]:
    """Each of ``item``'s trajectory links, held to its seal, in the item's order.

    ``read`` returns a session's stream bytes, or ``None`` if there is none; it raises
    ``FileTooLargeError`` for a stream past its cap, which is not read, and any other
    ``OSError`` for a stream it refused to open (a link, a second name, a pipe), which counts
    as tampered, since the runtime writes none of those.
    """
    found: list[TrajectoryStatus] = []
    for link in item.trajectories:
        session_id = trajectory_session(link)
        if session_id is None:
            found.append("not_in_this_run")
            continue
        expected = recorded_seal(events, session_id)
        if expected is None:
            found.append("no_seal")
            continue
        try:
            data = read(session_id)
        except FileTooLargeError:
            found.append("too_large")
            continue
        except OSError:
            found.append("tampered")
            continue
        if data is None:
            found.append("missing")
        else:
            found.append("holds" if seal(data) == expected else "tampered")
    return tuple(found)


class ShownItem(BaseModel):
    """What a person was shown of an item: its line's digest and its trajectories' statuses."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    trajectories: tuple[TrajectoryStatus, ...]


def queue_files(run_dir: Path) -> tuple[Path, ...]:
    """The files :func:`queue_listing` and :func:`item_view` read, for a caller to vet first."""
    return tuple(Path(run_dir) / name for name in (QUEUE_NAME, DECISIONS_NAME, EVENTS_NAME))


def read_stream(path: Path) -> bytes | None:
    """A session's captured stream at ``path``, capped, or ``None`` if there is none.

    For a reader that has already held the path to its own rules (the operator UI's
    allowlist). The open never blocks; a stream that is not a regular file raises ``OSError``
    and one past its cap ``FileTooLargeError``, which :func:`trajectory_statuses` reads as
    tampered and too large.
    """
    return _read_path(path, RECORD_READ_CAP)


class TrajectoryView(BaseModel):
    """One of an item's trajectory links: the session it names, if any, and its status."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    link: NonEmptyStr
    session_id: NonEmptyStr | None
    status: TrajectoryStatus


class ItemView(BaseModel):
    """An item as a person is shown it: the item, whether it is open, and what was checked.

    ``item_sha256`` and the trajectories' statuses are exactly what a decision on this view
    sends back (:class:`ShownItem`) and what :func:`record_decision` checks again under its
    lock, computed here by the same functions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    position: Annotated[int, Field(ge=0)]
    item: QueueItem
    item_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    open: bool
    trajectories: tuple[TrajectoryView, ...]

    def shown(self) -> ShownItem:
        """What a decision on this view sends back."""
        return ShownItem(
            item_sha256=self.item_sha256,
            trajectories=tuple(t.status for t in self.trajectories),
        )


def item_view(
    run_dir: Path, position: int, *, read_stream: Callable[[str], bytes | None]
) -> ItemView | None:
    """The item at ``position`` in the run's queue, oldest first, or ``None`` past the end.

    ``read_stream`` returns a session's stream by its id (built from the id, never from the
    link as recorded), as :func:`trajectory_statuses` takes it. Read without writing.

    Raises:
        QueueError: the queue holds a line the writer could not have written, or is not read.
        CorruptEventLogError: the event log does, or is not read.
    """
    view = read_queue(run_dir)
    if not 0 <= position < len(view.items):
        return None
    item = view.items[position]
    events = _events_of_run(run_dir) or []
    statuses = trajectory_statuses(item, events, read_stream)
    return ItemView(
        position=position,
        item=item,
        item_sha256=view.digests[item.item_id],
        open=item in view.open_items(),
        trajectories=tuple(
            TrajectoryView(link=link, session_id=trajectory_session(link), status=status)
            for link, status in zip(item.trajectories, statuses, strict=True)
        ),
    )


def statuses_now(run_dir: Path, item_id: str) -> tuple[TrajectoryStatus, ...]:
    """Each of an item's trajectory statuses as they read now: the view the command line shows.

    The command line has no page that showed them; ``physgate queue list`` printed them, and a
    decision bound to the digest it printed is bound to these as the decision function reads
    them again under its lock. Read without writing.

    Raises:
        QueueError: no such item, or a queue file the writer could not have written.
        CorruptEventLogError: the event log does.
    """
    view = read_queue(run_dir)
    item = next((i for i in view.items if i.item_id == item_id), None)
    if item is None:
        raise _not_open(item_id, Path(run_dir) / QUEUE_NAME)
    events = _events_of_run(run_dir) or []
    with _stream_reader(run_dir, None) as reader:
        return trajectory_statuses(item, events, reader)


# -- the one decision function ------------------------------------------------------------


def decision_text(verb: Verb, note: str, position: Position | None = None) -> str:
    """The decision as recorded: the verb, its position, and the note after a colon if any.

    A rejection must say why; a choice names its position.

    Raises:
        QueueError: a rejection without a note, a verb that is not one of the three, or a
            position without choose or choose without one.
    """
    if verb not in ("approve", "reject", "choose"):
        msg = "a decision is to approve or to reject, or to choose a position"
        raise QueueError(msg, verb=str(verb))
    if (problem := position_problem(verb, position)) is not None:
        raise QueueError(problem, verb=verb)
    said = verb if position is None else f"{verb} {position}"
    # Blank means nothing but what ``str.strip`` removes; the operator UI's page mirrors this
    # set exactly, so its confirmation shows the decision this function makes.
    if not note.strip():
        if verb == "reject":
            msg = "a rejection says why: its note is required"
            raise QueueError(msg)
        return said
    return f"{said}: {note}"


#: How the decision function opens what it reads and writes: relative to the run directory's
#: descriptor, never through a link, never creating anything, and never waiting (a named pipe
#: in a file's place would otherwise block the open itself).
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_in(dir_fd: int, name: str, flags: int) -> int:
    """Open ``name`` beneath ``dir_fd``. Its own function so a test can act just before it."""
    return os.open(name, flags, dir_fd=dir_fd)


def _plain(fd: int) -> os.stat_result:
    """``fd``'s status if it is a regular file with one name; otherwise ``OSError``."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise OSError(errno.EPERM, "not a regular file with one name")
    return st


def _read_in(dir_fd: int, *parts: str, cap: int) -> bytes | None:
    """The bytes of the file ``parts`` names beneath ``dir_fd``, or ``None`` if it is not there.

    Every directory on the way and the file itself are opened without following a link and
    without waiting, and the file must be regular with one name and at most ``cap`` bytes.

    Raises:
        OSError: a link, a second name, anything else that is not a plain file, or a file
            past ``cap`` (``FileTooLargeError``).
    """
    opened: list[int] = []
    try:
        current = dir_fd
        for name in parts[:-1]:
            current = _open_in(current, name, _DIR_FLAGS)
            opened.append(current)
        fd = _open_in(current, parts[-1], _READ_FLAGS)
        opened.append(fd)
        _plain(fd)
        return _read_fd(fd, cap)
    except FileNotFoundError:
        return None
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def record_decision(
    run_dir: Path,
    item_id: str,
    *,
    decision: str | None = None,
    person: PersonDecision | None = None,
    resolved_by: str,
    clock: Callable[[], datetime] | None = None,
    shown: ShownItem | None = None,
    dir_fd: int | None = None,
) -> QueueResolution:
    """Record a person's decision on an open item: the one function that writes a decision.

    ``physgate queue resolve`` and the operator UI both call it, and so does
    :meth:`ApprovalQueue.resolve`. The run directory is ``dir_fd`` when the caller opened it
    (the UI reaches it by a walk no swap can redirect), or ``run_dir`` opened here. In order:

    1. the decisions file is opened for appending beneath the run directory, never through a
       link and never created, and must be a regular file with one name;
    2. an exclusive lock is taken on it, so two deciders cannot both find an item open;
    3. both files are read beneath the run directory the same way (the decisions file must be
       the one locked) and every line held to the writer's rules;
    4. the item must be listed and open, and, when ``shown`` is given, still exactly as it was
       shown: its line's digest and every trajectory's status, read again under the lock;
    5. a torn final line, which only a decider that died mid-write can leave while the lock is
       free, is cut; the decision is appended as one line and synced.

    The decision is ``decision``, free text that binds to nothing, or ``person``, a verb and a
    note bound to the view ``shown`` (ARCH-133): its line then also names the verb, the note and
    the digest of the item line shown. A bound approve, and a choice of the domain's position
    (which carries a session's typed value forward), is refused unless every trajectory shown
    held its seal; a choice of sizing's position binds to any view, as a reject does. An approve
    of a blocked review is refused unless its note says how the blocked check is decided.

    A refusal writes nothing. ``run_dir`` also names the files in a refusal.

    Raises:
        QueueError: the item is not open (unknown, decided, or no queue at all), a file is not
            a plain file, a line is not one the writer could have written, or the decision is
            not a record.
        StaleViewError: the item is no longer as ``shown``.
    """
    queue_path = Path(run_dir) / QUEUE_NAME
    if (decision is None) == (person is None):
        msg = "a decision is one of free text or a verb with its note, never both or neither"
        raise QueueError(msg, item=item_id)
    if person is not None and shown is None:
        msg = "a decision with a verb is bound to the view it was taken on, and none was given"
        raise QueueError(msg, item=item_id)
    try:
        record = QueueResolution(
            item_id=item_id,
            ts=utc_stamp((clock or utc_now)()),
            decision=person.text() if person is not None else str(decision),
            resolved_by=resolved_by,
            verb=person.verb if person is not None else None,
            position=person.position if person is not None else None,
            note=person.note if person is not None else None,
            shown_sha256=shown.item_sha256 if person is not None and shown is not None else None,
        )
    except ValidationError as exc:
        msg = "the decision is not one the queue can record"
        raise QueueError(msg, reason=first_problem(exc)) from None
    owned = dir_fd is None
    if dir_fd is None:
        try:
            dir_fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_open(item_id, queue_path) from None
    try:
        _decide(dir_fd, Path(run_dir), record, shown)
    finally:
        if owned:
            os.close(dir_fd)
    return record


def _no_decisions_file(
    dir_fd: int, item_id: str, queue_path: Path, decisions_path: Path
) -> QueueError:
    """The refusal when the decisions file is missing: no queue at all, or one that lost it."""
    try:
        os.stat(QUEUE_NAME, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _not_open(item_id, queue_path)
    msg = (
        "the run's queue lists items but its decisions file is missing, so nothing can be "
        "decided: the queue's writer creates that file with the first item, and this function "
        "never creates it"
    )
    return QueueError(msg, queue=str(queue_path), file=str(decisions_path))


def _not_open(item_id: str, queue_path: Path) -> QueueError:
    msg = f"a decision on {item_id!r}, which is not an open item"
    return QueueError(msg, queue=str(queue_path))


def _decide(dir_fd: int, run_dir: Path, record: QueueResolution, shown: ShownItem | None) -> None:
    queue_path, decisions_path = run_dir / QUEUE_NAME, run_dir / DECISIONS_NAME
    try:
        append = _open_in(dir_fd, DECISIONS_NAME, _APPEND_FLAGS)
    except FileNotFoundError:
        raise _no_decisions_file(dir_fd, record.item_id, queue_path, decisions_path) from None
    except OSError as exc:
        raise _unreadable(decisions_path, exc) from None
    try:
        try:
            locked = _plain(append)
        except OSError as exc:
            raise _unreadable(decisions_path, exc) from None
        _lock(append, decisions_path)
        _checked(record.item_id)
        try:
            items = _read_in(dir_fd, QUEUE_NAME, cap=QUEUE_READ_CAP)
        except OSError as exc:
            raise _unreadable(queue_path, exc) from None
        if items is None:
            raise _not_open(record.item_id, queue_path)
        try:
            reading = _open_in(dir_fd, DECISIONS_NAME, _READ_FLAGS)
        except OSError as exc:
            raise _unreadable(decisions_path, exc) from None
        try:
            read = _plain(reading)
            decided = _read_fd(reading, DECISIONS_READ_CAP)
        except OSError as exc:
            raise _unreadable(decisions_path, exc) from None
        finally:
            os.close(reading)
        if (read.st_dev, read.st_ino) != (locked.st_dev, locked.st_ino):
            msg = "the decisions file was replaced while the decision was being made"
            raise QueueError(msg, file=str(decisions_path))
        records = _Records()
        _parse(items, _ITEM, records, name=str(queue_path))
        good_end = _parse(decided, _DECISION, records, name=str(decisions_path))
        try:
            records.check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(queue_path)) from None
        if shown is not None:
            _require_as_shown(dir_fd, run_dir, records, record.item_id, shown)
        if record.verb is not None and shown is not None:
            _require_bindable(records.items[record.item_id], record, shown)
        if good_end != len(decided):
            os.ftruncate(append, good_end)
        _write_all(append, record.model_dump_json().encode() + b"\n")
        os.fsync(append)
    finally:
        os.close(append)


def _lock(fd: int, path: Path) -> None:
    """Take the decisions file's lock, waiting at most ``LOCK_WAIT_S``; refuse after that.

    Raises:
        QueueError: the lock was held by another decision for the whole wait.
    """
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                msg = (
                    "another decision held the approval queue's lock for the whole wait, "
                    "so nothing is written; decide again"
                )
                raise QueueError(msg, file=str(path), waited_s=f"{LOCK_WAIT_S:g}") from None
            time.sleep(LOCK_POLL_S)
        else:
            return


def _checked(item_id: str) -> None:
    """Called with the lock held, before anything is read. A seam for the lock's own tests."""


def _require_bindable(item: QueueItem, record: QueueResolution, shown: ShownItem) -> None:
    """Refuse a bound approve, or a choice of the domain, its view cannot carry.

    A trajectory shown that did not hold its seal, or a blocked review approved without saying
    how the check it could not decide is decided. Choosing the domain's position carries a
    session's typed value forward, so it is held to the seals as an approve is; choosing sizing
    keeps the graph's value, as a reject keeps the record, and binds to any view.
    """
    if record.verb == "choose" and record.position == "domain":
        if not shown.trajectories or any(status != "holds" for status in shown.trajectories):
            msg = (
                "choosing the domain binds to an item every trajectory of which held its seal "
                "when shown, and this one's did not, so the decision is refused"
            )
            raise QueueError(msg, item=item.item_id, shown=",".join(shown.trajectories))
        return
    if record.verb != "approve":
        return
    if not shown.trajectories or any(status != "holds" for status in shown.trajectories):
        msg = (
            "an approve binds to an item every trajectory of which held its seal when shown, "
            "and this one's did not, so the decision is refused"
        )
        raise QueueError(msg, item=item.item_id, shown=",".join(shown.trajectories))
    if item.source == "review_blocked" and record.note is None:
        msg = (
            "approving a blocked review decides the check the review could not: the note says "
            "how, and none was given"
        )
        raise QueueError(msg, item=item.item_id)


def _require_as_shown(
    dir_fd: int, run_dir: Path, records: _Records, item_id: str, shown: ShownItem
) -> None:
    """Refuse unless the item is still exactly as ``shown``, read again under the lock."""
    now = item_sha256(records.lines[item_id])
    if now != shown.item_sha256:
        msg = "the item is no longer the one that was shown, so the decision is refused"
        raise StaleViewError(msg, item=item_id, shown=shown.item_sha256, now=now)
    try:
        log = _read_in(dir_fd, EVENTS_NAME, cap=RECORD_READ_CAP)
    except OSError as exc:
        raise _unreadable(run_dir / EVENTS_NAME, exc) from None
    events = parse_events(log, log=str(run_dir / EVENTS_NAME)) if log is not None else []
    statuses = trajectory_statuses(
        records.items[item_id],
        events,
        lambda session_id: _read_in(
            dir_fd, SESSIONS_NAME, session_id, STREAM_NAME, cap=RECORD_READ_CAP
        ),
    )
    if statuses != shown.trajectories:
        msg = "a trajectory of the item is no longer as it was shown, so the decision is refused"
        raise StaleViewError(
            msg, item=item_id, shown=",".join(shown.trajectories), now=",".join(statuses)
        )


class ApprovalQueue:
    """The one writer of a run's approval queue.

    Opening it creates the files and cuts a torn final line, which is right for the writer and
    wrong for anything that only reads: a reader goes through :func:`read_queue`.
    """

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Open or create the queue at ``path``.

        Raises:
            QueueError: a complete line is not a record, or does not follow from the
                lines before it (an item listed twice, a decision on no open item).
        """
        self.path = Path(path)
        if self.path.name != QUEUE_NAME:
            msg = "the approval queue's items file is always named the same in its run directory"
            raise QueueError(msg, queue=str(self.path), expected=QUEUE_NAME)
        self.decisions_path = self.path.with_name(DECISIONS_NAME)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.decisions_path.touch(exist_ok=True)
        self.refresh()

    def refresh(self) -> None:
        """Read both files again: a person may have decided since they were last read.

        Raises:
            QueueError: a complete line is not a record of its file's kind, or does not
                follow from the lines before it.
        """
        self._records = _Records()
        # The items file has one writer, this one, so a torn tail there is this writer's own
        # interrupted write and is cut. The decisions file is appended to by whoever decides,
        # whenever they decide, so a torn tail there may be a write still in progress: it is
        # left for the decision function to cut, under its lock.
        try:
            items = _read_path(self.path, QUEUE_READ_CAP) or b""
        except OSError as exc:
            raise _unreadable(self.path, exc) from None
        try:
            decided = _read_path(self.decisions_path, DECISIONS_READ_CAP) or b""
        except OSError as exc:
            raise _unreadable(self.decisions_path, exc) from None
        good_end = _parse(items, _ITEM, self._records, name=str(self.path))
        if len(items) != good_end:
            with self.path.open("r+b") as handle:
                handle.truncate(good_end)
        _parse(decided, _DECISION, self._records, name=str(self.decisions_path))

    def _append(self, record: QueueItem) -> None:
        try:
            self._records.check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(self.path)) from None
        # Every listed item has a decisions file beside it, so it can always be decided: the
        # decision function never creates one, and refuses a run whose file has gone.
        self.decisions_path.touch(exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(record.model_dump_json().encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records.record(record)

    def add(self, item: QueueItem) -> None:
        """List ``item``, synced before returning."""
        self._append(item)

    def resolve(self, item_id: str, *, decision: str, resolved_by: str) -> QueueResolution:
        """Record a person's decision on an open item, through :func:`record_decision`."""
        record = record_decision(
            self.path.parent,
            item_id,
            decision=decision,
            resolved_by=resolved_by,
            clock=self._clock,
        )
        self.refresh()
        return record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return self._records.open_items()

    def items(self) -> list[QueueItem]:
        """Every item, oldest first."""
        return list(self._records.items.values())
