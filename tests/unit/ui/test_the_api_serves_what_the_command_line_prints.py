"""The API's gate events and ledger are byte for byte what the command line prints.

The command is run as its own process, as an operator runs it, on runs the real loop made; the
API is asked over HTTP for the same run. Equality comes from both calling one function and
writing through one serialiser, not from matching formats; this test is what would notice if
either side ever stopped doing that. Every comparison first asserts there is something to
compare, and the observed run carries a gate event a reviewer had passed, so the field the
thesis counts is among the bytes compared.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ui_rig import context_over, fake_ui, real_runs, sealed_session, serving

PHYSGATE = Path(sys.executable).parent / "physgate"
RUNS = ("run-on", "run-observe", "run-clean")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("world")
    return {"root": real_runs(base), "ui": fake_ui(base / "checkout")}


def _cli(*argv: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(PHYSGATE), *argv], capture_output=True, check=False)


def _api(root: Path, ui: Path, target: str) -> tuple[int, bytes]:
    with serving(context_over(root, ui_root=ui)) as live:
        status, _, body = live.request("GET", target)
    return status, body


def _copy(world: dict[str, Path], tmp_path: Path, run: str) -> Path:
    """A copy of one run under a root of its own, to damage without touching the others."""
    root = tmp_path / "copied"
    shutil.copytree(world["root"] / run, root / run, symlinks=True)
    return root


@pytest.mark.parametrize("run", RUNS)
def test_the_api_s_gate_events_are_the_cli_s_bytes(world: dict[str, Path], run: str) -> None:
    printed = _cli("gate-events", "--run-dir", str(world["root"] / run))
    assert printed.returncode == 0, printed.stderr
    status, served = _api(world["root"], world["ui"], f"/api/runs/0/{run}/gate-events")
    assert status == 200
    assert printed.stdout, "comparing two empty outputs proves nothing"
    assert served == printed.stdout


def test_the_compared_gate_events_include_one_a_reviewer_had_passed(
    world: dict[str, Path],
) -> None:
    _, served = _api(world["root"], world["ui"], "/api/runs/0/run-observe/gate-events")
    lines = [json.loads(line) for line in served.splitlines()]
    assert any(line["reviewer_had_passed"] is True and line["outcome"] == "fail" for line in lines)


@pytest.mark.parametrize("run", RUNS)
def test_the_api_s_ledger_is_the_cli_s_bytes_and_the_file_s(
    world: dict[str, Path], run: str
) -> None:
    printed = _cli("ledger", "--run-dir", str(world["root"] / run))
    assert printed.returncode == 0, printed.stderr
    status, served = _api(world["root"], world["ui"], f"/api/runs/0/{run}/ledger")
    assert status == 200
    assert printed.stdout, "comparing two empty outputs proves nothing"
    assert served == printed.stdout == (world["root"] / run / "ledger.jsonl").read_bytes()


def test_a_ledger_the_event_log_does_not_imply_is_refused_by_both(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root = _copy(world, tmp_path, "run-on")
    ledger = root / "run-on" / "ledger.jsonl"
    lines = ledger.read_text().splitlines(keepends=True)
    first = json.loads(lines[0])
    first["assigned_role"] = "firmware"
    ledger.write_text(json.dumps(first, separators=(",", ":")) + "\n" + "".join(lines[1:]))
    printed = _cli("ledger", "--run-dir", str(root / "run-on"))
    assert printed.returncode == 2
    assert b"disagrees with the run-event log" in printed.stderr
    status, served = _api(root, world["ui"], "/api/runs/0/run-on/ledger")
    assert status == 422
    assert b"disagrees with the run-event log" in served


def test_a_ledger_behind_its_log_is_shown_as_far_as_it_goes(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """A killed orchestrator can leave the ledger short of the log; it is still a prefix."""
    root = _copy(world, tmp_path, "run-on")
    ledger = root / "run-on" / "ledger.jsonl"
    lines = ledger.read_bytes().splitlines(keepends=True)
    ledger.write_bytes(b"".join(lines[:-1]))
    printed = _cli("ledger", "--run-dir", str(root / "run-on"))
    status, served = _api(root, world["ui"], "/api/runs/0/run-on/ledger")
    assert printed.returncode == 0
    assert status == 200
    assert served == printed.stdout == b"".join(lines[:-1])


def test_a_corrupt_ledger_line_is_refused_by_both_and_left_on_disk(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root = _copy(world, tmp_path, "run-clean")
    ledger = root / "run-clean" / "ledger.jsonl"
    with ledger.open("ab") as handle:
        handle.write(b'{"not": "a line"}\n')
    before = ledger.read_bytes()
    assert _cli("ledger", "--run-dir", str(root / "run-clean")).returncode == 2
    assert _api(root, world["ui"], "/api/runs/0/run-clean/ledger")[0] == 422
    assert ledger.read_bytes() == before


def test_the_api_s_cost_is_the_cli_s_line(world: dict[str, Path]) -> None:
    printed = _cli("cost", "--run-dir", str(world["root"] / "run-on"), "--prices", "2026-09-27")
    assert printed.returncode == 0, printed.stderr
    expected = json.loads(printed.stdout)
    for added_by_the_command in ("basis_label", "appended_to"):
        expected.pop(added_by_the_command)
    status, served = _api(world["root"], world["ui"], "/api/runs/0/run-on/cost/2026-09-27")
    assert status == 200
    assert json.loads(served) == expected
    assert expected["rows"], "a cost with no rows proves nothing"


def test_an_unrecorded_price_sheet_is_refused(world: dict[str, Path]) -> None:
    status, served = _api(world["root"], world["ui"], "/api/runs/0/run-on/cost/2026-01-01")
    assert status == 422
    assert b"no price sheet" in served


def test_a_trajectory_is_the_sealed_stream(world: dict[str, Path]) -> None:
    run_dir = world["root"] / "run-observe"
    session = sealed_session(run_dir)
    status, served = _api(
        world["root"], world["ui"], f"/api/runs/0/run-observe/trajectories/{session}"
    )
    assert status == 200
    assert served == (run_dir / "sessions" / session / "stdout.jsonl").read_bytes()
    seals = [
        json.loads(raw)["trajectory_seal"]
        for raw in (run_dir / "events.jsonl").read_text().splitlines()
        if json.loads(raw).get("session_id") == session and json.loads(raw).get("trajectory_seal")
    ]
    assert hashlib.sha256(served).hexdigest() == seals[0]["sha256"]


def test_a_trajectory_is_found_by_its_session_id_not_by_the_path_the_record_names(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """The record names the stream where it was written; the copy is served from the copy."""
    root = _copy(world, tmp_path, "run-observe")
    session = sealed_session(root / "run-observe")
    recorded = [
        json.loads(raw)["trajectory"]
        for raw in (root / "run-observe" / "events.jsonl").read_text().splitlines()
        if json.loads(raw).get("session_id") == session and json.loads(raw).get("trajectory")
    ]
    assert recorded and not recorded[0].startswith(str(root)), "the record names the original"
    status, _ = _api(root, world["ui"], f"/api/runs/0/run-observe/trajectories/{session}")
    assert status == 200


def test_a_changed_trajectory_is_refused(world: dict[str, Path], tmp_path: Path) -> None:
    root = _copy(world, tmp_path, "run-observe")
    session = sealed_session(root / "run-observe")
    stream = root / "run-observe" / "sessions" / session / "stdout.jsonl"
    stream.write_bytes(stream.read_bytes() + b'{"type":"forged"}\n')
    status, served = _api(root, world["ui"], f"/api/runs/0/run-observe/trajectories/{session}")
    assert status == 422
    assert b"not what it was when its session ended" in served


def test_a_session_the_run_does_not_record_is_not_found(world: dict[str, Path]) -> None:
    status, _ = _api(world["root"], world["ui"], "/api/runs/0/run-observe/trajectories/nobody")
    assert status == 404


def test_a_run_the_roots_do_not_hold_is_not_found(world: dict[str, Path]) -> None:
    assert _api(world["root"], world["ui"], "/api/runs/0/run-elsewhere/ledger")[0] == 404
    assert _api(world["root"], world["ui"], "/api/runs/1/run-on/ledger")[0] == 404


def test_the_graph_is_every_node_at_its_latest_revision_with_its_units(
    world: dict[str, Path],
) -> None:
    status, served = _api(world["root"], world["ui"], "/api/runs/0/run-on/graph")
    assert status == 200
    graph = json.loads(served)
    assert graph["nodes"], "a graph with no nodes proves nothing"
    journal = (world["root"] / "run-on" / "store" / "journal.jsonl").read_text().splitlines()
    assert graph["head_revision"] == len(journal)
    for entry in graph["nodes"].values():
        for quantity in entry["node"]["quantities"].values():
            assert quantity["unit"]


def test_the_config_names_the_manifest_id_every_gate_event_carries(
    world: dict[str, Path],
) -> None:
    _, config = _api(world["root"], world["ui"], "/api/runs/0/run-observe/config")
    _, events = _api(world["root"], world["ui"], "/api/runs/0/run-observe/gate-events")
    manifest_id = json.loads(config)["manifest_id"]
    assert {json.loads(line)["manifest_id"] for line in events.splitlines()} == {manifest_id}


def test_the_events_route_serves_every_line_of_the_log(world: dict[str, Path]) -> None:
    _, served = _api(world["root"], world["ui"], "/api/runs/0/run-on/events")
    log = (world["root"] / "run-on" / "events.jsonl").read_text().splitlines()
    assert len(served.splitlines()) == len(log) > 0


def test_the_prices_route_lists_the_recorded_sheets(world: dict[str, Path]) -> None:
    with serving(context_over(world["root"], ui_root=world["ui"])) as live:
        assert live.json("/api/prices") == {"prices": ["2026-09-27"]}
