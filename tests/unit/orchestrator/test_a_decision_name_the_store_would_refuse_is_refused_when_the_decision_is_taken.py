"""A name the store would refuse is refused where the decision is taken, and nothing is written.

The store holds the operator's name on a declared quantity to a length. The queue used to take a
longer name, record the decision, and leave the first declared part built from it refused by the
store, with the run halted on an incident that a decision, once taken, cannot be taken again to
clear. The name is now held to the store's own rule by the one function that records a decision,
so the command line, the operator UI and the queue's own ``resolve`` are all held to it. A line
already on a record is read as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from parts_rig import (
    IMU,
    MOTOR,
    body,
    decide,
    decisions_bytes,
    item,
    listed,
    person,
    shown,
    started,
)
from plan_hold_rig import again, kinds
from sign_off_rig import signing

from physgate.cli import main
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.parts_write import parts_payload
from physgate.orchestrator.queue import (
    ApprovalQueue,
    PersonDecision,
    QueueItem,
    QueueResolution,
    ShownItem,
    read_queue,
    record_decision,
)
from physgate.orchestrator.replay import replay
from physgate.state.schema import Declared
from physgate.state.store import Store
from physgate.ui.server import require_operator

PLAIN = "r-s1"
IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]
STATED = {"mass": (0.4, "kg"), "stall_current": (2.4, "A")}
#: What the store holds an operator's name to, read off its own field.
LIMIT = next(
    m.max_length
    for m in Declared.model_fields["operator"].metadata
    if getattr(m, "max_length", None) is not None
)
FITS = "o" * LIMIT
TOO_LONG = "o" * (LIMIT + 1)


def _decided_by(run_dir: Path, item_id: str, name: str, position: str = "have") -> QueueResolution:
    return record_decision(
        run_dir,
        item_id,
        person=person(position, body(STATED) if position == "have" else None),
        resolved_by=name,
        shown=shown(run_dir, item_id),
    )


def _waiting(tmp_path: Path) -> Any:  # noqa: ANN401 - the rig, which holds the run's store
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    return the_rig


def _item_run(tmp_path: Path) -> Path:
    """A run whose one open item is a plain approval, which free text decides."""
    run_dir = tmp_path / "queue"
    run_dir.mkdir(parents=True)
    ApprovalQueue(run_dir / "queue.jsonl").add(
        QueueItem(
            item_id=PLAIN,
            ts="2026-10-11T00:00:00.000000Z",
            run_id="r",
            subtask_id="s1",
            source="repair_budget_exhausted",
            decision_required="Decide.",
            artefact_diff="",
            triggering_finding="a finding",
            quantities=(),
            trajectories=("sessions/a/stdout.jsonl",),
        )
    )
    return run_dir


def _decided(run_dir: Path) -> list[str]:
    return [one.item_id for _, one in read_queue(run_dir).decisions]


def _events_size(run_dir: Path) -> int:
    return (run_dir / "events.jsonl").stat().st_size


def _main(*args: str) -> Any:  # noqa: ANN401 - the exit code, however the command ended
    try:
        return main(list(args))
    except SystemExit as exc:
        return exc.code


# -- the function every path goes through ----------------------------------------------------


def test_a_name_of_the_stores_length_is_taken_and_one_character_more_is_refused(
    tmp_path: Path,
) -> None:
    the_rig = _waiting(tmp_path)
    run_dir = the_rig.run_dir
    before = decisions_bytes(run_dir) if (run_dir / "queue_decisions.jsonl").exists() else b""
    events = _events_size(run_dir)
    with pytest.raises(QueueError) as refused:
        _decided_by(run_dir, IDS[0], TOO_LONG)
    assert str(LIMIT) in str(refused.value) and str(LIMIT + 1) in str(refused.value)
    assert not (run_dir / "queue_decisions.jsonl").exists() or decisions_bytes(run_dir) == before
    assert _events_size(run_dir) == events
    taken = _decided_by(run_dir, IDS[0], FITS)
    assert taken.resolved_by == FITS


def test_a_refused_name_leaves_the_item_open_to_be_decided_with_a_shorter_one(
    tmp_path: Path,
) -> None:
    the_rig = _waiting(tmp_path)
    run_dir = the_rig.run_dir
    with pytest.raises(QueueError):
        _decided_by(run_dir, IDS[0], TOO_LONG)
    assert IDS[0] in {one.item_id for one in read_queue(run_dir).open_items()}
    assert decide(run_dir, IDS[0], "find") is not None
    assert IDS[0] not in {one.item_id for one in read_queue(run_dir).open_items()}


@pytest.mark.parametrize("name", ["", "   ", "two\nlines"])
def test_a_name_the_store_would_refuse_for_its_shape_is_refused_too(
    tmp_path: Path, name: str
) -> None:
    run_dir = _item_run(tmp_path)
    with pytest.raises(QueueError):
        record_decision(run_dir, PLAIN, decision="approve", resolved_by=name)
    assert _decided(run_dir) == []


def test_a_free_text_decision_is_held_to_the_same_limit(tmp_path: Path) -> None:
    run_dir = _item_run(tmp_path)
    with pytest.raises(QueueError, match=str(LIMIT)):
        record_decision(run_dir, PLAIN, decision="approve", resolved_by=TOO_LONG)
    assert _decided(run_dir) == []
    record_decision(run_dir, PLAIN, decision="approve", resolved_by=FITS)
    assert _decided(run_dir) == [PLAIN]


def test_the_queues_own_resolve_is_held_to_the_same_limit(tmp_path: Path) -> None:
    run_dir = _item_run(tmp_path)
    queue = ApprovalQueue(run_dir / "queue.jsonl")
    with pytest.raises(QueueError, match=str(LIMIT)):
        queue.resolve(PLAIN, decision="approve", resolved_by=TOO_LONG)
    assert _decided(run_dir) == []
    queue.resolve(PLAIN, decision="approve", resolved_by=FITS)
    assert _decided(run_dir) == [PLAIN]


# -- the command line ----------------------------------------------------------------------


def test_the_command_line_refuses_a_long_name_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _item_run(tmp_path)
    args = ("queue", "resolve", PLAIN, "--run-dir", str(run_dir), "--decision", "approve")
    assert _main(*args, "--by", TOO_LONG) == 2
    assert str(LIMIT) in capsys.readouterr().err
    assert _decided(run_dir) == []
    assert _main(*args, "--by", FITS) == 0
    assert _decided(run_dir) == [PLAIN]


def test_the_command_line_refuses_a_long_name_on_a_part_and_the_part_stays_open(
    tmp_path: Path,
) -> None:
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))
    digest = read_queue(run_dir).digests[IDS[0]]
    args = ("queue", "resolve", IDS[0], "--run-dir", str(run_dir), "--sha256", digest)
    args += ("--choose", "find")
    assert _main(*args, "--by", TOO_LONG) == 2
    assert _decided(run_dir) == []
    assert (
        _main("queue", "parts", "--run-dir", str(run_dir), "--find-remaining", "--by", TOO_LONG)
        == 2
    )
    assert _decided(run_dir) == []
    assert _main(*args, "--by", FITS) == 0


# -- the page's server -----------------------------------------------------------------------


def test_the_operator_a_page_server_takes_at_start_is_held_to_the_stores_length() -> None:
    assert require_operator(FITS) == FITS
    with pytest.raises(Exception, match=str(LIMIT)):
        require_operator(TOO_LONG)


# -- the run that was lost ------------------------------------------------------------------


def test_a_long_name_never_reaches_the_store_so_the_run_goes_on(tmp_path: Path) -> None:
    the_rig = _waiting(tmp_path)
    run_dir = the_rig.run_dir
    with pytest.raises(QueueError):
        _decided_by(run_dir, IDS[0], TOO_LONG)
    assert isinstance(_decided_by(run_dir, IDS[0], FITS), QueueResolution)
    assert isinstance(decide(run_dir, IDS[1], "find"), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    step = signing(lambda: again(the_rig), run_dir)
    assert step == "done"
    assert "incident" not in kinds(run_dir)


# -- the rule is the store's --------------------------------------------------------------


def _node_by(operator: str) -> dict[str, Any]:
    quantity = {
        "value": 0.4,
        "unit": "kg",
        "source": "declared by the person",
        "written_by": "control",
        "declared": {"item_id": IDS[0], "decision_sha256": "a" * 64, "operator": operator},
    }
    return {
        "id": "control.motor_left",
        "kind": "component",
        "domain": "control",
        "owner_role": "control",
        "quantities": {"mass": quantity},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-12T10:00:00.000000Z",
    }


def test_the_store_itself_takes_a_name_the_queue_takes_and_refuses_one_it_refuses(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "graph")
    refused = store.declare(_node_by(TOO_LONG), (IDS[0],))  # type: ignore[attr-defined]
    assert (refused.accepted, refused.reason) == (False, "declare_refused")
    assert store.head_revision() == 0
    taken = store.declare(_node_by(FITS), (IDS[0],))  # type: ignore[attr-defined]
    assert taken.accepted


# -- what a record already holds is read as before -----------------------------------------


def _hand_written(run_dir: Path, item_id: str, name: str) -> None:
    """The line an earlier writer put on the record: the same line, with no check made."""
    now = "2026-01-01T00:00:00.000000Z"
    view = read_queue(run_dir)
    line = QueueResolution.model_validate(
        {
            "item_id": item_id,
            "ts": now,
            "decision": "choose have",
            "resolved_by": name,
            "verb": "choose",
            "position": "have",
            "shown_sha256": view.digests[item_id],
            "parts": body(STATED),
        }
    )
    with (run_dir / "queue_decisions.jsonl").open("ab") as out:
        out.write(line.model_dump_json().encode() + b"\n")


def test_a_record_that_holds_a_long_name_replays_to_the_state_it_always_did(
    tmp_path: Path,
) -> None:
    the_rig = _waiting(tmp_path)
    run_dir = the_rig.run_dir
    _hand_written(run_dir, IDS[0], "o" * 69)
    assert isinstance(decide(run_dir, IDS[1], "find"), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    assert [d.resolved_by for _, d in read_queue(run_dir).decisions][0] == "o" * 69
    step = signing(lambda: again(the_rig), run_dir)
    # The run ends as it did, and its record replays with the long name in it.
    assert step == "done"
    assert "incident" not in kinds(run_dir)
    state = replay(read_events(run_dir / "events.jsonl"))
    assert state.parts_released is not None
    assert [node for node, _, _ in state.parts_landed] == [
        "control.motor_left",
        "sizing.control_motor_left",
    ]
    assert replay(read_events(run_dir / "events.jsonl")).parts_landed == state.parts_landed


# -- the number, the characters it counts, and the order of the refusals -------------------


def _free_text_by(tmp_path: Path, name: str) -> None:
    record_decision(_item_run(tmp_path), PLAIN, decision="approve", resolved_by=name)


def test_the_limit_is_sixty_four_characters_written_out(tmp_path: Path) -> None:
    assert LIMIT == 64
    assert require_operator("o" * 64) == "o" * 64
    _free_text_by(tmp_path / "fits", "o" * 64)
    with pytest.raises(QueueError):
        _free_text_by(tmp_path / "over", "o" * 65)


def test_a_name_is_counted_in_characters_not_bytes(tmp_path: Path) -> None:
    assert len(("é" * 64).encode()) > 64
    _free_text_by(tmp_path / "fits", "é" * 64)
    with pytest.raises(QueueError):
        _free_text_by(tmp_path / "over", "é" * 65)


def test_a_name_in_wide_characters_is_taken_at_sixty_four_and_refused_at_sixty_five(
    tmp_path: Path,
) -> None:
    the_rig = _waiting(tmp_path)
    run_dir = the_rig.run_dir
    with pytest.raises(QueueError):
        _decided_by(run_dir, IDS[0], "é" * 65)
    assert _decided_by(run_dir, IDS[0], "é" * 64).resolved_by == "é" * 64


def test_a_name_checked_first_answers_before_an_unknown_decided_or_stale_item(
    tmp_path: Path,
) -> None:
    run_dir = _item_run(tmp_path)
    record_decision(run_dir, PLAIN, decision="approve", resolved_by="yasin")
    for item_id in ("nowhere", PLAIN):
        with pytest.raises(QueueError, match=str(LIMIT)):
            record_decision(run_dir, item_id, decision="approve", resolved_by=TOO_LONG)
    stale = ShownItem(item_sha256="0" * 64, trajectories=())
    other = _item_run(tmp_path / "other")
    with pytest.raises(QueueError, match=str(LIMIT)):
        record_decision(
            other,
            PLAIN,
            person=PersonDecision(verb="approve", note=None),
            resolved_by=TOO_LONG,
            shown=stale,
        )


@pytest.mark.parametrize("name", [" ", "two\nlines", TOO_LONG])
@pytest.mark.parametrize("how", ["free text", "reject"])
def test_a_decision_that_declares_nothing_is_held_to_the_name_rule_too(
    tmp_path: Path, name: str, how: str
) -> None:
    run_dir = _item_run(tmp_path)
    shown_ = shown(run_dir, PLAIN)
    with pytest.raises(QueueError):
        if how == "free text":
            record_decision(run_dir, PLAIN, decision="approve", resolved_by=name)
        else:
            said = PersonDecision(verb=how, note="no" if how == "reject" else None)  # type: ignore[arg-type]
            record_decision(run_dir, PLAIN, person=said, resolved_by=name, shown=shown_)
    assert _decided(run_dir) == []


# -- the decision, then the declare it leads to, on the real store -------------------------


def _declare_from(run_dir: Path, store: Store) -> Any:  # noqa: ANN401 - the store's answer
    (_, decision), *_ = read_queue(run_dir).decisions
    assert decision.parts is not None
    payload = parts_payload(
        MOTOR,
        shared=False,
        owner_role=MOTOR.role,
        item_id=decision.item_id,
        body=decision.parts,
        operator=decision.resolved_by,
        decided_ts="2026-11-12T10:00:00.000000Z",
    )
    assert payload is not None
    return store.declare(payload, (decision.item_id,))  # type: ignore[attr-defined]


def test_a_decision_with_a_name_the_store_refuses_is_never_recorded_so_nothing_is_declared(
    tmp_path: Path,
) -> None:
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))
    with pytest.raises(QueueError):
        _decided_by(run_dir, IDS[0], "o" * 65)
    assert _decided(run_dir) == []
    assert b"o" * 65 not in decisions_bytes(run_dir)


def test_a_decision_with_a_name_of_sixty_four_characters_is_declared_under_that_name(
    tmp_path: Path,
) -> None:
    run_dir = listed(tmp_path / "run", item(MOTOR, 1, 2), item(IMU, 2, 2))
    _decided_by(run_dir, IDS[0], "o" * 64)
    store = Store(tmp_path / "graph")
    answer = _declare_from(run_dir, store)
    assert (answer.accepted, answer.reason) == (True, None)
    held = store.read_node(MOTOR.node)
    assert held["quantities"]["mass"]["declared"]["operator"] == "o" * 64
