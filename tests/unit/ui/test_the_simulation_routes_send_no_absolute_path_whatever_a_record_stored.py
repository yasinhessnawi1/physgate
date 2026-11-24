"""No answer of the simulation routes carries an absolute path of the machine that recorded.

A sealed record's file of the interpreter's installation is stored by its absolute path, and a
collector's reason for setting a file aside can name one. Those are sealed and logged as they
were, and they can hold a home folder and so an account name. The routes show a path relative
to the run, or a label; the sealed bytes and the log are not changed.

The runs are made by the real loop with the real gate (see ``ui_series_rig``); the stored
absolute paths are written into copies of their logs, in the field the writer's own line holds.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from ui_rig import context_over, fake_ui, serving
from ui_series_rig import series_runs

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.series.reader import attempt_records

#: What a recording machine's home folder looks like, and the account name in it.
HOME = "/Users/someone-private"
INSIDE_AND_OUTSIDE = (
    f"{HOME}/physgate-toolenv/env-1234/lib/python3.12/sitecustomize.py",
    "/opt/tools/lib/python3.12/os.py",
)
#: A path in any string: a slash that starts a word and is followed by a name and a slash.
ABSOLUTE = re.compile(r"(?:^|[\s'\"(=:])(/[\w.+@-]+/|[A-Za-z]:\\)")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("series")
    runs = base / "runs"
    series_runs(base, runs)
    return {"base": base, "runs": runs, "ui": fake_ui(base / "checkout")}


def _forged(world: dict[str, Path], name: str, tmp_path: Path, change: Any) -> tuple[Path, Path]:  # noqa: ANN401
    """A copy of run ``name`` whose first session end that sealed a record is changed."""
    root = tmp_path / "runs"
    run = root / name
    shutil.copytree(
        world["runs"] / name, run, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    log = run / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    at = next(
        i
        for i, raw in enumerate(lines)
        if json.loads(raw)["kind"] == "session_ended" and json.loads(raw)["series"]["records"]
    )
    record = json.loads(lines[at])
    change(record["series"])
    lines[at] = (json.dumps(record) + "\n").encode()
    log.write_bytes(b"".join(lines))
    return root, run


def _paths(value: object) -> list[str]:
    """Every string of an answer that holds an absolute path."""
    if isinstance(value, str):
        return [value] if ABSOLUTE.search(value) else []
    if isinstance(value, dict):
        return [p for v in value.values() for p in _paths(v)]
    if isinstance(value, list):
        return [p for v in value for p in _paths(v)]
    return []


def _get(world: dict[str, Path], root: Path, target: str) -> tuple[int, bytes]:
    with serving(context_over(root, ui_root=world["ui"])) as live:
        status, _, body = live.request("GET", target)
    return status, body


def _first_attempt(run: Path) -> tuple[str, int]:
    ended = next(
        e
        for e in read_events(run / "events.jsonl")
        if isinstance(e, SessionEnded) and e.series.records
    )
    return ended.subtask_id, ended.attempt


def test_a_file_of_the_installation_stored_by_its_absolute_path_is_shown_by_a_label(
    world: dict[str, Path], tmp_path: Path
) -> None:
    def store(series: dict[str, Any]) -> None:
        series["records"][0]["environment"] = [
            {"path": path, "sha256": "ab" * 32} for path in INSIDE_AND_OUTSIDE
        ]

    root, run = _forged(world, "run-series", tmp_path, store)
    subtask, attempt = _first_attempt(run)
    stored = attempt_records(read_events(run / "events.jsonl"), subtask, attempt)[0]
    assert [c.path for c in stored.record.environment] == list(INSIDE_AND_OUTSIDE)
    status, body = _get(world, root, f"/api/runs/0/run-series/series/{subtask}/{attempt}")
    assert status == 200, body
    row = json.loads(body)["records"][0]
    assert [f["path"] for f in row["environment"]] == [
        "<outside the run>/sitecustomize.py",
        "<outside the run>/os.py",
    ]
    assert [f["sha256"] for f in row["environment"]] == ["ab" * 32] * 2
    assert b"someone-private" not in body and HOME.encode() not in body
    assert _paths(json.loads(body)) == []


def test_a_reason_that_names_an_absolute_path_is_shown_with_the_path_relative_or_a_label(
    world: dict[str, Path], tmp_path: Path
) -> None:
    def name_paths(series: dict[str, Any]) -> None:
        run_path = str(tmp_path / "runs" / "run-series-retried")
        series["discarded"] = [
            {
                "name": "outside.json",
                "reason": f"ran from a path that is not plain: {INSIDE_AND_OUTSIDE[0]}",
            },
            {"name": "inside.json", "reason": f"the file {run_path}/series/x/1/y/z.json changed"},
        ]

    root, run = _forged(world, "run-series-retried", tmp_path, name_paths)
    status, body = _get(world, root, "/api/runs/0/run-series-retried/series")
    assert status == 200, body
    assert b"someone-private" not in body and str(run).encode() not in body
    reasons = {
        s["name"]: s["reason"]
        for a in json.loads(body)["attempts"]
        for s in a["set_aside"]
        if s["name"] in ("outside.json", "inside.json")
    }
    assert (
        reasons["outside.json"]
        == "ran from a path that is not plain: <outside the run>/sitecustomize.py"
    )
    assert reasons["inside.json"] == "the file series/x/1/y/z.json changed"
    assert _paths(json.loads(body)) == []


def test_no_string_any_simulation_route_sends_holds_an_absolute_path(
    world: dict[str, Path], tmp_path: Path
) -> None:
    def store(series: dict[str, Any]) -> None:
        series["records"][0]["environment"] = [{"path": INSIDE_AND_OUTSIDE[0], "sha256": "cd" * 32}]
        series["refused"] = [{"name": "stray.json", "reason": f"left by {INSIDE_AND_OUTSIDE[1]}"}]

    root, run = _forged(world, "run-series", tmp_path, store)
    subtask, attempt = _first_attempt(run)
    base = "/api/runs/0/run-series/series"
    sealed = attempt_records(read_events(run / "events.jsonl"), subtask, attempt)
    for target in (base, f"{base}/{subtask}/{attempt}"):
        status, body = _get(world, root, target)
        assert status == 200, body
        assert _paths(json.loads(body)) == [], target
        assert HOME.encode() not in body and str(run).encode() not in body
    for entry in sealed:
        status, body = _get(world, root, f"{base}/{subtask}/{attempt}/{entry.record.record_id}")
        assert status == 200, body
        assert str(run).encode() not in body


def test_a_refusal_names_the_record_by_its_place_in_the_run_without_a_path(
    world: dict[str, Path], tmp_path: Path
) -> None:
    root, run = _forged(world, "run-series", tmp_path, lambda series: None)
    subtask, attempt = _first_attempt(run)
    entry = attempt_records(read_events(run / "events.jsonl"), subtask, attempt)[0]
    entry.path(run).write_bytes(b"not what was sealed")
    status, body = _get(world, root, f"/api/runs/0/run-series/series/{subtask}/{attempt}")
    assert status == 200, body
    refused = [r for r in json.loads(body)["records"] if "refused" in r]
    assert refused and _paths(refused) == []
    assert str(run).encode() not in body
