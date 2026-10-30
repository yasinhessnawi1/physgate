"""What a person's decision on a queue item does, computed by code from the run's record.

ARCH-133. A person decides an item with a verb and a note; what that does is never read
from the words. It is computed here, from the event log as ``RunState`` replays it, by one
function used in three places:

- when an item is listed (``item_consequence``): what each verb will do, and why approve
  only records when it does, so the item says it before anyone decides;
- when the loop takes a decision (``decision_effect``): the item must still say what the log
  says, and the decision must be bound to the item's line as listed;
- when a ``decision_taken`` line is replayed (``require_taken``): the line must be one this
  code could have written, given every line before it.

**The rule, in one sentence:** an approve may merge only an attempt that every automated
check let through. What a person overrides is the reviewer's verdict and nothing else: a
review that failed, never came, or blocked on the specification. An attempt whose reading
was not verified, whose change check refused it, or whose gate result the run's mode does not
merge, is never merged by an approve; nor is one of a subtask any review of which confirmed
a reward-hacking indicator, at any attempt, or one in whose streams the scan before review
found one that no review judged.

**What a reject does:** after a blocked review, one fix by a fresh session (once per
subtask); with repair attempts left, the next attempt from the note; otherwise the subtask
ends rejected. An integration failure is recorded and never acted on; so are approve and reject on
an arbitration, where a person picks a position instead. **What choosing sizing's value does:**
the next attempt while the budget lasts, else the one fix while it is unused, else the end of the
subtask; the order each gives quotes the graph's value as the rulings held it. Choosing the
domain's value records only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from physgate.orchestrator.budget import after_rejection
from physgate.orchestrator.events import (
    DecisionEffect,
    DecisionTaken,
    GateRan,
    GateSkipped,
    Position,
    WhyNot,
)
from physgate.orchestrator.exceptions import QueueItemMismatchError
from physgate.orchestrator.protocols import PersonOrder, PersonOrderKind
from physgate.orchestrator.queue import (
    INTEGRATION,
    POSITIONS,
    ConfirmedIndicator,
    ItemConsequence,
    OnChoose,
    OnReject,
    QueueItem,
    QueueResolution,
    QueueSource,
    Verb,
    WhyRecordOnly,
)
from physgate.orchestrator.repair import (
    chose_sizing_fix_instruction,
    chose_sizing_retry_instruction,
    fix_instruction,
    person_repair_instruction,
)
from physgate.reviewers.packet import fits_one_read, person_order_text
from physgate.reviewers.scan import ScanHit, ScanUnreadableError, scan

if TYPE_CHECKING:
    from physgate.orchestrator.replay import AttemptState, RunState, SubtaskState


#: The sources whose approve can merge, and so whose scan before review counts: every one of
#: them may carry an earlier attempt that ended at the gate or the change check unreviewed, whose
#: work is in the commit an approve merges. Each attempt no review judged is scanned (a review
#: that blocked judged its own attempt's streams, not an earlier one's); a hit makes approve
#: record only. The same holds for each: the automated block, the indicator history, the scan.
SCANNED_SOURCES: frozenset[QueueSource] = frozenset(
    {"review_unavailable", "review_blocked", "repair_budget_exhausted", "escalation_decision"}
)


@dataclass(frozen=True)
class Taken:
    """What a decision does when the loop takes it: the effect, whether it acts, and why not."""

    effect: DecisionEffect
    acts: bool
    why_not: WhyNot | None
    #: A reject that ends the subtask in place of the order it would give, because what that
    #: order's reviewer would be told is longer than one read shows whole.
    order_too_long: bool = False


#: Why approve records only, as an item says it, and as the decision taken on it says it.
_WHY_NOT: dict[WhyRecordOnly, WhyNot] = {
    "gate": "last_rejection_automated",
    "change_check": "last_rejection_automated",
    "reading": "last_rejection_automated",
    "indicator_in_history": "indicator_in_history",
    "scan_hit": "scan_hit",
    "source": "record_only_source",
    "legacy": "legacy_item",
}


def confirmed_indicators(sub: SubtaskState) -> tuple[ConfirmedIndicator, ...]:
    """Every indicator a review of any attempt of the subtask confirmed, oldest first.

    Every attempt, every round and the fix: an attempt that confirmed gaming and a later one
    that failed for something else still leave the subtask's history with it.
    """
    # Read from every review line the subtask's log holds, never from what an attempt still
    # remembers: a resumed attempt forgets its review, and its history must not.
    return tuple(
        ConfirmedIndicator(attempt=review.attempt, kind=indicator.kind)
        for review in sub.reviews
        for indicator in review.result.indicators
        if indicator.disposition == "confirmed"
    )


def scan_hits_of(streams: Iterable[bytes]) -> tuple[ScanHit, ...]:
    """What the scan before review finds in an attempt's streams, each already held to its seal.

    Raises:
        ScanUnreadableError: a stream is not UTF-8, or holds a line the scan cannot read: it
            fails closed, never as a stream with no hits.
    """
    hits: list[ScanHit] = []
    for data in streams:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            msg = "a stream is not UTF-8, so it is not one the runtime wrote"
            raise ScanUnreadableError(msg) from None
        hits.extend(scan(text))
    return tuple(hits)


def source_of(sub: SubtaskState) -> QueueSource:
    """The queue source of the item a subtask escalated with, read from how its attempt ended.

    Raises:
        ValueError: the subtask's last attempt did not end in a way that reaches the queue.
    """
    now = sub.attempts[-1] if sub.attempts else None
    if now is None:
        msg = "a subtask with no attempt has no queue item"
        raise ValueError(msg)
    if now.queued:
        return "arbitration"
    if now.blocked is not None:
        return "review_blocked"
    if now.unavailable_final is not None:
        return "review_unavailable"
    if now.rejected is not None:
        decided = now.decided
        if decided is not None and not decided.decision.forced:
            return "escalation_decision"
        return "repair_budget_exhausted"
    msg = "the subtask's last attempt did not end in a way that reaches the queue"
    raise ValueError(msg)


def _gate_merges(now: AttemptState) -> bool:
    """The attempt's gate line is one the run's gate mode merges."""
    gate = now.gate
    if isinstance(gate, GateSkipped):
        return True
    if isinstance(gate, GateRan):
        return gate.result.verdict == "pass" or gate.result.mode == "observe"
    return False


def _automated_block(now: AttemptState) -> WhyRecordOnly | None:
    """The automated check that refused the attempt, if one did: never overridden by a person."""
    if now.session is None or not now.session.reading_verified:
        return "reading"
    if now.changes is None or now.changes.refused_by is not None:
        return "change_check"
    if not _gate_merges(now):
        return "gate"
    return None


def _arbitration_effect() -> tuple[WhyRecordOnly, OnReject]:
    """What approve and reject do on an arbitration item: nothing.

    Neither verb picks between the two positions, so both record only; a person picks one with
    ``choose`` (:func:`_on_choose`).
    """
    return "source", "record_only"


def _on_choose(sub: SubtaskState) -> dict[Position, OnChoose]:
    """What choosing each position of the subtask's arbitration item does, from its record.

    Sizing's value: the next attempt while the budget lasts; once none is left, the one fix while
    no attempt of the subtask was it; otherwise the end of the subtask. The domain's records only.
    """
    now = sub.attempts[-1]
    sizing: OnChoose
    if not now.fix and after_rejection(now.number) is not None:
        sizing = "retry"
    elif not any(attempt.fix for attempt in sub.attempts):
        sizing = "fix"
    else:
        sizing = "end_subtask"
    return {"sizing": sizing, "domain": "record_only"}


def _on_reject(sub: SubtaskState, source: QueueSource) -> OnReject:
    """What a reject does to the subtask's item: one fix, the next attempt, or the end."""
    now = sub.attempts[-1]
    if source == "review_blocked":
        # Never a fix's own: a fix whose review blocked ends the subtask by rule and goes to no
        # person (the replay routes it so, and refuses a second fix).
        return "fix"
    fix_used = any(attempt.fix for attempt in sub.attempts)
    if fix_used or after_rejection(now.number) is None:
        return "end_subtask"
    if source in ("review_unavailable", "escalation_decision"):
        return "retry"
    return "end_subtask"


def item_consequence(
    state: RunState, subtask_id: str, *, source: QueueSource, scan_hits: tuple[ScanHit, ...]
) -> ItemConsequence:
    """What each verb will do to the subtask's item, and why approve records only if it does.

    ``scan_hits`` is what the scan before review found in the streams of the attempts no review
    judged; it counts for the sources in :data:`SCANNED_SOURCES`.
    """
    if subtask_id == INTEGRATION or source == "gate_escalation":
        return ItemConsequence(
            attempt=None,
            attempt_commit=None,
            on_approve="record_only",
            on_reject="record_only",
            why_record_only="source",
            confirmed_indicators=(),
            scan_hits=(),
        )
    sub = state.subtasks[subtask_id]
    now = sub.attempts[-1]
    commit = (
        now.changes.checked_commit
        if now.changes is not None
        else now.session.attempt_commit
        if now.session is not None
        else None
    )
    indicators = confirmed_indicators(sub)
    hits = scan_hits if source in SCANNED_SOURCES else ()
    if source == "arbitration":
        why, on_reject = _arbitration_effect()
        return ItemConsequence(
            attempt=now.number,
            attempt_commit=commit,
            on_approve="record_only",
            on_reject=on_reject,
            why_record_only=why,
            confirmed_indicators=indicators,
            scan_hits=(),
            on_choose=_on_choose(sub),
        )
    why_not: WhyRecordOnly | None = _automated_block(now)
    if why_not is None and indicators:
        why_not = "indicator_in_history"
    if why_not is None and hits:
        why_not = "scan_hit"
    return ItemConsequence(
        attempt=now.number,
        attempt_commit=commit,
        on_approve="merge_attempt" if why_not is None else "record_only",
        on_reject=_on_reject(sub, source),
        why_record_only=why_not,
        confirmed_indicators=indicators,
        scan_hits=hits,
    )


def person_order(
    state: RunState,
    rejected: AttemptState,
    *,
    effect: DecisionEffect,
    item_id: str,
    note: str | None,
) -> PersonOrder | None:
    """The order a person's decision on ``rejected`` gives the next session, built by code alone.

    For the one fix: the review's finding and each blocking defect it named, and the note, in
    the fix template. For a retry: the note, with the reviewer's finding when a review rejected
    the attempt. For a choice of sizing's value on an attempt sent to a person by its rulings:
    the graph's value of each quantity ruled above the gate, and the note if there is one.
    Nothing for any other effect. The same function builds the order when the loop takes the
    decision and when it starts the session, so both read the same text.

    Raises:
        ValueError: a fix of an attempt whose review did not block, or a reject's order with no
            note.
    """
    if rejected.queued:
        return _chose_sizing_order(state, rejected, effect=effect, item_id=item_id, note=note)
    if effect in ("fix", "retry") and note is None:
        msg = "a session a person ordered by a reject is ordered with the person's note"
        raise ValueError(msg)
    if effect == "fix":
        blocked = rejected.blocked
        if blocked is None:
            msg = "a fix is ordered only after a review that blocked"
            raise ValueError(msg)
        text = fix_instruction(
            rejected.number,
            blocked.result.finding,
            tuple(d.finding for d in blocked.result.spec_defects if d.blocking),
            note or "",
        )
        return PersonOrder(
            kind="fix_after_block", item_id=item_id, of_attempt=rejected.number, instruction=text
        )
    if effect == "retry":
        before = rejected.rejected
        text = person_repair_instruction(
            rejected.number, note or "", before.finding if before is not None else None
        )
        return PersonOrder(
            kind="retry_after_reject", item_id=item_id, of_attempt=rejected.number, instruction=text
        )
    return None


def _chose_sizing_order(
    state: RunState,
    rejected: AttemptState,
    *,
    effect: DecisionEffect,
    item_id: str,
    note: str | None,
) -> PersonOrder | None:
    """The order choosing sizing's value gives: the graph's value as each ruling held it."""
    sized = tuple(
        (line.held, state.writer_of(line.held))
        for line in rejected.arbitrations
        if line.level != "gate"
    )
    if effect == "retry":
        text = chose_sizing_retry_instruction(rejected.number, sized, note)
        kind: PersonOrderKind = "retry_after_arbitration"
    elif effect == "fix":
        text = chose_sizing_fix_instruction(rejected.number, sized, note)
        kind = "fix_after_arbitration"
    else:
        return None
    return PersonOrder(kind=kind, item_id=item_id, of_attempt=rejected.number, instruction=text)


def _order_fits(
    state: RunState, sub: SubtaskState, effect: DecisionEffect, item_id: str, note: str | None
) -> bool:
    """Whether the reviewer of the session a decision orders could read what it is told whole.

    A reject's order is the note and what it quotes, so one with no note orders nothing. A
    choice's quotes the graph's values, which can be long without any note.
    """
    now = sub.attempts[-1]
    if note is None and not now.queued:
        return True
    order = person_order(state, now, effect=effect, item_id=item_id, note=note)
    return order is None or fits_one_read(person_order_text(order))


def _effect_of(
    consequence: ItemConsequence, verb: Verb, position: Position | None = None
) -> tuple[DecisionEffect, WhyNot | None]:
    if verb == "choose":
        chosen = (consequence.on_choose or {}).get(position) if position is not None else None
        if chosen is None:
            msg = "a choice of a position the item does not state"
            raise ValueError(msg)
        if chosen == "record_only":
            return "none", "record_only_source"
        return chosen, None
    if verb == "approve":
        if consequence.on_approve == "merge_attempt":
            return "merge", None
        return "none", _WHY_NOT[consequence.why_record_only or "legacy"]
    if consequence.on_reject == "record_only":
        return "none", "record_only_source"
    return consequence.on_reject, None


def decision_effect(
    state: RunState,
    item: QueueItem,
    resolution: QueueResolution,
    *,
    line_sha256: str,
    scan_hits: tuple[ScanHit, ...],
    held: bool,
) -> Taken:
    """What the loop does with ``resolution`` on ``item``, from the run as its log replays.

    ``line_sha256`` is the digest of the item's line as the items file holds it now;
    ``scan_hits`` what the scan finds in the attempt's sealed streams now; ``held``
    whether the decision was written while a session ran without the OS layer.

    Raises:
        QueueItemMismatchError: the item, the decision and the event log do not agree: the
            item's line changed since it was decided, its subtask is not waiting on it, or it
            states another consequence than the log gives. The run halts on it.
    """
    if resolution.item_id != item.item_id:
        msg = "the decision is on another item than the one it is taken with"
        raise QueueItemMismatchError(msg, item=item.item_id, decided=resolution.item_id)
    if item.consequence is None:
        return Taken(effect="none", acts=False, why_not="legacy_item")
    if resolution.verb is None or resolution.shown_sha256 is None:
        return Taken(effect="none", acts=False, why_not="not_bound")
    if resolution.shown_sha256 != line_sha256:
        msg = "the item's line is not the one the decision was taken on"
        raise QueueItemMismatchError(msg, item=item.item_id)
    if item.subtask_id == INTEGRATION:
        escalated = state.integration_escalated
        if escalated is None or escalated.item_id != item.item_id:
            msg = "the run escalated no such integration item"
            raise QueueItemMismatchError(msg, item=item.item_id)
        expected = item_consequence(state, INTEGRATION, source=item.source, scan_hits=())
    else:
        sub = state.subtasks.get(item.subtask_id)
        if sub is None or sub.status != "escalated" or sub.queue_item != item.item_id:
            msg = "the item's subtask is not waiting on this item"
            raise QueueItemMismatchError(msg, item=item.item_id, subtask=item.subtask_id)
        expected = item_consequence(state, item.subtask_id, source=item.source, scan_hits=scan_hits)
    if expected != item.consequence:
        msg = "the item says another consequence than the run's record gives"
        raise QueueItemMismatchError(msg, item=item.item_id)
    if resolution.verb == "approve" and item.source == "review_blocked" and resolution.note is None:
        # The writer refuses this line; one that reaches the file anyway is refused here.
        msg = "approving a blocked review says how the blocked check is decided, and this did not"
        raise QueueItemMismatchError(msg, item=item.item_id)
    try:
        effect, why = _effect_of(expected, resolution.verb, resolution.position)
    except ValueError as exc:  # the writer refuses this line; one that reaches the file anyway
        raise QueueItemMismatchError(str(exc), item=item.item_id) from None
    if why is not None:
        return Taken(effect=effect, acts=False, why_not=why)
    too_long = False
    if effect in ("fix", "retry") and item.subtask_id != INTEGRATION:
        sub = state.subtasks[item.subtask_id]
        if not _order_fits(state, sub, effect, item.item_id, resolution.note):
            # Refused before any session: a review that could not read what its session was
            # told whole could not be prepared, and would be no review.
            effect, too_long = "end_subtask", True
    if held:
        return Taken(
            effect=effect, acts=False, why_not="held_os_layer_off", order_too_long=too_long
        )
    return Taken(effect=effect, acts=True, why_not=None, order_too_long=too_long)


def require_taken(state: RunState, event: DecisionTaken) -> None:
    """Refuse a ``decision_taken`` line this code could not have written after the lines before it.

    What the line can be checked against from the event log alone: whose item it is, that the
    subtask waits on it, that it acts only where the log's own record allows the effect it
    names, on the attempt and the commit the log names. What the log cannot hold (the item's
    line, the scan of the streams) the loop checked when it took the decision.

    Raises:
        ValueError: the line cannot come next.
    """
    earlier = state.taken.get(event.item_id)
    if event.confirmed_by is not None:
        if (
            earlier is None
            or earlier.why_not != "held_os_layer_off"
            or event.item_id in (state.confirmed)
        ):
            msg = "a confirmation follows a held decision, once"
            raise ValueError(msg)
        if (event.verb, event.position, event.effect, event.decision_offset) != (
            earlier.verb,
            earlier.position,
            earlier.effect,
            earlier.decision_offset,
        ):
            msg = "a confirmation is of the decision that was held"
            raise ValueError(msg)
    elif earlier is not None:
        msg = "a decision on an item is taken once"
        raise ValueError(msg)
    if event.subtask_id is None:
        if event.acts or event.effect != "none":
            msg = "a decision on the integration item records only"
            raise ValueError(msg)
        if event.verb == "choose":
            msg = "a decision on the integration item records only, and no position is chosen on it"
            raise ValueError(msg)
        if state.integration_escalated is None or state.integration_escalated.item_id != (
            event.item_id
        ):
            msg = "a decision on an integration item the run did not escalate"
            raise ValueError(msg)
        return
    sub = state.subtasks.get(event.subtask_id)
    if sub is None or sub.status != "escalated" or sub.queue_item != event.item_id:
        msg = "a decision on an item its subtask is not waiting on"
        raise ValueError(msg)
    now = sub.attempts[-1]
    if event.verb is None:
        # Free text binds to nothing, on any item.
        if (
            event.acts
            or event.effect != "none"
            or event.why_not not in ("not_bound", "legacy_item")
        ):
            msg = "a decision with no verb binds to nothing and records only"
            raise ValueError(msg)
        return
    if event.shown_sha256 is None:
        msg = "a decision with a verb names the digest of the item line it was taken on"
        raise ValueError(msg)
    source = source_of(sub)
    if event.verb == "choose" and event.position not in POSITIONS.get(source, ()):
        msg = "a choice is taken only on an arbitration item, of a position it offers"
        raise ValueError(msg)
    expected = item_consequence(state, event.subtask_id, source=source, scan_hits=())
    if (event.attempt, event.attempt_commit) != (now.number, expected.attempt_commit):
        msg = "a decision that names another attempt or commit than the record's"
        raise ValueError(msg)
    # What the log alone gives the verb. The scan's hits and the item's own line are not in the
    # log; the loop checked those when it took the decision, so a scan hit may only turn an
    # effect the log allows into recording, and nothing turns one it does not allow into an act.
    effect, why = _effect_of(expected, event.verb, event.position)
    too_long = (
        why is None
        and effect in ("fix", "retry")
        and not _order_fits(state, sub, effect, event.item_id, event.note)
    )
    if too_long:
        effect = "end_subtask"
    if event.order_too_long != too_long:
        msg = "a decision that says its order could not be read whole where the record does not"
        raise ValueError(msg)
    if event.why_not is None or event.why_not == "held_os_layer_off":
        allowed = why is None and event.effect == effect
    elif event.why_not == "scan_hit":
        allowed = event.verb == "approve" and event.effect == "none" and effect == "merge"
    elif event.why_not == "legacy_item":
        allowed = event.effect == "none"
    else:
        allowed = event.effect == "none" and event.why_not == why
    if not allowed:
        msg = "a decision that does other than the record allows"
        raise ValueError(msg)
    if event.acts and event.verb == "reject" and event.note is None:
        msg = "a reject that acts carries its note"
        raise ValueError(msg)
