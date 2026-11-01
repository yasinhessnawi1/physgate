"""A session end with several findings records them all in one line first; a kill writes the rest.

A session's end can show more than one thing a person must look at: held-out material in its
stream, a stream something else wrote, a possible abort, commands whose reaper was not heard from.
Each is an incident, and the run halts once after them, under the cause the site's own rule picks.
Where there are two or more, one line listing each finding (its cause and its detail, in the order
the incidents are written) and the halt's cause comes first. A process killed after it, between
two of the incidents or before the halt, leaves the rest owed: the process that takes over writes
the missing incidents and then that halt, so the run reads as it would have uninterrupted. Replay
holds the incidents and the halt to the line. A session end with one incident writes no such line,
so its log keeps its bytes. The leftovers a resume finds are recorded the same way: every
leftover's own lines, then the findings line, then every incident, then one halt. A log written
before the line existed replays as it did.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, KilledError, Rig, plan, usage

from physgate.orchestrator.events import Event, parse_events, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import Leftover
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.replay import replay

CANARY = "held-out canary"


def lines(rig: Rig) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in (rig.run_dir / "events.jsonl").read_bytes().splitlines()]


def kinds(rows: list[dict[str, Any]]) -> list[str]:
    return [r["kind"] for r in rows]


def comparable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every line but its place and its time."""
    return [{k: v for k, v in r.items() if k not in ("seq", "ts")} for r in rows]


def outcome(how: Callable[[], Any]) -> str:
    """The step a drive ended on, or what escaped it, as text for the assertion."""
    try:
        return str(how().kind)
    except KilledError:
        return "killed"
    except Exception as exc:  # noqa: BLE001 - any escape is the finding
        return f"raised {exc!r}"


def dies_at(loop: Loop, n: int, kind: str) -> None:
    """The process dies as it is about to write its ``n``-th line of ``kind`` (from 1)."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    seen = [0]

    def emitting(event: Event) -> None:
        if event.kind == kind:
            seen[0] += 1
            if seen[0] == n:
                raise KilledError
        emit(event)

    loop._emit = emitting  # type: ignore[method-assign]  # noqa: SLF001


@dataclass
class LeftBehind(FakeDispatcher):
    """A dispatcher whose first stop finds the given leftovers; it ended them, so none after."""

    left: list[Leftover] = field(default_factory=list)

    def stop_leftovers(self) -> list[Leftover]:
        found, self.left = self.left, []
        return found


def leftover(sid: str, **seen: Any) -> Leftover:  # noqa: ANN401 - the model's own fields
    spent = (MessageUsage(message_id=f"m-{sid}", usage=usage(5)),)
    return Leftover(session_id=sid, pid=4242, killed=0, stopped=False, usage=spent, **seen)


#: Each session end with two or more incidents: what the session showed, the incidents in their
#: order, and the halt's cause by the site's own rule.
ENDS: dict[str, tuple[dict[str, Any], list[str], str]] = {
    "exposure and abort": (
        {"held_out": {1: CANARY}, "aborted": {1: ("toolu_a",)}},
        ["held_out_read", "os_layer_aborted"],
        "held_out_read",
    ),
    "exposure, tampering and abort": (
        {"held_out": {1: CANARY}, "tampered": {1: "a tail"}, "aborted": {1: ("toolu_a",)}},
        ["held_out_read", "trajectory_tampered", "os_layer_aborted"],
        "trajectory_tampered",
    ),
    "abort and unverified reaping": (
        {"aborted": {1: ("toolu_a",)}, "unverified": {1: ("toolu_b",)}},
        ["os_layer_aborted", "reaper_unverified"],
        "reaper_unverified",
    ),
}

#: Each leftover shape: the leftovers a resume finds, the incidents and the halt's cause.
LEFT: dict[str, tuple[list[Leftover], list[str], str]] = {
    "exposure and reviewer material": (
        [leftover("left-1", held_out_seen=CANARY, review_material_seen="rubric canary")],
        ["held_out_read", "review_material_read"],
        "held_out_read",
    ),
    "exposure and tampering": (
        [leftover("left-1", held_out_seen=CANARY, tampered="a tail")],
        ["held_out_read", "trajectory_tampered"],
        "trajectory_tampered",
    ),
    "two tampered": (
        [leftover("left-1", tampered="a tail"), leftover("left-2", tampered="another tail")],
        ["trajectory_tampered", "trajectory_tampered"],
        "trajectory_tampered",
    ),
}


def ended_session(path: Path, shown: dict[str, Any], *, kill: tuple[int, str] | None) -> Rig:
    """A run whose first session's end shows ``shown``; its process killed where ``kill`` says."""
    rig = Rig(path, dispatcher=FakeDispatcher(**shown))
    loop = rig.open()
    loop.start(plan("s1"))
    if kill is not None:
        dies_at(loop, *kill)
    said = outcome(loop.run)
    loop.close()
    assert said == ("killed" if kill is not None else "halted"), said
    return rig


def left_behind(path: Path, found: list[Leftover], *, kill: tuple[int, str] | None) -> Rig:
    """A run that a process takes over with ``found`` left running; killed where ``kill`` says."""
    rig = Rig(path, dispatcher=LeftBehind(left=list(found)))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    loop = rig.open()
    if kill is not None:
        dies_at(loop, *kill)
    said = outcome(loop.run)
    loop.close()
    assert said == ("killed" if kill is not None else "halted"), said
    return rig


def taken_over(rig: Rig) -> str:
    """A fresh process takes the run over, as an operator would; how its drive ended."""
    fresh = rig.open()
    try:
        interrupted = replay(read_events(rig.run_dir / "events.jsonl")).interrupted() is not None
        return outcome(fresh.resume if interrupted else fresh.run)
    finally:
        fresh.close()


def kill_points(incidents: list[str]) -> list[tuple[int, str]]:
    """Between each pair of incidents, and before the halt."""
    return [*((n, "incident") for n in range(2, len(incidents) + 1)), (1, "halted")]


def named(points: dict[str, tuple[Any, list[str], str]]) -> list[tuple[str, tuple[int, str]]]:
    return [(shape, point) for shape, (_, i, _) in points.items() for point in kill_points(i)]


def ids(cases: list[tuple[str, tuple[int, str]]]) -> list[str]:
    return [f"{shape}, before {kind} {n}" for shape, (n, kind) in cases]


def _findings_then_incidents(rows: list[dict[str, Any]], incidents: list[str], halt: str) -> None:
    """The line, every incident it names in its order, then one halt under its cause."""
    assert "findings_recorded" in kinds(rows), "no line records the findings first"
    at = kinds(rows).index("findings_recorded")
    (record,) = [r for r in rows if r["kind"] == "findings_recorded"]
    assert [f["cause"] for f in record["findings"]] == incidents
    assert record["halt"] == halt
    after = rows[at + 1 :]
    assert kinds(after)[: len(incidents) + 1] == ["incident"] * len(incidents) + ["halted"]
    written = after[: len(incidents)]
    assert [(r["cause"], r["detail"]) for r in written] == [
        (f["cause"], f["detail"]) for f in record["findings"]
    ]
    assert after[len(incidents)]["detail"].startswith(halt)


# --- what the uninterrupted run writes ---------------------------------------------------------


@pytest.mark.parametrize("shape", ENDS)
def test_a_session_end_with_several_findings_records_them_before_its_incidents(
    tmp_path: Path, shape: str
) -> None:
    shown, incidents, halt = ENDS[shape]
    rows = lines(ended_session(tmp_path, shown, kill=None))
    assert "findings_recorded" in kinds(rows), "no line records the findings first"
    assert kinds(rows).index("session_ended") < kinds(rows).index("findings_recorded")
    _findings_then_incidents(rows, incidents, halt)


@pytest.mark.parametrize("shape", LEFT)
def test_the_leftovers_lines_come_first_then_their_findings_every_incident_and_one_halt(
    tmp_path: Path, shape: str
) -> None:
    found, incidents, halt = LEFT[shape]
    rows = lines(left_behind(tmp_path, found, kill=None))
    last_leftover = max(
        i for i, r in enumerate(rows) if r["kind"] in ("leftover_read", "tokens_used")
    )
    assert "findings_recorded" in kinds(rows), "no line records the findings first"
    assert last_leftover < kinds(rows).index("findings_recorded")
    assert kinds(rows).count("halted") == 1
    _findings_then_incidents(rows, incidents, halt)


def test_a_session_end_with_one_finding_writes_no_findings_line(tmp_path: Path) -> None:
    rows = lines(ended_session(tmp_path, {"held_out": {1: CANARY}}, kill=None))
    at = kinds(rows).index("session_ended")
    assert kinds(rows)[at + 1 :] == ["incident", "halted"]
    assert rows[at + 1]["cause"] == "held_out_read"
    assert rows[at + 2]["detail"] == "held_out_read in s1"


# --- a kill between them -----------------------------------------------------------------------


@pytest.mark.parametrize(("shape", "point"), named(ENDS), ids=ids(named(ENDS)))
def test_a_kill_between_a_session_end_s_incidents_resumes_to_the_uninterrupted_log(
    tmp_path: Path, shape: str, point: tuple[int, str]
) -> None:
    shown, incidents, halt = ENDS[shape]
    reference = lines(ended_session(tmp_path / "reference", shown, kill=None))
    rig = ended_session(tmp_path / "cut", shown, kill=point)
    assert replay(read_events(rig.run_dir / "events.jsonl")).next_step().kind == "halt"
    said = taken_over(rig)
    assert said == "halted", said
    rows = lines(rig)
    assert comparable(rows) == comparable(reference)
    _findings_then_incidents(rows, incidents, halt)
    assert replay(read_events(rig.run_dir / "events.jsonl")).next_step().kind == "halted"


@pytest.mark.parametrize(("shape", "point"), named(LEFT), ids=ids(named(LEFT)))
def test_a_kill_between_the_leftovers_incidents_resumes_to_the_uninterrupted_log(
    tmp_path: Path, shape: str, point: tuple[int, str]
) -> None:
    found, incidents, halt = LEFT[shape]
    reference = lines(left_behind(tmp_path / "reference", found, kill=None))
    rig = left_behind(tmp_path / "cut", found, kill=point)
    said = taken_over(rig)
    assert said == "halted", said
    rows = lines(rig)
    assert comparable(rows) == comparable(reference)
    _findings_then_incidents(rows, incidents, halt)


# --- replay holds the incidents and the halt to the line ---------------------------------------


def refusal(rows: list[dict[str, Any]]) -> str | None:
    """Why replay refuses ``rows``, or None."""
    try:
        replay(parse_events(_bytes(rows), log="events.jsonl"))
    except CorruptEventLogError as exc:
        return f"{exc}: {exc.context}"
    return None


def _uninterrupted(tmp_path: Path) -> list[dict[str, Any]]:
    shown, _, _ = ENDS["exposure, tampering and abort"]
    rows = lines(ended_session(tmp_path, shown, kill=None))
    assert "findings_recorded" in kinds(rows), "no line records the findings first"
    assert refusal(rows) is None
    return rows


def test_an_incident_the_findings_line_does_not_name_next_is_refused(tmp_path: Path) -> None:
    rows = _uninterrupted(tmp_path)
    at = kinds(rows).index("findings_recorded")
    rows[at + 2] = rows[at + 2] | {"cause": "reaper_unverified"}
    assert refusal(rows) is not None


def test_an_incident_with_another_detail_than_the_line_names_is_refused(tmp_path: Path) -> None:
    rows = _uninterrupted(tmp_path)
    at = kinds(rows).index("findings_recorded")
    rows[at + 1] = rows[at + 1] | {"detail": "something else was found"}
    assert refusal(rows) is not None


def test_a_halt_under_another_cause_than_the_line_names_is_refused(tmp_path: Path) -> None:
    rows = _uninterrupted(tmp_path)
    halt = kinds(rows).index("halted")
    rows[halt] = rows[halt] | {"detail": "os_layer_aborted in s1"}
    assert refusal(rows) is not None


def test_a_halt_before_every_finding_was_written_is_refused(tmp_path: Path) -> None:
    rows = _uninterrupted(tmp_path)
    halt = kinds(rows).index("halted")
    del rows[halt - 1]
    for seq, row in enumerate(rows):
        row["seq"] = seq
    assert refusal(rows) is not None


# --- logs written before the line existed --------------------------------------------------------


def _renumbered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for seq, row in enumerate(rows):
        row["seq"] = seq
    return rows


def test_a_log_with_several_incidents_and_no_findings_line_replays_as_before(
    tmp_path: Path,
) -> None:
    # As a session end was written before the line: each incident, then the halt.
    shown, _, _ = ENDS["exposure and abort"]
    rig = ended_session(tmp_path, shown, kill=None)
    old = _renumbered([r for r in lines(rig) if r["kind"] != "findings_recorded"])
    assert refusal(old) is None
    state = replay(parse_events(_bytes(old), log="events.jsonl"))
    assert state.next_step().kind == "halted"


def test_a_log_with_the_old_incident_and_halt_pairs_of_leftovers_replays_as_before(
    tmp_path: Path,
) -> None:
    # Two tampered leftovers, as written before the line: an incident and its halt, twice.
    found, _, _ = LEFT["two tampered"]
    rig = left_behind(tmp_path, found, kill=None)
    rows = [r for r in lines(rig) if r["kind"] != "findings_recorded"]
    first = kinds(rows).index("incident")
    halt = next(r for r in rows if r["kind"] == "halted")
    old = _renumbered([*rows[: first + 1], dict(halt), *rows[first + 1 :]])
    assert kinds(old)[first:] == ["incident", "halted", "incident", "halted"]
    assert refusal(old) is None
    (rig.run_dir / "events.jsonl").write_bytes(_bytes(old))
    said = taken_over(rig)
    assert said == "halted", said
    assert lines(rig) == old, "a process taking over the old log wrote to it"


def _bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in rows)
