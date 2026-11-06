"""The simulation listing: what each attempt's sessions sealed, read from the run's event log alone.

The route lists, per attempt, the records its sessions sealed, the ones a later session sealed
again, the files the collector set aside, and every graph quantity the change check held to a
record. It opens no record: a file in the run's series directory that no session's end seals is
never named, and the listing never even looks there.

Beside each checked quantity it shows only what a gate record of the same attempt says about
that quantity, joined by the quantity's name. A gate record that names other quantities on the
same node says nothing about this one, and a pass names none, so neither is ever shown as a
verdict on it. A failing record is matched to the quantity it names by node, value and unit,
and a quantity that matches no failing record, or more than one, is never given one.

The runs are made by the real loop with the real gate (see ``ui_series_rig``).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from ui_rig import RECORDER, context_over, fake_ui, serving, snapshot
from ui_series_rig import PEAK_OUT_OF_RANGE, cut_after_first_check, rejected, series_runs

import physgate.ui
from physgate.orchestrator.events import (
    GateRan,
    GateSkipped,
    Merged,
    ProposalsChecked,
    SessionEnded,
    read_events,
)
from physgate.series.reader import attempt_records
from physgate.ui.table import ROUTES, RUN

#: The module the simulation routes live in.
SIMULATION = Path(physgate.ui.__file__).parent / "simulation.py"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The series runs, built once for the module, and a stamped build to serve beside them."""
    base = tmp_path_factory.mktemp("series")
    runs = base / "runs"
    made = series_runs(base, runs)
    cut_after_first_check(made["run-series"], runs / "run-series-unjudged")
    return {"base": base, "runs": runs, "ui": fake_ui(base / "checkout")}


def _get(root: Path, ui: Path, name: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    with serving(context_over(root, ui_root=ui)) as live:
        return live.request(method, f"/api/runs/0/{name}/series")


def _listing(world: dict[str, Path], name: str, root: Path | None = None) -> dict[str, Any]:
    status, _, body = _get(root or world["runs"], world["ui"], name)
    assert status == 200, body
    answer: dict[str, Any] = json.loads(body)
    return answer


def _attempts(answer: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    return {(a["subtask_id"], a["attempt"]): a for a in answer["attempts"]}


def _events(run: Path) -> list[Any]:
    return read_events(run / "events.jsonl")


def _check(attempt: dict[str, Any], quantity: str) -> dict[str, Any]:
    (found,) = [c for c in attempt["checks"] if c["quantity"] == quantity]
    return found  # type: ignore[no-any-return]


def _copy(world: dict[str, Path], name: str, tmp_path: Path) -> tuple[Path, Path]:
    """A copy of one run under a root of its own: (the root, the run)."""
    root = tmp_path / "runs"
    target = root / name
    shutil.copytree(
        world["runs"] / name, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    return root, target


def _forge(run: Path, kind: str, change: Any, which: int = 0) -> None:  # noqa: ANN401
    """Rewrite the ``which``-th log line of ``kind`` through ``change``, in place."""
    log = run / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    at = [i for i, raw in enumerate(lines) if json.loads(raw)["kind"] == kind][which]
    record = json.loads(lines[at])
    change(record)
    lines[at] = (json.dumps(record) + "\n").encode()
    log.write_bytes(b"".join(lines))


def _gate_line(run: Path, subtask: str, attempt: int) -> GateRan:
    (line,) = [
        e
        for e in _events(run)
        if isinstance(e, GateRan) and (e.subtask_id, e.attempt) == (subtask, attempt)
    ]
    return line


def _first_subtask(run: Path) -> str:
    return str(next(e.subtask_id for e in _events(run) if isinstance(e, SessionEnded)))


def test_the_listing_is_one_read_route_placed_after_the_queue_items() -> None:
    patterns = [route.pattern for route in ROUTES]
    listing = [route for route in ROUTES if route.pattern == f"{RUN}/series"]
    assert len(listing) == 1, "the run's simulation listing is one route"
    assert (listing[0].kind, listing[0].method) == ("read", "GET")
    assert (
        patterns.index(f"{RUN}/series")
        == patterns.index(f"{RUN}/queue/items/{{position:index}}") + 1
    )
    assert [route.kind for route in ROUTES].count("act") == 1


def test_the_listing_opens_the_event_log_and_nothing_beneath_the_records(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series-retried", tmp_path)
    ended = next(
        e for e in _events(run) if isinstance(e, SessionEnded) and e.outcome == "completed"
    )
    sealed_dir = run / "series" / ended.subtask_id / str(ended.attempt) / ended.session_id
    (sealed_dir / "unsealed_extra.json").write_text('{"format": "series.v1"}')
    outside = tmp_path / "elsewhere.json"
    outside.write_text("outside every root")
    os.symlink(outside, sealed_dir / "linked_out.json")
    os.mkfifo(run / "series" / ended.subtask_id / str(ended.attempt) / "piped.json")
    assert (run / "series" / "_refused").is_dir(), "the collector's refused tree is there to ignore"
    assert (run / "series" / "_discarded").is_dir()
    with serving(context_over(root, ui_root=world["ui"])) as live, RECORDER.recording() as writes:
        status, _, body = live.request("GET", "/api/runs/0/run-series-retried/series")
    assert status == 200, body
    assert writes == []
    real = os.path.realpath(run)
    opened = {os.path.realpath(p) for p in RECORDER.opened if os.path.realpath(p).startswith(real)}
    assert opened == {os.path.realpath(run / "events.jsonl")}
    listed = [p for p in RECORDER.listed if os.path.realpath(p).startswith(real)]
    assert listed == []
    for planted in (b"unsealed_extra", b"linked_out", b"piped", b"outside every root"):
        assert planted not in body


def test_each_attempt_lists_what_its_sessions_sealed_as_the_review_reads_them(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series"
    events = _events(run)
    answer = _listing(world, "run-series")
    assert answer["tolerance"] == "0.005"
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert [(a["subtask_id"], a["attempt"]) for a in answer["attempts"]] == [
        (e.subtask_id, e.attempt) for e in ended
    ]
    for attempt, session in zip(answer["attempts"], ended, strict=True):
        assert attempt["owner_role"] == "control"
        assert attempt["sessions"] == [
            {
                "session_id": session.session_id,
                "outcome": "completed",
                "attempt_commit": session.attempt_commit,
            }
        ]
        sealed = attempt_records(events, session.subtask_id, session.attempt)
        assert sealed, "an attempt that sealed nothing would make this vacuous"
        assert attempt["records"] == [
            {
                "record_id": entry.record.record_id,
                "session_id": entry.session_id,
                "sha256": entry.record.sha256,
                "length": entry.record.length,
                "script": entry.record.script,
                "script_sha256": entry.record.script_sha256,
            }
            for entry in sealed
        ]
        assert attempt["superseded"] == []
        assert (attempt["merged"], attempt["rejected"], attempt["refused_by"]) == (
            True,
            False,
            None,
        )


def test_a_record_sealed_again_by_a_later_session_is_listed_as_superseded(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-retried"
    events = _events(run)
    first, retry = [e for e in events if isinstance(e, SessionEnded) and e.attempt == 1][:2]
    assert first.subtask_id == retry.subtask_id and first.outcome == "infrastructure"
    attempt = _attempts(_listing(world, "run-series-retried"))[(first.subtask_id, 1)]
    assert attempt["superseded"] == [
        {"record_id": record.record_id, "session_id": first.session_id}
        for record in first.series.records
    ]
    served = [(r["record_id"], r["session_id"]) for r in attempt["records"]]
    assert served == [
        (e.record.record_id, e.session_id) for e in attempt_records(events, first.subtask_id, 1)
    ]
    assert {session for _, session in served} == {retry.session_id}
    assert [s["outcome"] for s in attempt["sessions"]] == ["infrastructure", "completed"]


def test_every_file_a_session_set_aside_is_listed_with_its_reason(world: dict[str, Path]) -> None:
    run = world["runs"] / "run-series-retried"
    answer = _attempts(_listing(world, "run-series-retried"))
    ended = [e for e in _events(run) if isinstance(e, SessionEnded)]
    expected: dict[tuple[str, int], list[dict[str, str]]] = {}
    for session in ended:
        for kind, entries in (
            ("refused", session.series.refused),
            ("discarded", session.series.discarded),
        ):
            expected.setdefault((session.subtask_id, session.attempt), []).extend(
                {"session_id": session.session_id, "kind": kind, "name": e.name, "reason": e.reason}
                for e in entries
            )
    assert any(e["kind"] == "refused" for entries in expected.values() for e in entries)
    assert any(e["name"] == ".half_written.tmp" for entries in expected.values() for e in entries)
    assert {key: attempt["set_aside"] for key, attempt in answer.items()} == expected


def _unchecked_entry(line: GateRan, node: str, quantity: str) -> dict[str, Any]:
    (record,) = [
        r
        for r in line.result.checks
        if r.outcome == "unchecked"
        and r.node == node
        and quantity in getattr(r.details, "quantities", ())
    ]
    return {
        "seq": line.seq,
        "check": record.check,
        "name": record.name,
        "outcome": "unchecked",
        "gate_mode": line.result.mode,
        "blocking": record.blocking,
        "expected": record.expected,
        "low": None,
        "high": None,
    }


def test_a_quantity_the_gate_left_unchecked_is_given_that_record_and_a_pass_names_none(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series"
    for key, attempt in _attempts(_listing(world, "run-series")).items():
        line = _gate_line(run, *key)
        assert line.result.verdict == "pass"
        margin = _check(attempt, "phase_margin")
        assert margin["gate"] == [_unchecked_entry(line, margin["node_id"], "phase_margin")]
        assert margin["gate"][0]["check"] == 2 and margin["gate"][0]["name"] == "magnitude"
        # The magnitude check judged the peak and passed: a pass names no quantity, so the
        # peak is never shown as passed.
        assert _check(attempt, "step_peak")["gate"] == "not_named"


def test_a_failing_range_is_given_to_the_quantity_it_names_and_to_no_other_on_its_node(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-refused"
    subtask = _first_subtask(run)
    attempt = _attempts(_listing(world, "run-series-refused"))[(subtask, 1)]
    line = _gate_line(run, subtask, 1)
    peak = _check(attempt, "step_peak")
    (failing,) = [r for r in line.result.checks if r.outcome == "fail"]
    assert peak["gate"] == [
        {
            "seq": line.seq,
            "check": 2,
            "name": "magnitude",
            "outcome": "fail",
            "gate_mode": "on",
            "blocking": True,
            "expected": failing.expected,
            "low": {"value": PEAK_OUT_OF_RANGE[0], "unit": "m"},
            "high": {"value": PEAK_OUT_OF_RANGE[1], "unit": "m"},
        }
    ]
    # The phase margin sits on the same node: the failing record is the peak's, not its.
    margin = _check(attempt, "phase_margin")
    assert margin["gate"] == [_unchecked_entry(line, margin["node_id"], "phase_margin")]


def test_an_attempt_refused_before_the_gate_says_so_and_its_check_keeps_its_reason(
    world: dict[str, Path],
) -> None:
    run = world["runs"] / "run-series-refused"
    subtask = _first_subtask(run)
    attempts = _attempts(_listing(world, "run-series-refused"))
    refused = attempts[(subtask, 2)]
    assert refused["refused_by"] == "series"
    assert refused["records"] == []
    (check,) = refused["checks"]
    (recorded,) = next(
        e.series_checks
        for e in _events(run)
        if isinstance(e, ProposalsChecked) and (e.subtask_id, e.attempt) == (subtask, 2)
    )
    assert check["outcome"] == "unreadable" and check["reason"] == recorded.reason
    assert check["record_id"] == "loop_nominal" and check["read_value"] is None
    assert check["gate"] == "refused_before_gate"


def test_the_fate_of_each_attempt_is_read_off_its_own_lines(world: dict[str, Path]) -> None:
    run = world["runs"] / "run-series-refused"
    subtask = _first_subtask(run)
    answer = _attempts(_listing(world, "run-series-refused"))
    merged = {(e.subtask_id, e.attempt) for e in _events(run) if isinstance(e, Merged)}
    assert merged == {(subtask, 3)}
    assert set(answer) >= merged | rejected(run)
    for key, attempt in answer.items():
        assert attempt["merged"] is (key in merged), key
        assert attempt["rejected"] is (key in rejected(run)), key
    assert answer[(subtask, 1)]["refused_by"] is None
    assert answer[(subtask, 3)]["refused_by"] is None


def test_under_observe_the_failing_record_carries_the_mode_it_ran_in(
    world: dict[str, Path],
) -> None:
    answer = _attempts(_listing(world, "run-series-observe"))
    assert answer
    for attempt in answer.values():
        (entry,) = _check(attempt, "step_peak")["gate"]
        assert (entry["outcome"], entry["gate_mode"], entry["blocking"]) == (
            "fail",
            "observe",
            True,
        )
        assert attempt["merged"] is True


def test_with_the_gate_off_every_check_says_the_gate_did_not_run(world: dict[str, Path]) -> None:
    run = world["runs"] / "run-series-off"
    assert [e for e in _events(run) if isinstance(e, GateSkipped)]
    checks = [c for a in _listing(world, "run-series-off")["attempts"] for c in a["checks"]]
    assert len(checks) == 4
    assert {c["gate"] for c in checks} == {"gate_off"}


def test_a_check_whose_attempt_the_gate_has_not_reached_says_so(world: dict[str, Path]) -> None:
    checks = [c for a in _listing(world, "run-series-unjudged")["attempts"] for c in a["checks"]]
    assert len(checks) == 2
    assert {c["gate"] for c in checks} == {"gate_not_run"}


@pytest.mark.parametrize("forgery", ["no record matches", "two records match"])
def test_a_named_quantity_that_matches_no_failing_record_or_two_is_never_given_one(
    world: dict[str, Path], tmp_path: Path, forgery: str
) -> None:
    root, run = _copy(world, "run-series-refused", tmp_path)
    subtask = _first_subtask(run)

    def change(record: dict[str, Any]) -> None:
        checks = record["result"]["checks"]
        (failing,) = [c for c in checks if c["outcome"] == "fail"]
        if forgery == "no record matches":
            failing["value"]["value"] = 2.0
        else:
            checks.append(dict(failing))

    _forge(run, "gate_ran", change)
    assert _gate_line(run, subtask, 1).result.verdict == "fail"
    attempt = _attempts(_listing(world, "run-series-refused", root))[(subtask, 1)]
    assert _check(attempt, "step_peak")["gate"] == "unmatched"
    assert _check(attempt, "phase_margin")["gate"] != "unmatched"


def test_a_refusal_the_gate_still_judged_afterwards_is_shown_by_the_gate(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series-refused", tmp_path)
    subtask = _first_subtask(run)

    def refuse(record: dict[str, Any]) -> None:
        record["refused_by"] = "series"
        record["reason"] = "a refusal forged for this test"

    _forge(run, "proposals_checked", refuse)
    attempts = _attempts(_listing(world, "run-series-refused", root))
    first = attempts[(subtask, 1)]
    assert first["refused_by"] == "series"
    assert isinstance(_check(first, "step_peak")["gate"], list)
    assert _check(attempts[(subtask, 2)], "phase_margin")["gate"] == "refused_before_gate"


def test_an_integer_a_browser_cannot_hold_exactly_is_sent_as_its_numeral(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _copy(world, "run-series", tmp_path)

    def widen(record: dict[str, Any]) -> None:
        record["series_checks"][0]["declared_value"] = 2**63 - 1

    _forge(run, "proposals_checked", widen)
    attempt = _listing(world, "run-series", root)["attempts"][0]
    widened, other = attempt["checks"]
    assert widened["declared_value"] == "9223372036854775807"
    assert isinstance(other["declared_value"], float)
    assert isinstance(widened["read_value"], float)


def test_the_listing_answers_get_and_head_alike_stores_nothing_and_writes_nothing(
    world: dict[str, Path],
) -> None:
    names = sorted(p.name for p in world["runs"].iterdir() if (p / "run.json").is_file())
    assert len(names) >= 8
    before = snapshot(world["runs"])
    context = context_over(world["runs"], ui_root=world["ui"])
    with serving(context) as live, RECORDER.recording() as writes:
        for name in names:
            target = f"/api/runs/0/{name}/series"
            status, headers, body = live.request("GET", target)
            head_status, head_headers, head_body = live.request("HEAD", target)
            assert status == head_status == 200, (name, body)
            assert head_body == b""
            assert headers["content-length"] == head_headers["content-length"] == str(len(body))
            assert "no-store" in headers["cache-control"]
    assert writes == []
    assert snapshot(world["runs"]) == before


def test_no_such_run_is_404_and_a_line_no_writer_could_have_written_is_422(
    world: dict[str, Path], tmp_path: Path
) -> None:
    assert _get(world["runs"], world["ui"], "no-such-run")[0] == 404
    root, run = _copy(world, "run-series", tmp_path)
    with (run / "events.jsonl").open("ab") as log:
        log.write(b'{"not": "an event"}\n')
    status, _, body = _get(root, world["ui"], "run-series")
    assert status == 422
    assert b"attempts" not in body


def test_the_simulation_routes_import_nothing_from_the_evaluation_machinery() -> None:
    assert SIMULATION.is_file(), "the simulation routes live in their own module"
    tree = ast.parse(SIMULATION.read_text())
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "physgate.series.reader" in imported, "records are found through the reader's own rule"
    assert not [m for m in imported if m.startswith("physgate.evaluation")]
