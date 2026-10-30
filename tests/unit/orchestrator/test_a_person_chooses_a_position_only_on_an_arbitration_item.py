"""A person chooses a position only on an arbitration item, and the choice is recorded and taken.

The verb ``choose`` names one ``position`` of the set the item's kind offers, and only an
arbitration item offers one: ``sizing`` (the graph's value stands) or ``domain`` (the disputing
subtask's). The decision's text is exactly ``choose <position>``, with ``: <note>`` when there is
a note. The writer, every reader of the decisions file and the replay of the event log refuse a
choice anywhere else, and a position outside the item's set. The item says what each position
does before anyone decides (``on_choose``), and in this build both record only: a choice is taken
into the run, with its position, and acts on nothing. Approve and reject on an arbitration item
still record only, and arbitration stays out of the sources whose streams are scanned before an
approve. Choosing the domain carries a session's typed value forward, so it binds only to a view
whose transcripts all held their seal, as an approve does; choosing sizing keeps the graph's value
and binds to any view, as a reject does. An item that is not the one the record builds halts the
run at take, whatever position was chosen. Every item of another kind keeps its bytes.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import (  # noqa: E402
    KilledByRowError,
    driven,
    events_of,
    refusal,
    resume,
    rig_of,
)
from loop_fakes import FakeReviewer, Rig  # noqa: E402
from test_a_queue_decision_acts_at_a_boundary import (  # noqa: E402
    NO_VERDICT,
    _layer,
    _resume,
    _rig,
    _start,
    decide,
)

from physgate import roles  # noqa: E402
from physgate.cli import main  # noqa: E402
from physgate.orchestrator import queue as queue_module  # noqa: E402
from physgate.orchestrator.decisions import SCANNED_SOURCES  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    DecisionTaken,
    Event,
    Incident,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, QueueError  # noqa: E402
from physgate.orchestrator.queue import (  # noqa: E402
    DECISIONS_NAME,
    QUEUE_NAME,
    QueueItem,
    QueueResolution,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.replay import replay  # noqa: E402

TS = "2026-10-30T09:00:00.000000Z"
SHA = "b" * 64


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def one(found: Any) -> Any:  # noqa: ANN401 - whatever the row lists
    found = list(found)
    assert len(found) == 1, found
    return found[0]


def taken(events: list[Event]) -> list[DecisionTaken]:
    return [e for e in events if isinstance(e, DecisionTaken)]


def person(position: str, note: str | None = None) -> Any:  # noqa: ANN401 - the queue's model
    """A person's choice, as the decision function takes it."""
    return queue_module.PersonDecision.model_validate(
        {"verb": "choose", "position": position, "note": note}
    )


def chose(run_dir: Path, position: str, note: str | None = None) -> QueueResolution:
    """Choose ``position`` on the open item as a person does from the listing; an escape fails."""
    try:
        view = read_queue(run_dir)
        item = one(view.open_items())
        shown = ShownItem(
            item_sha256=view.digests[item.item_id],
            trajectories=statuses_now(run_dir, item.item_id),
        )
        return record_decision(
            run_dir, item.item_id, person=person(position, note), resolved_by="yasin", shown=shown
        )
    except Exception as exc:  # noqa: BLE001 - any escape is the finding
        raise AssertionError(f"the choice was not recorded: {exc!r}") from None


def refused(act: Callable[[], object]) -> str:
    """Why the queue refused ``act``, asserted to be the queue's own refusal."""
    try:
        act()
    except QueueError as exc:
        return f"{exc} {exc.context}"
    except Exception as exc:  # noqa: BLE001 - refused by no rule of the queue's is the finding
        raise AssertionError(f"refused by no rule of the queue's: {exc!r}") from None
    raise AssertionError("not refused")


def model_refusal(model: type[Any], data: dict[str, Any]) -> str:
    """Why ``model`` refuses ``data``, asserted to be a validation refusal."""
    try:
        model.model_validate(data)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"{model.__name__} took {data}")


def arbitrated(tmp_path: Path) -> Rig:
    """A run whose domain subtask disputed sizing's value to a person: one open item."""
    rig = rig_of(tmp_path / "run")
    driven(rig)
    assert one(read_queue(rig.run_dir).open_items()).source == "arbitration"
    return rig


# --- the field and the set ---------------------------------------------------------------------


def test_only_an_arbitration_item_offers_positions_and_they_are_sizing_and_domain() -> None:
    assert getattr(queue_module, "POSITIONS", None) == {"arbitration": ("sizing", "domain")}
    assert "choose" in getattr(queue_module.Verb, "__args__", ())


def test_a_choice_s_text_is_the_verb_the_position_and_the_note() -> None:
    try:
        bare, noted = person("sizing"), person("domain", "the domain's 5 A holds")
    except Exception as exc:  # noqa: BLE001 - not yet a decision is the finding
        raise AssertionError(f"a choice is not a decision: {exc!r}") from None
    assert bare.text() == "choose sizing"
    assert noted.text() == "choose domain: the domain's 5 A holds"
    line = {
        "item_id": "run-1-s1", "ts": TS, "kind": "resolution", "decision": "choose domain",
        "resolved_by": "yasin", "verb": "choose", "position": "domain", "shown_sha256": SHA,
    }  # fmt: skip
    try:
        record = QueueResolution.model_validate(line)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"a choice's line does not read: {exc!r}") from None
    assert record.model_dump_json() == json.dumps(line, separators=(",", ":"))


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"position": None}, "a position is chosen with choose, and only with it"),
        ({"verb": "approve", "decision": "approve"}, "a position is chosen with choose, and only"),
        ({"position": "producer"}, "domain"),
        ({"decision": "choose sizing"}, "a decision's text is exactly its verb, position and note"),
        ({"decision": "choose domain: why"}, "exactly its verb, position and note"),
    ],
    ids=["choose without a position", "a position on another verb", "outside the set",
         "the other position's text", "a note the line does not carry"],
)  # fmt: skip
def test_a_choice_that_is_not_its_verb_position_and_note_is_refused(
    change: dict[str, Any], says: str
) -> None:
    line = {
        "item_id": "run-1-s1", "ts": TS, "decision": "choose domain", "resolved_by": "yasin",
        "verb": "choose", "position": "domain", "shown_sha256": SHA,
    } | change  # fmt: skip
    assert says in model_refusal(QueueResolution, line)


def test_a_person_s_choice_is_held_to_the_same_rules() -> None:
    PersonDecision = queue_module.PersonDecision  # noqa: N806 - the model
    said = model_refusal(PersonDecision, {"verb": "choose", "note": None})
    assert "a position is chosen with choose, and only with it" in said
    said = model_refusal(PersonDecision, {"verb": "reject", "position": "sizing", "note": "x"})
    assert "a position is chosen with choose, and only with it" in said
    said = model_refusal(PersonDecision, {"verb": "choose", "position": "sizing", "note": "\x1b"})
    assert "control character" in said


# --- where it is accepted and where refused ----------------------------------------------------


def _hand_queue(tmp_path: Path, source: str) -> Path:
    """A run directory whose queue lists one item of ``source``, written as the writer writes."""
    run_dir = tmp_path / source
    run_dir.mkdir()
    item = QueueItem(
        item_id="run-1-s1", ts=TS, run_id="run-1",
        subtask_id="integration" if source == "gate_escalation" else "s1",
        source=source,  # type: ignore[arg-type]  # each of the queue's sources, by name
        decision_required="Decide.", artefact_diff="", triggering_finding="a finding",
        quantities=(), trajectories=("sessions/a/stdout.jsonl",),
    )  # fmt: skip
    (run_dir / QUEUE_NAME).write_bytes(item.model_dump_json().encode() + b"\n")
    (run_dir / DECISIONS_NAME).write_bytes(b"")
    return run_dir


SOURCES = (
    "gate_escalation", "repair_budget_exhausted", "review_unavailable", "review_blocked",
    "escalation_decision", "arbitration",
)  # fmt: skip


@pytest.mark.parametrize("source", SOURCES)
def test_choose_is_refused_on_any_item_but_an_arbitration(tmp_path: Path, source: str) -> None:
    run_dir = _hand_queue(tmp_path, source)
    view = read_queue(run_dir)
    shown = ShownItem(
        item_sha256=view.digests["run-1-s1"], trajectories=statuses_now(run_dir, "run-1-s1")
    )

    def choose() -> object:
        return record_decision(
            run_dir, "run-1-s1", person=person("sizing"), resolved_by="yasin", shown=shown
        )

    if source != "arbitration":
        said = refused(choose)
        assert "a choice is made only on an item whose kind offers positions" in said
        assert (run_dir / DECISIONS_NAME).read_bytes() == b""
        return
    try:
        record = choose()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"a choice on an arbitration item was refused: {exc!r}") from None
    assert isinstance(record, QueueResolution)
    assert json.loads((run_dir / DECISIONS_NAME).read_bytes())["position"] == "sizing"


@pytest.mark.parametrize("source", SOURCES)
def test_a_choice_line_on_any_item_but_an_arbitration_does_not_read(
    tmp_path: Path, source: str
) -> None:
    run_dir = _hand_queue(tmp_path, source)
    line = {
        "item_id": "run-1-s1", "ts": TS, "kind": "resolution", "decision": "choose domain",
        "resolved_by": "yasin", "verb": "choose", "position": "domain", "shown_sha256": SHA,
    }  # fmt: skip
    (run_dir / DECISIONS_NAME).write_bytes(json.dumps(line, separators=(",", ":")).encode() + b"\n")
    if source != "arbitration":
        said = refused(lambda: read_queue(run_dir))
        assert "a choice is made only on an item whose kind offers positions" in said
        return
    try:
        view = read_queue(run_dir)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"a choice on an arbitration item does not read: {exc!r}") from None
    assert [d.item_id for _, d in view.decisions] == ["run-1-s1"]


def test_choosing_the_domain_binds_only_to_a_view_whose_transcripts_all_held_their_seal(
    tmp_path: Path,
) -> None:
    rig = arbitrated(tmp_path)
    item = one(read_queue(rig.run_dir).open_items())
    stream = rig.run_dir / item.trajectories[0]
    stream.write_bytes(stream.read_bytes() + b"{}\n")
    statuses = statuses_now(rig.run_dir, item.item_id)
    assert "holds" in statuses or "tampered" in statuses
    assert any(status != "holds" for status in statuses)
    shown = ShownItem(
        item_sha256=read_queue(rig.run_dir).digests[item.item_id], trajectories=statuses
    )
    before = (rig.run_dir / DECISIONS_NAME).read_bytes()
    said = refused(
        lambda: record_decision(
            rig.run_dir, item.item_id, person=person("domain"), resolved_by="yasin", shown=shown
        )
    )
    assert "held its seal" in said
    assert (rig.run_dir / DECISIONS_NAME).read_bytes() == before


def test_choosing_sizing_binds_to_a_view_whatever_its_seals_showed(tmp_path: Path) -> None:
    rig = arbitrated(tmp_path)
    item = one(read_queue(rig.run_dir).open_items())
    stream = rig.run_dir / item.trajectories[0]
    stream.write_bytes(stream.read_bytes() + b"{}\n")
    assert any(s != "holds" for s in statuses_now(rig.run_dir, item.item_id))
    record = chose(rig.run_dir, "sizing")
    assert (record.verb, record.decision) == ("choose", "choose sizing")


#: The line a choice with a note is written as, which the operator UI's confirmation also shows:
#: one file both languages are held to.
CHOICE_LINE = Path(__file__).resolve().parents[3] / "ui/src/screens/queue/choice-with-note.line"


def test_a_choice_with_a_note_is_written_as_the_line_the_ui_shows(tmp_path: Path) -> None:
    rig = arbitrated(tmp_path)
    chose(rig.run_dir, "sizing", "keep 24 V")
    written = json.loads((rig.run_dir / DECISIONS_NAME).read_bytes().splitlines()[-1])
    # The item, its digest and the time are this run's; the UI's fixture names its own.
    shown = written | {
        "item_id": "run-1-s1", "ts": "\u2039the time you confirm\u203a", "shown_sha256": "a" * 64,
    }  # fmt: skip
    line = json.dumps(shown, separators=(",", ":"), ensure_ascii=False)
    assert line == CHOICE_LINE.read_text(encoding="utf-8").rstrip("\n")


# --- the item ----------------------------------------------------------------------------------


def test_an_arbitration_item_carries_the_five_fields_and_both_positions(tmp_path: Path) -> None:
    rig = arbitrated(tmp_path)
    view = read_queue(rig.run_dir)
    item = one(view.open_items())
    # ARCH-130's five: the decision required, the diff, the finding, the quantities, the links.
    assert item.decision_required.strip() and item.triggering_finding.strip()
    assert isinstance(item.artefact_diff, str)
    assert 1 <= len(item.quantities) <= 3
    assert len(item.trajectories) >= 1
    # Both positions, each with what choosing it does, in the order the kind's set lists them.
    consequence = item.consequence
    assert consequence is not None
    on_choose = getattr(consequence, "on_choose", None)
    assert on_choose == {"sizing": "record_only", "domain": "record_only"}
    assert list(on_choose) == ["sizing", "domain"]
    raw = (rig.run_dir / QUEUE_NAME).read_bytes()
    assert b'"on_choose":{"sizing":"record_only","domain":"record_only"}' in raw


def test_an_item_whose_positions_are_not_its_kind_s_set_does_not_read(tmp_path: Path) -> None:
    rig = arbitrated(tmp_path)
    items = rig.run_dir / QUEUE_NAME
    data = items.read_bytes()
    stated = b',"on_choose":{"sizing":"record_only","domain":"record_only"}'
    assert stated in data
    order = "an item states the positions its kind offers, in their order, and no others"
    for forged, says in (
        (b',"on_choose":{"domain":"record_only","sizing":"record_only"}', order),
        (b',"on_choose":{"sizing":"record_only"}', order),
        # Left out whole, as a line of another kind leaves it out: the form is the writer's.
        (b"", "an item whose kind offers positions states what choosing each does"),
    ):
        items.write_bytes(data.replace(stated, forged))
        said = refused(lambda: read_queue(rig.run_dir))
        assert says in said, (forged, said)


# --- taking it ---------------------------------------------------------------------------------


@pytest.mark.parametrize("position", ["sizing", "domain"])
def test_a_choice_is_taken_with_its_position_and_records_only(
    tmp_path: Path, position: str
) -> None:
    rig = arbitrated(tmp_path)
    item = one(read_queue(rig.run_dir).open_items())
    chose(rig.run_dir, position, "the reason a person gives")
    driven(rig, resume)
    events = events_of(rig)
    line = one(taken(events))
    assert (line.item_id, line.verb, getattr(line, "position", None)) == (
        item.item_id, "choose", position,
    )  # fmt: skip
    assert (line.effect, line.acts, line.why_not) == ("none", False, "record_only_source")
    assert line.note == "the reason a person gives"
    assert not [e for e in events if isinstance(e, Incident)]
    assert refusal(events) is None
    assert json.loads(line.model_dump_json())["position"] == position


@pytest.mark.parametrize("verb", ["approve", "reject"])
def test_approve_and_reject_on_an_arbitration_item_still_record_only(
    tmp_path: Path, verb: str
) -> None:
    rig = arbitrated(tmp_path)
    item = one(read_queue(rig.run_dir).open_items())
    assert item.consequence is not None
    assert (item.consequence.on_approve, item.consequence.on_reject) == (
        "record_only", "record_only",
    )  # fmt: skip
    decide(rig.run_dir, verb, None if verb == "approve" else "keep the graph's value")
    driven(rig, resume)
    events = events_of(rig)
    line = one(taken(events))
    assert (line.verb, line.effect, line.acts, line.why_not) == (
        verb, "none", False, "record_only_source",
    )  # fmt: skip
    assert "position" not in json.loads(line.model_dump_json())
    assert refusal(events) is None


def test_arbitration_stays_out_of_the_scanned_sources() -> None:
    assert (
        frozenset(
            {
                "review_unavailable",
                "review_blocked",
                "repair_budget_exhausted",
                "escalation_decision",
            }
        )
        == SCANNED_SOURCES
    )
    assert "arbitration" not in SCANNED_SOURCES


@pytest.mark.parametrize(
    "forge",
    ["finding", "consequence"],
)
def test_an_arbitration_item_rebuilt_at_take_must_equal_its_line(
    tmp_path: Path, forge: str
) -> None:
    rig = arbitrated(tmp_path)
    items = rig.run_dir / QUEUE_NAME
    item = QueueItem.model_validate_json(items.read_bytes())
    assert item.consequence is not None
    if forge == "finding":
        # Caught by the whole-item comparison: the consequence is still the record's.
        forged = item.model_copy(update={"triggering_finding": "Sizing agreed to 5 A."})
    else:
        # Caught by the consequence comparison, before the whole item is built.
        forged = item.model_copy(
            update={"consequence": item.consequence.model_copy(update={"on_reject": "end_subtask"})}
        )
    items.write_bytes(forged.model_dump_json().encode() + b"\n")
    chose(rig.run_dir, "domain")
    driven(rig, resume)
    events = events_of(rig)
    assert [e.cause for e in events if isinstance(e, Incident)] == ["queue_item_mismatch"]
    assert taken(events) == []


# --- replay ------------------------------------------------------------------------------------


def _lines(events: list[Event]) -> list[dict[str, Any]]:
    return [json.loads(e.model_dump_json()) for e in events]


def _refusal_of(lines: list[dict[str, Any]]) -> str | None:
    data = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    try:
        replay(parse_events(data, log="events.jsonl"))
    except CorruptEventLogError as exc:
        return str(exc.context.get("reason", exc))
    except Exception as exc:  # noqa: BLE001 - any other escape is a refusal no rule gave
        return f"raised {type(exc).__name__}: {exc}"
    return None


def _as_choice(line: dict[str, Any], **change: Any) -> dict[str, Any]:  # noqa: ANN401
    return line | {
        "verb": "choose", "position": "sizing", "effect": "none", "acts": False,
        "why_not": "record_only_source",
    } | change  # fmt: skip


def _approved_on_arbitration(tmp_path: Path) -> list[dict[str, Any]]:
    rig = arbitrated(tmp_path)
    decide(rig.run_dir, "approve")
    driven(rig, resume)
    lines = _lines(events_of(rig))
    assert one(line for line in lines if line["kind"] == "decision_taken")["verb"] == "approve"
    return lines


def _with(lines: list[dict[str, Any]], **change: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    return [_as_choice(ln, **change) if ln["kind"] == "decision_taken" else ln for ln in lines]


def test_replay_reads_a_choice_on_an_arbitration_item(tmp_path: Path) -> None:
    lines = _approved_on_arbitration(tmp_path)
    assert _refusal_of(_with(lines)) is None
    assert _refusal_of(_with(lines, position="domain")) is None


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"position": None}, "a position is chosen with choose, and only with it"),
        ({"verb": "approve"}, "a position is chosen with choose, and only with it"),
        ({"position": "producer"}, "domain"),
        ({"effect": "retry", "acts": True, "why_not": None, "note": "go"},
         "a decision that does other than the record allows"),
        ({"why_not": "scan_hit"}, "a decision that does other than the record allows"),
    ],
    ids=["no position", "a position on approve", "outside the set", "acting", "another reason"],
)  # fmt: skip
def test_replay_refuses_a_choice_the_record_does_not_allow(
    tmp_path: Path, change: dict[str, Any], says: str
) -> None:
    lines = _approved_on_arbitration(tmp_path)
    assert _refusal_of(_with(lines)) is None
    said = _refusal_of(_with(lines, **change))
    assert said is not None and says in said, said


def test_replay_refuses_a_choice_on_an_item_of_another_kind(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    _resume(rig)[0].close()
    lines = _lines(events_of(rig))
    said = _refusal_of(_with(lines))
    assert said is not None and "a choice is taken only on an arbitration item" in said, said


def test_replay_refuses_a_choice_on_the_integration_item(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    assert rig.gate is not None
    rig.gate.integration_verdict = "fail"
    _resume(rig)[0].close()
    integration = one(read_queue(rig.run_dir).open_items())
    decide(rig.run_dir, "reject", "the bus", item_id=integration.item_id)
    _resume(rig)[0].close()
    lines = _lines(events_of(rig))
    last = [i for i, ln in enumerate(lines) if ln["kind"] == "decision_taken"][-1]
    assert lines[last]["subtask_id"] is None
    lines[last] = _as_choice(lines[last], note=None)
    said = _refusal_of(lines[: last + 1])
    assert said is not None and "records only, and no position is chosen on it" in said, said


# --- killed and resumed ------------------------------------------------------------------------


def _resume_killed(rig: Rig, kill: Callable[[Event], bool]) -> None:
    loop = rig.open()
    _layer(loop)
    emit = loop._emit

    def dies(line: Event) -> None:
        if kill(line):
            raise KilledByRowError
        emit(line)

    setattr(loop, "_emit", dies)  # noqa: B010 - a process that dies at a line
    try:
        loop.resume()
    except KilledByRowError:
        pass
    finally:
        loop.close()


@pytest.mark.parametrize("position", ["sizing", "domain"])
def test_a_choice_killed_before_it_is_taken_is_taken_once_on_resume(
    tmp_path: Path, position: str
) -> None:
    rig = arbitrated(tmp_path)
    chose(rig.run_dir, position)
    _resume_killed(rig, lambda line: isinstance(line, DecisionTaken))
    assert taken(events_of(rig)) == []
    driven(rig, resume)
    events = events_of(rig)
    assert [(t.verb, getattr(t, "position", None)) for t in taken(events)] == [("choose", position)]
    assert refusal(events) is None


@pytest.mark.parametrize("position", ["sizing", "domain"])
def test_a_choice_taken_is_not_taken_again_on_resume(tmp_path: Path, position: str) -> None:
    rig = arbitrated(tmp_path)
    chose(rig.run_dir, position)
    driven(rig, resume)
    driven(rig, resume)
    events = events_of(rig)
    assert [(t.verb, getattr(t, "position", None)) for t in taken(events)] == [("choose", position)]
    assert refusal(events) is None


# --- the command -------------------------------------------------------------------------------


def _command(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    try:
        code = main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.mark.parametrize(
    ("args", "decision"),
    [(["--choose", "domain"], "choose domain"),
     (["--choose", "sizing", "--note", "keep 24 V"], "choose sizing: keep 24 V")],
)  # fmt: skip
def test_the_command_chooses_a_position_by_the_digest_the_listing_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], decision: str
) -> None:
    rig = arbitrated(tmp_path)
    view = read_queue(rig.run_dir)
    item = one(view.open_items())
    code, out = _command(
        ["queue", "resolve", item.item_id, "--run-dir", str(rig.run_dir), *args,
         "--sha256", view.digests[item.item_id], "--by", "yasin"],
        capsys,
    )  # fmt: skip
    assert code == 0, out
    line = json.loads((rig.run_dir / DECISIONS_NAME).read_bytes())
    assert (line["verb"], line["position"], line["decision"]) == (
        "choose", args[1], decision,
    )  # fmt: skip


def test_the_command_refuses_a_choice_on_an_item_of_another_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _hand_queue(tmp_path, "review_unavailable")
    digest = read_queue(run_dir).digests["run-1-s1"]
    code, out = _command(
        ["queue", "resolve", "run-1-s1", "--run-dir", str(run_dir), "--choose", "sizing",
         "--sha256", digest, "--by", "yasin"],
        capsys,
    )  # fmt: skip
    assert code != 0, out
    assert "a choice is made only on an item whose kind offers positions" in out
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


@pytest.mark.parametrize(
    "args",
    [["--choose", "domain", "--approve"], ["--choose", "producer"], ["--choose"]],
)
def test_the_command_takes_one_verb_and_a_position_of_the_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    run_dir = _hand_queue(tmp_path, "arbitration")
    digest = read_queue(run_dir).digests["run-1-s1"]
    code, _ = _command(
        ["queue", "resolve", "run-1-s1", "--run-dir", str(run_dir), *args,
         "--sha256", digest, "--by", "yasin"],
        capsys,
    )  # fmt: skip
    assert code == 2
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


# --- every other item keeps its bytes ----------------------------------------------------------

#: Lines written before a choice existed, by the builders and models that write them: an item
#: with a consequence and one without, a decision with a verb, and the line taking it.
O3_LINES = (
    b'{"item_id":"run-1-s1","ts":"2026-10-30T09:00:00.000000Z","kind":"item","run_id":"run-1",'
    b'"subtask_id":"s1","source":"repair_budget_exhausted","decision_required":"Subtask s1 was '
    b"rejected on all 3 attempts. Decide whether to accept the last attempt as it stands, "
    b'rewrite the subtask\'s specification, or split the subtask.","artefact_diff":"diff '
    b'--git a/x b/x\\n","triggering_finding":"the bus is over its bound","quantities":[{"node_id"'
    b':"power.bus","name":"peak_current","value":5,"unit":"A"}],"trajectories":["sessions/a/'
    b'stdout.jsonl","sessions/b/stdout.jsonl","sessions/c/stdout.jsonl"],"consequence":{"attempt"'
    b':3,"attempt_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","on_approve":"merge_attempt",'
    b'"on_reject":"end_subtask","why_record_only":null,"confirmed_indicators":[{"attempt":2,'
    b'"kind":"hard_coded_values"}],"scan_hits":[]}}',
    b'{"item_id":"run-1-s1","ts":"2026-10-30T09:00:00.000000Z","kind":"item","run_id":"run-1",'
    b'"subtask_id":"s1","source":"repair_budget_exhausted","decision_required":"Subtask s1 was '
    b"rejected on all 3 attempts. Decide whether to accept the last attempt as it stands, "
    b'rewrite the subtask\'s specification, or split the subtask.","artefact_diff":"diff '
    b'--git a/x b/x\\n","triggering_finding":"the bus is over its bound","quantities":[{"node_id"'
    b':"power.bus","name":"peak_current","value":5,"unit":"A"}],"trajectories":["sessions/a/'
    b'stdout.jsonl","sessions/b/stdout.jsonl","sessions/c/stdout.jsonl"]}',
    b'{"item_id":"run-1-s1","ts":"2026-10-30T09:01:00.000000Z","kind":"resolution","decision":'
    b'"reject: split it","resolved_by":"yasin","verb":"reject","note":"split it","shown_sha256":'
    b'"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}',
    b'{"seq":40,"ts":"2026-10-30T09:02:00.000000Z","run_id":"run-1","gate_mode":"on","kind":'
    b'"decision_taken","subtask_id":"s1","item_id":"run-1-s1","verb":"reject","note":"split it",'
    b'"resolved_by":"yasin","decided_ts":"2026-10-30T09:01:00.000000Z","decision_offset":0,'
    b'"shown_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","attempt":3,'
    b'"attempt_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","effect":"end_subtask","acts":'
    b'true,"why_not":null,"confirmed_by":null,"order_too_long":false}',
)


def test_an_o3_item_keeps_its_bytes_with_no_on_choose() -> None:
    from physgate.orchestrator.events import _EVENT
    from physgate.orchestrator.protocols import QuantityRef
    from physgate.orchestrator.queue import (
        ConfirmedIndicator,
        ItemConsequence,
        escalation_item,
    )
    from physgate.orchestrator.repair import Finding

    finding = Finding(
        source="gate", text="the bus is over its bound",
        quantities=(QuantityRef(node_id="power.bus", name="peak_current", value=5, unit="A"),),
    )  # fmt: skip
    consequence = ItemConsequence(
        attempt=3, attempt_commit="a" * 40, on_approve="merge_attempt", on_reject="end_subtask",
        why_record_only=None,
        confirmed_indicators=(ConfirmedIndicator(attempt=2, kind="hard_coded_values"),),
        scan_hits=(),
    )  # fmt: skip
    built = [
        escalation_item(
            item_id="run-1-s1", run_id="run-1", subtask_id="s1", findings=(finding,) * 3,
            artefact_diff="diff --git a/x b/x\n",
            trajectories=tuple(f"sessions/{s}/stdout.jsonl" for s in "abc"),
            ts=TS, consequence=given,
        ).model_dump_json().encode()
        for given in (consequence, None)
    ]  # fmt: skip
    assert built == list(O3_LINES[:2])
    assert getattr(consequence, "on_choose", "absent") in (None, "absent")
    assert QueueItem.model_validate_json(O3_LINES[1]).model_dump_json().encode() == O3_LINES[1]
    resolution = QueueResolution.model_validate_json(O3_LINES[2])
    assert resolution.model_dump_json().encode() == O3_LINES[2]
    decision = _EVENT.validate_json(O3_LINES[3])
    assert decision.model_dump_json().encode() == O3_LINES[3]
    assert b"on_choose" not in b"".join(O3_LINES) and b"position" not in b"".join(O3_LINES)
    assert QueueItem.model_validate_json(O3_LINES[0]).model_dump_json().encode() == O3_LINES[0]
