"""Records of the kinds and fields a real control run leaves are all shown, each with its units.

A real run's records were read before this was written (the review's listing and the attempt
route over a finished run's sealed records); what that showed is held here on records the
writer makes in the same shape, so nothing of a real run is copied into the repository: the
role's own groups, eight traces to a record, twelve inputs with units spelt as the writer
admits them, and a loop's frequency response among them. Each record is answered with its
group, its columns' names and units, its inputs and the very bytes it sealed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ui_rig import context_over, fake_ui, serving
from ui_series_rig import series_runs

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.series.reader import attempt_records

GROUPS = {
    "simulation",
    "edge_runs",
    "corners",
    "sweeps",
    "noise",
    "model",
    "sensitivity",
    "margins",
}
TRACES = [
    ("tilt", "rad"),
    ("tilt_rate", "rad/s"),
    ("ground_speed", "m/s"),
    ("speed_mean_1s", "m/s"),
    ("position", "m"),
    ("command", "1"),
    ("speed_command", "m/s"),
    ("theta_hat", "rad"),
]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("series")
    runs = base / "runs"
    series_runs(base, runs)
    return {"runs": runs, "ui": fake_ui(base / "checkout")}


def _get(world: dict[str, Path], target: str) -> tuple[int, bytes]:
    with serving(context_over(world["runs"], ui_root=world["ui"])) as live:
        status, _, body = live.request("GET", target)
    return status, body


def _attempt(world: dict[str, Path]) -> tuple[str, int, list[dict[str, Any]]]:
    run = world["runs"] / "run-series-real-shape"
    ended = next(
        e
        for e in read_events(run / "events.jsonl")
        if isinstance(e, SessionEnded) and e.series.records
    )
    status, body = _get(
        world, f"/api/runs/0/run-series-real-shape/series/{ended.subtask_id}/{ended.attempt}"
    )
    assert status == 200, body
    return ended.subtask_id, ended.attempt, json.loads(body)["records"]


def test_every_record_of_the_shape_a_real_run_leaves_is_shown_and_none_is_refused(
    world: dict[str, Path],
) -> None:
    _, _, rows = _attempt(world)
    assert len(rows) == 9
    assert [r for r in rows if "refused" in r] == []
    assert {r["group"] for r in rows} == GROUPS


def test_a_record_of_eight_traces_keeps_each_name_and_unit_as_the_writer_recorded_them(
    world: dict[str, Path],
) -> None:
    _, _, rows = _attempt(world)
    (fall,) = [r for r in rows if r["record_id"] == "nominal_fall"]
    assert fall["axis"] == "time" and fall["loop"] is False
    assert [(t["name"], t["unit"]) for t in fall["traces"]] == TRACES
    assert (fall["x"]["name"], fall["x"]["unit"], fall["x"]["samples"]) == ("time", "s", 400)
    assert all(t["samples"] == 400 for t in fall["traces"])
    (ratio,) = [r for r in rows if r["record_id"] == "ratio_check"]
    assert [(t["name"], t["unit"]) for t in ratio["traces"]] == [("tilt_over_rate", "s")]


def test_a_loop_s_frequency_response_is_drawn_as_one_and_keeps_its_units(
    world: dict[str, Path],
) -> None:
    _, _, rows = _attempt(world)
    (loop,) = [r for r in rows if r["record_id"] == "loop_body_high"]
    assert loop["loop"] is True and loop["axis"] == "frequency" and loop["group"] == "margins"
    assert (loop["x"]["name"], loop["x"]["unit"]) == ("angular_frequency", "rad/s")
    assert [(t["name"], t["unit"]) for t in loop["traces"]] == [
        ("loop_magnitude", "dimensionless"),
        ("loop_phase", "rad"),
    ]
    assert [r["loop"] for r in rows].count(True) == 1


def test_twelve_inputs_keep_the_value_and_the_unit_each_was_given_with(
    world: dict[str, Path],
) -> None:
    _, _, rows = _attempt(world)
    inputs = rows[0]["inputs"]
    assert len(inputs) == 12
    assert inputs["rotor_inertia"] == {"value": 1e-08, "unit": "kg*m**2"}
    assert inputs["speed_ramp"] == {"value": 0.1, "unit": "m/s**2"}
    assert inputs["body_inertia_scale"] == {"value": 2.0, "unit": "1"}
    assert inputs["seed"] == {"value": 0, "unit": "dimensionless"}


def test_each_record_is_served_as_the_very_bytes_it_sealed(world: dict[str, Path]) -> None:
    subtask, attempt, rows = _attempt(world)
    run = world["runs"] / "run-series-real-shape"
    events = read_events(run / "events.jsonl")
    for entry in attempt_records(events, subtask, attempt):
        status, body = _get(
            world,
            f"/api/runs/0/run-series-real-shape/series/{subtask}/{attempt}/{entry.record.record_id}",
        )
        assert status == 200
        assert body == entry.path(run).read_bytes()
