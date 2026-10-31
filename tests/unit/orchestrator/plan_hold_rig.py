"""A run whose plan's review holds it under ``on``: its opening, a loop over fakes, a decision.

The opening is the one ``decompose`` writes: the call's tokens, the plan, the review's tokens and
its line, with the call's stream where the call writes it and sealed as it stands. The loop is the
fakes' rig, in a run that acts on decisions where the OS layer runs, or one that records only.
Every name the hold adds is looked up when a test asks for it, so a test of it fails on an
assertion, not at collection, in a tree without it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loop_fakes import FakeDispatcher, KilledError, Rig, plan, usage

from physgate.orchestrator.events import Event, OsLayerChecked, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import (
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
)
from physgate.orchestrator.queue import (
    PersonDecision,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import DecompositionCall, DecompositionSummary
from physgate.orchestrator.run_config import ModelStrings
from physgate.orchestrator.trajectory import seal
from physgate.oslayer.probe import Present

DESIGN = "claude-opus-5-5"
MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"electrical": "claude-sonnet-5"},
    reviewers={"electrical": "claude-opus-5-5", "design": DESIGN},
)
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ITEM = "run-1-plan"
SPEC_COMMIT = "c" * 40
PLAN_DIGEST = "d" * 64
FINDING = "the plan leaves the bus unprotected"
SESSION = "decomposition-session-1"
REVIEW_SESSION = "review-session-1"
INSTALL = {"path": "/install", "action": "checked", "seconds": 0.5, "entries": 3}


def verdict(name: str = "fail") -> ReviewResult:
    """A review of the plan: a fail names one failing item; a blocked one a blocking defect."""
    items = (
        (
            ItemVerdict(
                item="every interface has one owner",
                section="domain_standards",
                result="unmet",
                evidence="plan: iface.bus",
            ),
        )
        if name == "fail"
        else ()
    )
    defects = (
        (SpecDefect(finding="the brief gives no supply voltage", blocking=True),)
        if name == "blocked"
        else ()
    )
    return ReviewResult(
        verdict=name,  # type: ignore[arg-type]
        finding=FINDING,
        reviewer_model=DESIGN,
        session_id=REVIEW_SESSION,
        usage=(MessageUsage(message_id="r1", usage=usage(5)),),
        items=items,
        spec_defects=defects,
    )


UNAVAILABLE = {
    "cause": "reading_incomplete",
    "detail": "a required file was not read in full",
    "session_id": REVIEW_SESSION,
    "reviewer_model": DESIGN,
}


def rig(run_dir: Path, *, acts: bool = True, design_review: str = "on", **kw: Any) -> Rig:
    """A rig over the run, under ``design_review``, acting on decisions or recording them."""
    run_dir.mkdir(parents=True, exist_ok=True)
    overrides: dict[str, Any] = {"design_review": design_review, "models": MODELS}
    if acts:
        overrides |= {"queue_decisions": "act", "os_layer": PRESENT}
    kw.setdefault("dispatcher", FakeDispatcher(trajectories=run_dir / "sessions"))
    return Rig(run_dir, config_overrides=overrides, **kw)


def stream_path(run_dir: Path) -> Path:
    return run_dir / "decomposition" / "stdout.jsonl"


def _stream(run_dir: Path) -> Any:  # noqa: ANN401 - the stream's seal
    path = stream_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": "m1", "model": "claude-sonnet-5", "content": []}
    path.write_text(json.dumps({"type": "assistant", "message": message}) + "\n")
    return seal(path.read_bytes())


def layer(loop: Loop) -> None:
    """The OS layer, present, as the command records it before anything is driven."""
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": PRESENT, "as_recorded": None}
        )
    )


def opened(
    the_rig: Rig, *, review: str | None = "fail", ids: tuple[str, ...] = ("s1", "s2")
) -> Loop:
    """A loop over a run started as ``decompose`` starts it, its review ``review``.

    ``review`` names a verdict, or is ``None`` for a review that reached none. Nothing lists the
    plan's item: that is the command's next write, which this opening stops before.
    """
    from physgate.orchestrator.record import PlanReviewed

    loop = the_rig.open()
    sealed = _stream(the_rig.run_dir)
    ending: dict[str, Any] = (
        {"result": verdict(review)} if review is not None else {"unavailable": UNAVAILABLE}
    )
    reviewed = PlanReviewed.model_validate(
        {
            "install": INSTALL,
            "stream_seal": sealed,
            "session_id": REVIEW_SESSION,
            "usage": (MessageUsage(message_id="r1", usage=usage(5)),),
            **ending,
        }
    )
    loop.record.start(
        plan(*ids),
        call=DecompositionCall(
            session_id=SESSION, usage=(MessageUsage(message_id="d1", usage=usage(10)),)
        ),
        decomposed=DecompositionSummary(
            session_id=SESSION,
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(ids),
            interface_nodes=("iface.bus",),
            spec_commit=SPEC_COMMIT,
            head_revision=1,
            plan_sha256=PLAN_DIGEST,
        ),
        reviewed=reviewed,
    )
    if the_rig.config_overrides.get("queue_decisions") == "act":
        layer(loop)
    return loop


def outcome_of(how: Callable[[], Any]) -> Any:  # noqa: ANN401 - whatever came of it
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the test asserts on
        return exc


def again(the_rig: Rig, *, kill_after: str | None = None) -> str:
    """A fresh process runs the run: the step it ends at, or ``killed`` after a line of a kind."""
    loop = the_rig.open()
    if the_rig.config_overrides.get("queue_decisions") == "act":
        layer(loop)
    if kill_after is not None:
        real = loop.record.emit

        def emit(event: Event) -> None:
            real(event)
            if event.kind == kill_after:
                raise KilledError(kill_after)

        loop.record.emit = emit  # type: ignore[method-assign]
    try:
        found = outcome_of(loop.run)
    finally:
        loop.close()
    if isinstance(found, KilledError):
        return "killed"
    assert not isinstance(found, Exception), found
    return str(found.kind)


def items(run_dir: Path) -> list[QueueItem]:
    return list(read_queue(run_dir).items)


def decide(run_dir: Path, verb: str, note: str | None = None, item_id: str = ITEM) -> None:
    """Decide the item as a person does from the listing: bound to the digest it printed."""
    view = read_queue(run_dir)
    assert item_id in view.digests, "the item is not listed"
    shown = ShownItem(
        item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
    )
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(verb=verb, note=note),  # type: ignore[arg-type]
        resolved_by="yasin",
        shown=shown,
    )


def lines(run_dir: Path) -> list[Event]:
    return list(read_events(run_dir / "events.jsonl"))


def kinds(run_dir: Path) -> list[str]:
    return [event.kind for event in lines(run_dir)]


def dispatched(run_dir: Path) -> list[str]:
    """Every dispatch on the record: each stage entered, and the integration call's lines."""
    return [
        k
        for k in kinds(run_dir)
        if k in ("stage_entered", "integration_gate_ran", "integration_escalated")
    ]
