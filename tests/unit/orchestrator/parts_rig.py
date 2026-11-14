"""A run that asks which parts a person has: its components, its queue, a loop over fakes.

The run acts on decisions where the OS layer runs, as every run that asks does. Its opening is
the one ``decompose`` writes, with the decomposition's line naming the components, and under
``design_review: on`` the review's lines after it. Every name the parts decision adds is looked
up when a row asks for it, so a row fails on an assertion, not at collection, in a tree
without it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import plan_hold_rig
from loop_fakes import FakeDispatcher, Rig, plan, usage

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import Component
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import (
    ApprovalQueue,
    PersonDecision,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import DecompositionCall, DecompositionSummary
from physgate.orchestrator.run_config import ModelStrings

RUN_ID = "run-1"
TS = "2026-11-12T10:00:00.000000Z"
STREAM = "decomposition/stdout.jsonl"
PLAN_DIGEST = plan_hold_rig.PLAN_DIGEST
SPEC_COMMIT = plan_hold_rig.SPEC_COMMIT
#: A role whose sessions are dispatched, so a released run goes past its plan.
MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"control": "claude-sonnet-5"},
    reviewers={"control": "claude-opus-5-5", "design": plan_hold_rig.DESIGN},
)

MOTOR = Component(
    node="control.motor_left",
    domain="control",
    role="control",
    label="Left drive motor",
    own=("mass",),
    shared=("stall_current",),
)
IMU = Component(
    node="control.imu", domain="control", role="control", label="IMU", own=("mass",), shared=()
)
BRACKET = Component(
    node="control.bracket", domain="control", role="control", label="Bracket", own=(), shared=()
)
COMPONENTS = (MOTOR, IMU, BRACKET)


def named(name: str, module: Any = queue_module) -> Any:  # noqa: ANN401 - whatever the name holds
    """``module``'s ``name``, or a failed assertion that says it is not built."""
    found = getattr(module, name, None)
    assert found is not None, f"{module.__name__} has no {name}"
    return found


def item_id(number: int, round_: int = 1) -> str:
    return str(named("parts_item_id")(RUN_ID, number, round_))


def item(component: Component = MOTOR, number: int = 1, of: int = 3) -> QueueItem:
    """The item a run lists for ``component``, the ``number``-th of its plan's ``of``."""
    built = named("parts_item")(
        item_id=item_id(number),
        run_id=RUN_ID,
        component=component,
        number=number,
        of=of,
        plan_sha256=PLAN_DIGEST,
        spec_commit=SPEC_COMMIT,
        stream=STREAM,
        ts=TS,
    )
    assert isinstance(built, QueueItem), built
    return built


def listed(run_dir: Path, *items: QueueItem) -> Path:
    """A run directory whose queue lists ``items`` (by default the motor's)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    queue = ApprovalQueue(run_dir / "queue.jsonl")
    for one in items or (item(),):
        queue.add(one)
    return run_dir


def body(declared: dict[str, tuple[Any, Any]] | None = None, texts: tuple[str, ...] = ()) -> Any:  # noqa: ANN401
    """A parts body: each name's value and unit, and the make texts."""
    return named("PartsBody").model_validate(
        {
            "declared": {
                name: {"value": value, "unit": unit}
                for name, (value, unit) in (declared or {}).items()
            },
            "texts": texts,
        }
    )


def person(
    position: str | None, parts: Any = None, verb: str = "choose", note: str | None = None
) -> Any:  # noqa: ANN401
    fields: dict[str, Any] = {"verb": verb, "note": note, "position": position}
    if parts is not None:
        assert "parts" in PersonDecision.model_fields, "a decision carries no parts body"
        fields["parts"] = parts
    return PersonDecision.model_validate(fields)


def shown(run_dir: Path, item_id_: str) -> ShownItem:
    view = read_queue(run_dir)
    assert item_id_ in view.digests, f"{item_id_} is not listed"
    return ShownItem(
        item_sha256=view.digests[item_id_], trajectories=statuses_now(run_dir, item_id_)
    )


def decide(
    run_dir: Path,
    item_id_: str,
    position: str | None,
    parts: Any = None,  # noqa: ANN401
    *,
    verb: str = "choose",
    note: str | None = None,
) -> Any:  # noqa: ANN401 - the recorded line, or why there is none
    """Decide ``item_id_`` as a person does from the listing; the line, or the refusal."""
    try:
        return record_decision(
            run_dir,
            item_id_,
            person=person(position, parts, verb, note),
            resolved_by="yasin",
            shown=shown(run_dir, item_id_),
        )
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001 - the refusal is what a row asserts on
        return exc


def decisions_bytes(run_dir: Path) -> bytes:
    return (run_dir / "queue_decisions.jsonl").read_bytes()


# -- a loop over fakes ---------------------------------------------------------------------


def rig(
    run_dir: Path, *, design_review: str = "off", parts: str = "on", gate_mode: str = "on"
) -> Rig:
    """A rig over the run: acting where the OS layer runs, asking about parts unless told not."""
    run_dir.mkdir(parents=True, exist_ok=True)
    overrides: dict[str, Any] = {
        "design_review": design_review,
        "models": MODELS,
        "queue_decisions": "act",
        "os_layer": plan_hold_rig.PRESENT,
        "parts_on_hand": parts,
    }
    return Rig(
        run_dir,
        gate_mode=gate_mode,  # type: ignore[arg-type]  # a test names one of the three
        config_overrides=overrides,
        dispatcher=FakeDispatcher(trajectories=run_dir / "sessions"),
    )


def summary(components: tuple[Component, ...] | None) -> Any:  # noqa: ANN401
    """The decomposition's summary, naming ``components`` where the summary can."""
    fields: dict[str, Any] = {
        "session_id": plan_hold_rig.SESSION,
        "model": "claude-sonnet-5",
        "num_turns": 1,
        "subtasks": 2,
        "interface_nodes": ("iface.bus",),
        "spec_commit": SPEC_COMMIT,
        "head_revision": 1,
        "plan_sha256": PLAN_DIGEST,
    }
    if components is not None:
        assert "components" in DecompositionSummary.model_fields, (
            "the decomposition's summary names no components"
        )
        fields["components"] = components
    return DecompositionSummary(**fields)


def _entries() -> list[Any]:
    return [entry.model_copy(update={"assigned_role": "control"}) for entry in plan("s1", "s2")]


def opened(the_rig: Rig, components: tuple[Component, ...] | None = COMPONENTS) -> Loop:
    """A loop over a run started as ``decompose`` starts one that does not review its plan.

    Nothing lists an item: that is the command's next write, which this opening stops before.
    """
    loop = the_rig.open()
    spent = (MessageUsage(message_id="d1", usage=usage(10)),)
    stream = the_rig.run_dir / STREAM
    stream.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": "m1", "model": "claude-sonnet-5", "content": []}
    stream.write_text(json.dumps({"type": "assistant", "message": message}) + "\n")
    loop.record.start(
        _entries(),
        call=DecompositionCall(session_id=plan_hold_rig.SESSION, usage=spent),
        decomposed=summary(components),
    )
    plan_hold_rig.layer(loop)
    return loop


def started(
    run_dir: Path,
    components: tuple[Component, ...] | None = COMPONENTS,
    *,
    gate_mode: str = "on",
) -> Rig:
    """A run that asks, opened and closed: the next process drives it."""
    the_rig = rig(run_dir, gate_mode=gate_mode)
    loop = plan_hold_rig.outcome_of(lambda: opened(the_rig, components))
    assert isinstance(loop, Loop), loop
    loop.close()
    return the_rig


def parts_items(run_dir: Path) -> list[QueueItem]:
    return [one for one in read_queue(run_dir).items if str(one.source) == "parts"]


def find_all(run_dir: Path) -> None:
    """Choose ``find`` on every open parts item, each on its own view."""
    for one in read_queue(run_dir).open_items():
        if str(one.source) == "parts":
            found = decide(run_dir, one.item_id, "find")
            assert not isinstance(found, Exception), found


def opened_reviewed(the_rig: Rig, components: tuple[Component, ...] = COMPONENTS) -> Loop:
    """A loop over a run that also reviews its plan, under ``on``, its review failed."""
    from journal_helper import one_round

    from physgate.orchestrator.record import PlanReviewed
    from physgate.orchestrator.trajectory import seal

    loop = the_rig.open()
    stream = the_rig.run_dir / STREAM
    stream.parent.mkdir(parents=True, exist_ok=True)
    message = {"id": "m1", "model": "claude-sonnet-5", "content": []}
    stream.write_text(json.dumps({"type": "assistant", "message": message}) + "\n")
    reviewed = PlanReviewed.model_validate(
        {
            "install": plan_hold_rig.INSTALL,
            "stream_seal": seal(stream.read_bytes()),
            "session_id": plan_hold_rig.REVIEW_SESSION,
            "usage": (MessageUsage(message_id="r1", usage=usage(5)),),
            "result": plan_hold_rig.verdict("fail"),
        }
    )
    spent = (MessageUsage(message_id="d1", usage=usage(10)),)
    proposals = one_round(
        the_rig.run_dir,
        session=plan_hold_rig.SESSION,
        plan=plan_hold_rig.PLAN_BYTES,
        reviewed=reviewed,
        spent=spent,
        design_review="on",
        holds=True,
    )
    loop.record.start(
        _entries(),
        proposals=proposals,
        call=DecompositionCall(session_id=plan_hold_rig.SESSION, usage=spent),
        decomposed=summary(components),
        reviewed=reviewed,
    )
    plan_hold_rig.layer(loop)
    return loop


def log_of(run_dir: Path) -> list[dict[str, Any]]:
    """The run's event log, each line as it was written."""
    return [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]


def taken(
    log: list[dict[str, Any]], number: int = 1, position: Any = "find", **fields: Any
) -> dict[str, Any]:  # noqa: ANN401
    """A ``decision_taken`` line on the ``number``-th part, as the loop writes a choice."""
    line: dict[str, Any] = {
        **{key: log[-1][key] for key in ("seq", "ts", "run_id", "gate_mode")},
        "kind": "decision_taken",
        "subtask_id": None,
        "item_id": f"{RUN_ID}-parts-{number}",
        "verb": "choose",
        "position": position,
        "note": None,
        "resolved_by": "yasin",
        "decided_ts": log[-1]["ts"],
        "decision_offset": 0,
        "shown_sha256": "a" * 64,
        "attempt": None,
        "attempt_commit": None,
        "effect": "find" if position == "find" else "declare",
        "acts": True,
        "why_not": None,
    }
    if position in ("have", "make"):
        line["parts_sha256"] = "b" * 64
    line.update(fields)
    return {key: value for key, value in line.items() if value is not ...}


def dispatch(log: list[dict[str, Any]]) -> dict[str, Any]:
    """The first dispatch of the run: its first planned subtask's first stage."""
    envelope = {key: log[-1][key] for key in ("seq", "ts", "run_id", "gate_mode")}
    return {
        **envelope,
        "kind": "stage_entered",
        "subtask_id": "s1",
        "attempt": 1,
        "stage": "resolve",
    }
