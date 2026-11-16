"""What each decision on a queue item will do, in plain words, from the item's own record.

``physgate queue list`` prints these beside each open item, and the operator UI says the same
sentences beside its buttons, so a person knows before deciding that an approve which only
records will merge nothing, and what each choice does. Every sentence is made from the item's
``consequence`` record and nothing else: an item that states none gets no sentences, and nothing
is guessed. Nothing here decides anything or writes any record.
"""

from __future__ import annotations

from physgate.orchestrator.events import Position
from physgate.orchestrator.queue import (
    ItemConsequence,
    OnChoose,
    OnReject,
    QueueItem,
    WhyRecordOnly,
)

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

_REJECT: dict[OnReject, str] = {
    "retry": "Rejecting spends this attempt, and the next attempt starts from your note.",
    "fix": (
        "Rejecting orders one fix by a fresh session, the subtask's last attempt. If it is not "
        "accepted, the subtask ends rejected."
    ),
    "end_subtask": "Rejecting ends the subtask as rejected. Nothing of it is merged.",
    "end_run": "Rejecting ends the run with no module dispatched.",
    "record_only": "",
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
    "declare": "the part is one you have or make, and what you stated of it is fixed.",
    "find": "the part is sourced and sized as before.",
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


def decision_sentences(item: QueueItem) -> dict[str, str] | None:
    """What each decision on ``item`` will do, by verb (and ``choose_<position>``).

    ``None`` where the item states no consequence: nothing is then said that the record does
    not say.
    """
    consequence = item.consequence
    if consequence is None:
        return None
    if consequence.on_approve == "release":
        approve = "Approving releases the hold, and the plan runs as it stands."
    elif consequence.on_approve == "merge_attempt":
        commit = (
            ""
            if consequence.attempt_commit is None
            else f" (commit {consequence.attempt_commit[:12]})"
        )
        approve = (
            f"Approving puts attempt {consequence.attempt}{commit} into the run, merged "
            "exactly as shown."
        )
    else:
        what = "merge or change anything" if consequence.attempt is None else "merge this attempt"
        approve = (
            f"Approving records your decision. It will not {what}, because {_why(consequence)}."
        )
    if consequence.on_reject == "record_only":
        reason = "" if consequence.why_record_only is None else f", because {_why(consequence)}"
        reject = f"Rejecting records your decision. It will not change anything in the run{reason}."
    else:
        reject = _REJECT[consequence.on_reject]
    said = {"approve": approve, "reject": reject}
    for position, effect in (consequence.on_choose or {}).items():
        said[f"choose_{position}"] = (
            f"Choosing {_POSITION[position]}: {_choose(consequence, effect)}"
        )
    return said
