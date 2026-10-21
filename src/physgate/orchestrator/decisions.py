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
ends rejected. An integration failure and an arbitration are recorded and never acted on.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from physgate.orchestrator.budget import after_rejection
from physgate.orchestrator.events import (
    DecisionEffect,
    DecisionTaken,
    GateRan,
    GateSkipped,
    WhyNot,
)
from physgate.orchestrator.exceptions import QueueItemMismatchError
from physgate.orchestrator.queue import (
    INTEGRATION,
    ConfirmedIndicator,
    ItemConsequence,
    OnReject,
    QueueItem,
    QueueResolution,
    QueueSource,
    WhyRecordOnly,
)
from physgate.reviewers.scan import ScanHit, ScanUnreadableError, scan

if TYPE_CHECKING:
    from physgate.orchestrator.replay import AttemptState, RunState, SubtaskState


@dataclass(frozen=True)
class Taken:
    """What a decision does when the loop takes it: the effect, whether it acts, and why not."""

    effect: DecisionEffect
    acts: bool
    why_not: WhyNot | None


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
    """What the verbs do on an arbitration item: nothing yet.

    The one place an arbitration's effect is defined. Until what approve picks between two
    arbitrated outcomes is defined, both verbs record only.
    """
    return "source", "record_only"


def _on_reject(sub: SubtaskState, source: QueueSource) -> OnReject:
    """What a reject does to the subtask's item: one fix, the next attempt, or the end."""
    now = sub.attempts[-1]
    fix_used = any(attempt.fix for attempt in sub.attempts)
    if source == "review_blocked":
        return "end_subtask" if fix_used else "fix"
    if fix_used or after_rejection(now.number) is None:
        return "end_subtask"
    if source in ("review_unavailable", "escalation_decision"):
        return "retry"
    return "end_subtask"


def item_consequence(
    state: RunState, subtask_id: str, *, source: QueueSource, scan_hits: tuple[ScanHit, ...]
) -> ItemConsequence:
    """What each verb will do to the subtask's item, and why approve records only if it does.

    ``scan_hits`` is what the scan before review found in the attempt's streams; it counts only
    for an item whose review never judged them (``review_unavailable``).
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
    hits = scan_hits if source == "review_unavailable" else ()
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


def _effect_of(
    consequence: ItemConsequence, verb: Literal["approve", "reject"]
) -> tuple[DecisionEffect, WhyNot | None]:
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
    effect, why = _effect_of(expected, resolution.verb)
    if why is not None:
        return Taken(effect=effect, acts=False, why_not=why)
    if held:
        return Taken(effect=effect, acts=False, why_not="held_os_layer_off")
    return Taken(effect=effect, acts=True, why_not=None)


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
        if (event.verb, event.effect, event.decision_offset) != (
            earlier.verb,
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
    expected = item_consequence(state, event.subtask_id, source=source_of(sub), scan_hits=())
    if (event.attempt, event.attempt_commit) != (now.number, expected.attempt_commit):
        msg = "a decision that names another attempt or commit than the record's"
        raise ValueError(msg)
    # What the log alone gives the verb. The scan's hits and the item's own line are not in the
    # log; the loop checked those when it took the decision, so a scan hit may only turn an
    # effect the log allows into recording, and nothing turns one it does not allow into an act.
    effect, why = _effect_of(expected, event.verb)
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
