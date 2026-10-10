"""The graph and run routes serve exactly what the package's own readers answer.

Over six runs the real loop made: three with a test gate, and the physics gate's three-mode
plan rebuilt with the real gate. Each route is held to the reader it calls, independently:
the trace and the gate events to the bytes the command prints; the change list, the graph at a
revision and a node's history to the store itself, opened on a copy; the tokens to the account;
the decisions to the sequence read from the raw log; the status to the loop's own replay.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ui_rig import Live, context_over, fake_ui, real_runs, serving
from ui_three_mode_rig import three_mode_runs

from physgate.evaluation.observe.sequence import decisions
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    Decomposed,
    EventLog,
    Halted,
    StageEntered,
    WriteDone,
    read_events,
)
from physgate.orchestrator.gate_events import recorded_gate_checks
from physgate.orchestrator.replay import replay
from physgate.state.schema import validate_node
from physgate.state.store import Store

PHYSGATE = Path(sys.executable).parent / "physgate"
RUNS = ("run-on", "run-observe", "run-clean", "drive-on", "drive-observe", "drive-off")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("world")
    runs = real_runs(base)
    three_mode_runs(base, runs)
    return {"root": runs, "ui": fake_ui(base / "checkout")}


@pytest.fixture(scope="module")
def live(world: dict[str, Path]) -> Iterator[Live]:
    with serving(context_over(world["root"], ui_root=world["ui"])) as server:
        yield server


def _get(live: Live, run: str, route: str) -> tuple[int, bytes]:
    status, _, body = live.request("GET", f"/api/runs/0/{run}/{route}")
    return status, body


def _json(live: Live, run: str, route: str) -> Any:  # noqa: ANN401 - a JSON answer of any shape
    status, body = _get(live, run, route)
    assert status == 200, (run, route, body[:300])
    return json.loads(body)


def _cli(*argv: str) -> bytes:
    done = subprocess.run([str(PHYSGATE), *argv], capture_output=True, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def store(
    world: dict[str, Path], tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[Store]:
    """The run's store itself, opened on a copy so the served run is never written."""
    run: str = request.node.callspec.params["run"]
    copy = tmp_path / "store"
    shutil.copytree(world["root"] / run / "store", copy, symlinks=True)
    opened = Store(copy)
    yield opened
    opened.close()


def _node(payload: dict[str, Any]) -> object:
    return validate_node(payload).model_dump(mode="json")


# -- the run's records ---------------------------------------------------------------------


@pytest.mark.parametrize("run", RUNS)
def test_the_trace_is_the_bytes_the_command_prints(
    world: dict[str, Path], live: Live, run: str
) -> None:
    printed = _cli("trace", "--run-dir", str(world["root"] / run))
    status, served = _get(live, run, "trace")
    assert status == 200 and printed, "comparing two empty outputs proves nothing"
    assert served == printed


@pytest.mark.parametrize("run", ["drive-on", "drive-observe", "drive-off"])
def test_the_real_gate_s_events_are_the_bytes_the_command_prints(
    world: dict[str, Path], live: Live, run: str
) -> None:
    printed = _cli("gate-events", "--run-dir", str(world["root"] / run))
    status, served = _get(live, run, "gate-events")
    assert status == 200 and served == printed


@pytest.mark.parametrize("run", RUNS)
def test_the_trace_s_stages_are_the_log_s_stage_lines_in_order(
    world: dict[str, Path], live: Live, run: str
) -> None:
    steps = _json(live, run, "trace")["steps"]
    lines = [
        e for e in read_events(world["root"] / run / "events.jsonl") if isinstance(e, StageEntered)
    ]
    assert len(steps) > 5
    assert [(s["seq"], s["subtask_id"], s["attempt"], s["stage"]) for s in steps] == [
        (e.seq, e.subtask_id, e.attempt, e.stage) for e in lines
    ]


@pytest.mark.parametrize("run", RUNS)
def test_the_tokens_are_the_account_s(world: dict[str, Path], live: Live, run: str) -> None:
    account = TokenAccount.from_events(read_events(world["root"] / run / "events.jsonl"))
    served = _json(live, run, "tokens")
    assert served["by_attribution"] == {
        a: u.model_dump(mode="json") for a, u in account.by_attribution().items()
    }
    assert served["by_kind"] == {k: u.model_dump(mode="json") for k, u in account.by_kind().items()}
    assert served["total"] == account.total().model_dump(mode="json")
    assert (
        served["total"]["output_tokens"] > 0 and served["by_kind"]["routing"]["input_tokens"] == 0
    )


@pytest.mark.parametrize("run", RUNS)
def test_the_decisions_are_the_sequence_read_from_the_raw_log(
    world: dict[str, Path], live: Live, run: str
) -> None:
    raw = [
        json.loads(line) for line in (world["root"] / run / "events.jsonl").read_text().splitlines()
    ]
    served = _json(live, run, "decisions")["decisions"]
    assert served == decisions(raw) and served


def test_the_decisions_carry_the_repair_attempts_finding_keys(live: Live) -> None:
    rejected = [
        d for d in _json(live, "drive-on", "decisions")["decisions"] if d["step"] == "rejected"
    ]
    assert [d["attempt"] for d in rejected] == [1, 2, 3]
    assert all(d["finding_key"].startswith("gate|") for d in rejected)


@pytest.mark.parametrize("run", RUNS)
def test_the_status_is_the_loop_s_own_next_step(
    world: dict[str, Path], live: Live, run: str
) -> None:
    state = replay(read_events(world["root"] / run / "events.jsonl"))
    step = state.next_step()
    served = _json(live, run, "status")
    assert served["next_step"] == {
        "kind": step.kind,
        "subtask_id": step.subtask_id,
        "attempt": step.attempt,
        "point": step.point,
    }
    assert served["halted"] is None and step.kind == "done"


@pytest.mark.parametrize("run", RUNS)
def test_the_gate_checks_are_the_reader_s(world: dict[str, Path], live: Live, run: str) -> None:
    found = recorded_gate_checks(
        world["root"] / run / "events.jsonl", world["root"] / run / "run.json"
    )
    status, body = _get(live, run, "gate-checks")
    assert status == 200
    assert [json.loads(line) for line in body.splitlines()] == [
        json.loads(c.model_dump_json()) for c in found
    ]


# -- the graph ------------------------------------------------------------------------------


@pytest.mark.parametrize("run", RUNS)
def test_the_change_list_between_any_two_revisions_is_the_store_s(
    live: Live, store: Store, run: str
) -> None:
    head = store.head_revision()
    assert head >= 1
    for since in range(0, head + 1):
        whole = store.diff(since)
        for until in range(since, head + 1):
            served = _json(live, run, f"graph/diff/{since}/{until}")
            want = [c for c in whole if c.revision <= until]
            assert [
                (c["revision"], c["node_id"], c["version"], c["op"]) for c in served["changes"]
            ] == [(c.revision, c.node_id, c.version, c.op) for c in want]
            assert sorted(served["nodes"]) == sorted({c.node_id for c in want})
            for node_id, sides in served["nodes"].items():
                for side, revision in (("before", since), ("after", until)):
                    earlier = [r for r in store.history(node_id) if r <= revision]
                    expected = (
                        None
                        if not earlier
                        else {"revision": earlier[-1], "node": _node(store.payload_at(earlier[-1]))}
                    )
                    assert sides[side] == expected, (since, until, node_id, side)


@pytest.mark.parametrize("run", RUNS)
def test_the_graph_at_any_revision_is_the_store_s(live: Live, store: Store, run: str) -> None:
    head = store.head_revision()
    ids = sorted({c.node_id for c in store.diff(0)})
    for revision in range(0, head + 1):
        served = _json(live, run, f"graph/at/{revision}")
        assert served["revision"] == revision and served["head_revision"] == head
        want = {}
        for node_id in ids:
            earlier = [r for r in store.history(node_id) if r <= revision]
            if earlier:
                want[node_id] = {
                    "revision": earlier[-1],
                    "node": _node(store.payload_at(earlier[-1])),
                }
        assert served["nodes"] == want
    at_head = _json(live, run, f"graph/at/{head}")["nodes"]
    assert at_head == _json(live, run, "graph")["nodes"]


@pytest.mark.parametrize("run", RUNS)
def test_a_node_s_history_is_the_store_s_and_names_its_writer(
    world: dict[str, Path], live: Live, store: Store, run: str
) -> None:
    events = read_events(world["root"] / run / "events.jsonl")
    (decomposed,) = [e for e in events if isinstance(e, Decomposed)]
    baseline = decomposed.head_revision
    wrote = {
        e.revision: {"subtask_id": e.subtask_id, "attempt": e.attempt}
        for e in events
        if isinstance(e, WriteDone)
    }
    for node_id in sorted({c.node_id for c in store.diff(0)}):
        served = _json(live, run, f"graph/history/{node_id}")
        assert served["baseline"] == baseline
        assert [h["revision"] for h in served["history"]] == store.history(node_id)
        for entry in served["history"]:
            assert entry["node"] == _node(store.payload_at(entry["revision"]))
            want = "decomposition" if entry["revision"] <= baseline else wrote[entry["revision"]]
            assert entry["written_by"] == want


def test_a_revision_the_journal_lacks_or_a_backwards_diff_is_not_found(live: Live) -> None:
    for route in (
        "graph/at/999",
        "graph/diff/0/999",
        "graph/diff/2/1",
        "graph/history/electrical.none",
    ):
        status, body = _get(live, "drive-observe", route)
        assert status == 404, (route, body[:200])
    for route in ("graph/at/-1", "graph/at/01", "graph/history/Electrical.x", "graph/history/a"):
        status, _ = _get(live, "drive-observe", route)
        assert status == 404, route


def test_the_status_of_a_run_stopped_mid_way_is_where_it_stopped(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """Every built run ends done, so here one is cut at its first gate line, as a kill would."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / "drive-observe", root / "drive-observe", symlinks=True)
    log = root / "drive-observe" / "events.jsonl"
    lines = log.read_text().splitlines(keepends=True)
    cut = next(i for i, line in enumerate(lines) if json.loads(line)["kind"] == "gate_ran")
    log.write_text("".join(lines[:cut]))
    step = replay(read_events(log)).next_step()
    assert step.kind != "done"
    with serving(context_over(root, ui_root=world["ui"])) as server:
        served = _json(server, "drive-observe", "status")
    assert served["next_step"] == {
        "kind": step.kind,
        "subtask_id": step.subtask_id,
        "attempt": step.attempt,
        "point": step.point,
    }


def test_the_status_of_a_halted_run_names_its_halt(world: dict[str, Path], tmp_path: Path) -> None:
    """A halt is a line in the log, and the route serves it: its reason, its detail, its line."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / "run-clean", root / "run-clean", symlinks=True)
    path = root / "run-clean" / "events.jsonl"
    config = json.loads((root / "run-clean" / "run.json").read_text())
    log = EventLog(path, run_id=config["run_id"], gate_mode=config["gate_mode"])
    halted = log.emit(Halted, reason="infrastructure_exhausted", detail="the retries ran out")
    log.close()
    state = replay(read_events(path))
    assert state.halted is not None and state.next_step().kind == "halted"
    with serving(context_over(root, ui_root=world["ui"])) as server:
        served = _json(server, "run-clean", "status")
    assert served["next_step"]["kind"] == "halted"
    assert served["halted"] == {
        "seq": halted.seq,
        "reason": "infrastructure_exhausted",
        "detail": "the retries ran out",
    }
