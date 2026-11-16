"""What each decision on a queue item will do, in plain words, from the item's own record.

``physgate queue list`` prints these beside each open item, and the operator UI says the same
sentences beside its buttons, so a person knows before deciding that an approve which only
records will merge nothing, and what each choice does. Every sentence is made from the item's
``consequence`` record and nothing else: an item that states none gets no sentences, and nothing
is guessed. Nothing here decides anything or writes any record.
"""

from __future__ import annotations

from pathlib import Path

from physgate.orchestrator.events import Position
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.queue import (
    ItemConsequence,
    OnChoose,
    OnReject,
    QueueItem,
    QueueResolution,
    WhyRecordOnly,
    earlier_round,
    events_of_run,
    raised_again_problem,
    read_queue,
)
from physgate.orchestrator.replay import replay

_WHY: dict[WhyRecordOnly, str] = {
    "gate": "the physics gate refused the attempt, and a person overrides the reviewer alone",
    "change_check": (
        "the change check refused the attempt, and a person overrides the reviewer alone"
    ),
    "reading": (
        "the attempt's required reading was not completed, and a person overrides the reviewer "
        "alone"
    ),
    "indicator_in_history": "a review of this subtask confirmed a reward-hacking indicator",
    "scan_hit": ("the scan before review found a reward-hacking indicator that no review judged"),
    "source": "for an item of this kind a decision is recorded and changes nothing in the run",
    "legacy": "the item was listed before items said what a decision does",
}

#: What an order that is too long to review does to an order a person's note goes into.
_TOO_LONG = (
    "unless your note makes the order too long to review, when the subtask ends rejected instead"
)

_REJECT: dict[OnReject, str] = {
    "retry": (
        f"Rejecting spends this attempt, and the next attempt starts from your note, {_TOO_LONG}."
    ),
    "fix": (
        "Rejecting orders one fix by a fresh session, the subtask's last attempt, "
        f"{_TOO_LONG}. If the fix is not accepted, the subtask ends rejected."
    ),
    "end_subtask": "Rejecting ends the subtask as rejected. Nothing of it is merged.",
    "end_run": "Rejecting ends the run with no module dispatched.",
    "record_only": "",
}

#: Said once under the sentences: what no decision can be, and what the run may do with it.
NOTE = (
    "A decision cannot be edited or undone, and the item closes. The run may hold it until an "
    "operator confirms it."
)

#: A part's choices by position: the record says declare or find, not which of the three.
_PART: dict[str, str] = {
    "have": "the part is one you have, and what you stated of it is fixed.",
    "make": "the part is one you make, and what you stated of it is fixed.",
    "find": "the part is sourced and sized as before.",
}

_POSITION: dict[Position, str] = {
    "sizing": "sizing's value",
    "domain": "the domain's value",
    "producer": "the producer's work",
    "consumer": "the consumer's work",
    "have": "have",
    "make": "make",
    "find": "find",
}

_CHOOSE: dict[OnChoose, str] = {
    "retry": (
        "this attempt is spent, and the next one is told sizing's value as the graph holds it, "
        "and your note if you write one. Its reviewer is told what it was told."
    ),
    "fix": (
        "one fix is made by a fresh session in the subtask's working copy, told sizing's value "
        "as the graph holds it and your note if you write one. It is the subtask's last "
        "attempt; if it is not accepted, the subtask ends rejected."
    ),
    "end_subtask": "the subtask ends rejected, and nothing of it is merged.",
    "resize": (
        "the subtask waits while sizing's closing pass is ordered to write the domain's value "
        "into the graph; once that pass is merged, this attempt is judged again from its "
        "finished session, with no new session. If the pass writes another value, the dispute "
        "is ruled again."
    ),
    "reopen": (
        "the other module is reopened for one more attempt, its next or its one fix, told the "
        "interface's values it does not hold. Its earlier merge stays on the record, and the "
        "contract is tested again once it is merged."
    ),
    "record_only": "the decision is recorded, and nothing in the run acts on it.",
    "declare": "",
    "find": "",
}


def _indicators(consequence: ItemConsequence) -> list[str]:
    return [f"attempt {i.attempt} ({i.kind})" for i in consequence.confirmed_indicators]


def _why(consequence: ItemConsequence) -> str:
    named = _indicators(consequence)
    if consequence.why_record_only == "indicator_in_history" and named:
        if len(named) == 1:
            return f"the review of {named[0]} confirmed a reward-hacking indicator"
        joined = ", ".join(named)
        return f"reviews of this subtask confirmed reward-hacking indicators: {joined}"
    return _WHY[consequence.why_record_only or "source"]


def _choose(consequence: ItemConsequence, effect: OnChoose) -> str:
    named = _indicators(consequence)
    if effect != "reopen" or not named:
        return _CHOOSE[effect]
    found = (
        "A review of the module it reopens confirmed a reward-hacking indicator"
        if len(named) == 1
        else "Reviews of the module it reopens confirmed reward-hacking indicators"
    )
    return f"{_CHOOSE['reopen']} {found}: {', '.join(named)}."


def decision_sentences(
    item: QueueItem, *, refused: frozenset[str] = frozenset()
) -> dict[str, str] | None:
    """What each decision on ``item`` will do, by verb (and ``choose_<position>``), then a note.

    ``refused`` names positions the item's own decision refuses, which are not described.
    ``None`` where the item states no consequence: nothing is then said that the record does
    not say.
    """
    consequence = item.consequence
    if consequence is None:
        return None
    if consequence.on_approve == "release":
        approve = "Approving releases the hold, and the plan runs as it stands."
    elif consequence.on_approve == "merge_attempt":
        sha = consequence.attempt_commit
        commit = "" if sha is None else f" (commit {sha[:12]})"
        approve = (
            f"Approving puts attempt {consequence.attempt}{commit} into the run, merged exactly "
            "as shown, unless the merge conflicts or is refused, when an incident is recorded "
            "and nothing is merged."
        )
    else:
        what = "merge or change anything" if consequence.attempt is None else "merge this attempt"
        approve = (
            "Approving records your decision and closes this item for good. "
            f"It will not {what}, because {_why(consequence)}."
        )
    if consequence.on_reject == "record_only":
        reason = "" if consequence.why_record_only is None else f", because {_why(consequence)}"
        reject = (
            "Rejecting records your decision and closes this item for good. "
            f"It will not change anything in the run{reason}."
        )
    else:
        reject = _REJECT[consequence.on_reject]
    said = {"approve": approve, "reject": reject}
    for position, effect in (consequence.on_choose or {}).items():
        if position in refused:
            continue
        what = _PART.get(position) or _choose(consequence, effect)
        if effect in ("retry", "fix", "resize"):
            what += (
                " If your note makes the order too long to review, the subtask ends rejected "
                "instead."
            )
        elif effect == "reopen":
            what += (
                " If the order to reopen it is too long to review, nothing is reopened and the "
                "decision is only recorded."
            )
        said[f"choose_{position}"] = f"Choosing {_POSITION[position]}: {what}"
    said["note"] = NOTE
    return said


def _refused(item: QueueItem, resolved: dict[str, QueueResolution]) -> frozenset[str]:
    """The positions a part raised again refuses: ``find``, once it was had or made."""
    if item.source != "parts":
        return frozenset()
    before = earlier_round(item.item_id)
    earlier = resolved.get(before) if before is not None else None
    return frozenset(
        position
        for position in ("find",)
        if raised_again_problem(earlier, position, None) is not None
    )


def with_what_each_decision_does(listing: dict[str, object], run_dir: Path) -> dict[str, object]:
    """``listing``, each open item that states a consequence saying what each decision will do.

    The sentences are made from the item's own record and added to what ``queue list`` prints
    only; the queue's lines, and the listing the operator UI serves, are as they were. An item
    a reopen superseded is given none, since the run records a decision on it and does nothing
    else; where the run's log cannot be replayed, none is given either, since nothing says
    which items it superseded.
    """
    open_items = listing["open"]
    assert isinstance(open_items, list)  # noqa: S101 - queue_listing's own shape
    # The log the listing was just made from, read under the same cap, not read again.
    events = events_of_run(run_dir)
    superseded: set[str] = set()
    if events is not None:
        try:
            superseded = set(replay(events).superseded)
        except CorruptEventLogError:
            return {**listing, "open": [_unreplayable(entry) for entry in open_items]}
    view = read_queue(run_dir)
    resolved = {decision.item_id: decision for _, decision in view.decisions}
    items = {item.item_id: item for item in view.open_items()}
    out: list[object] = []
    for entry in open_items:
        item = items.get(entry["item_id"])
        if item is None or item.consequence is None:
            out.append(entry)
        elif item.item_id in superseded:
            out.append(
                {
                    **entry,
                    "why_no_sentences": (
                        "a reopen superseded this item, so a decision on it is only recorded"
                    ),
                }
            )
        else:
            said = decision_sentences(item, refused=_refused(item, resolved))
            out.append({**entry, "what_each_decision_does": said})
    return {**listing, "open": out}


def _unreplayable(entry: dict[str, object]) -> dict[str, object]:
    """``entry``, saying why it has no sentences when it states a consequence."""
    if entry.get("consequence") is None:
        return entry
    return {
        **entry,
        "why_no_sentences": (
            "the run's log could not be replayed, so what a decision does is not stated"
        ),
    }
