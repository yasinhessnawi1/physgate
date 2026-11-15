"""The Evidence screen's run list: every run, its kind, what it recorded, or why it cannot be read.

``GET /api/evidence/runs`` answers one row per run the roots hold. A row names the run by its
root's position and its directory's name, and carries the run id, the seed, the manifest id held
to the digest the log's first line names, the run's kind (reportable, ablation, or development:
neither), every setting a comparison reports beside its numbers as the record holds it, and
every pin a comparison is refused across, less the held-out tier's digest. Nothing of the
held-out tier is in any row.

A run that cannot be read is a row too, never a refusal of the list: its configuration changed
after it started, or its log holds a line this package could not have written. Such a row holds
the sentence, the record it came from and the reader's own reason, and no other field; it names
the run by place, never by a path on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from ui_evidence_rig import (
    CANARIES,
    DRIFTED_MODEL,
    DRIFTED_TOKENS,
    RUNS,
    EvidenceRuns,
    evidence_runs,
    tier_digest,
)
from ui_rig import RECORDER, context_over, fake_ui, serving

from physgate.evaluation.observe.compare import DRIFT, REPORTED
from physgate.orchestrator.events import RunStarted, read_events
from physgate.orchestrator.run_config import load_run_config

ROUTE = "/api/evidence/runs"
#: The record's fields that name the held-out tier.
TIER_FIELDS = ("held_out", "held_out_canaries", "held_out_sha256")
#: The runs whose records read whole.
READABLE = ("ev-ablation", "ev-development", "ev-drifted", "ev-reportable")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[EvidenceRuns, Path, Path]:
    base = tmp_path_factory.mktemp("evidence")
    return evidence_runs(base), fake_ui(base / "checkout"), base


def _get(built: tuple[EvidenceRuns, Path, Path], *targets: str) -> list[tuple[int, bytes]]:
    made, ui, _ = built
    context = context_over(made.runs, ui_root=ui, held_out=tuple(str(r) for r in made.tier))
    answers: list[tuple[int, bytes]] = []
    with serving(context) as live:
        for target in targets:
            status, _, body = live.request("GET", target)
            answers.append((status, body))
    return answers


def _rows(built: tuple[EvidenceRuns, Path, Path]) -> dict[str, dict[str, Any]]:
    ((status, body),) = _get(built, ROUTE)
    assert status == 200, body[:300]
    rows: list[dict[str, Any]] = json.loads(body)["runs"]
    return {row["name"]: row for row in rows}


def _at(recorded: dict[str, Any], path: str) -> object:
    value: Any = recorded
    for part in path.split("."):
        value = value[part]
    return value


def test_every_run_the_root_holds_is_one_row_in_the_root_s_order(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    ((status, body),) = _get(built, ROUTE)
    assert status == 200, body[:300]
    rows = json.loads(body)["runs"]
    assert [(row["root"], row["name"]) for row in rows] == [(0, name) for name in RUNS]


def test_each_run_s_kind_is_read_from_its_record(built: tuple[EvidenceRuns, Path, Path]) -> None:
    rows = _rows(built)
    assert {name: rows[name]["kind"] for name in READABLE} == {
        "ev-ablation": "ablation",
        "ev-development": "development",
        "ev-drifted": "development",
        "ev-reportable": "reportable",
    }


@pytest.mark.parametrize("name", READABLE)
def test_a_row_carries_what_its_run_recorded_and_the_manifest_id_its_first_line_names(
    built: tuple[EvidenceRuns, Path, Path], name: str
) -> None:
    made, _, _ = built
    run_dir = made.runs / name
    recorded = load_run_config(run_dir / "run.json").model_dump(mode="json")
    digest = hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()
    started = read_events(run_dir / "events.jsonl")[0]
    assert isinstance(started, RunStarted)
    assert started.config_sha256 == digest, "the fixture's first line names its record"
    row = _rows(built)[name]
    assert row["run_id"] == recorded["run_id"] == name
    assert row["seed"] == recorded["seed"]
    assert row["manifest_id"] == digest
    assert row["flags"] == {field: recorded[field] for field in REPORTED}
    pins = [path for path in DRIFT if path not in TIER_FIELDS]
    assert row["pins"] == {path: _at(recorded, path) for path in pins}
    assert set(row) == {"root", "name", "run_id", "seed", "manifest_id", "kind", "flags", "pins"}


def test_the_kinds_differ_where_each_run_was_made_to(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    rows = _rows(built)
    assert rows["ev-ablation"]["flags"]["hooks"] == "off"
    assert rows["ev-ablation"]["flags"]["ablation"] is True
    assert rows["ev-ablation"]["flags"]["reportable"] is False
    assert rows["ev-reportable"]["flags"]["reportable"] is True
    assert rows["ev-reportable"]["flags"]["harness"]["clean"] is True
    assert rows["ev-development"]["flags"]["gate_mode"] == "observe"
    assert rows["ev-drifted"]["pins"]["models.roles"] == {"electrical": DRIFTED_MODEL}
    assert rows["ev-drifted"]["pins"]["max_output_tokens"] == DRIFTED_TOKENS
    assert rows["ev-development"]["pins"]["models.roles"] != {"electrical": DRIFTED_MODEL}


def test_no_row_carries_the_held_out_tier(built: tuple[EvidenceRuns, Path, Path]) -> None:
    made, _, _ = built
    record = (made.runs / "ev-reportable" / "run.json").read_text()
    recorded = [*CANARIES, *(tier_digest(r) for r in made.tier), *(str(r) for r in made.tier)]
    assert [leak for leak in recorded if leak not in record] == [], "no tier to withhold"
    # A root's own name and its real path say where the tier lives as plainly as its path.
    leaks = [*recorded, *(os.path.realpath(r) for r in made.tier), *(r.name for r in made.tier)]
    ((status, body),) = _get(built, ROUTE)
    assert status == 200
    assert [leak for leak in leaks if leak in body.decode()] == []
    for row in json.loads(body)["runs"]:
        named = set(row) | set(row.get("flags", {})) | set(row.get("pins", {}))
        assert not named & set(TIER_FIELDS), row["name"]


def test_a_run_whose_configuration_changed_after_it_started_is_a_row_with_the_sentence_alone(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    assert _rows(built)["ev-tampered"] == {
        "root": 0,
        "name": "ev-tampered",
        "record": "run.json",
        "error": "the run's first line does not name the configuration recorded beside it",
    }


def test_a_run_whose_log_holds_a_line_this_package_cannot_read_is_a_row_with_its_reason(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    row = _rows(built)["ev-unreadable"]
    assert set(row) == {"root", "name", "record", "error", "offset", "reason"}
    assert (row["root"], row["name"], row["record"]) == (0, "ev-unreadable", "events.jsonl")
    assert row["error"] == "the run-event log holds a line this package could not have written"
    assert row["reason"]
    assert int(row["offset"]) > 0


def test_no_answer_names_a_path_on_disk(built: tuple[EvidenceRuns, Path, Path]) -> None:
    _, _, base = built
    ((status, body),) = _get(built, ROUTE)
    assert status == 200
    text = body.decode()
    assert str(base) not in text
    assert os.path.realpath(base) not in text


def test_with_no_run_under_the_root_the_list_is_empty(
    built: tuple[EvidenceRuns, Path, Path], tmp_path: Path
) -> None:
    _, ui, _ = built
    empty = tmp_path / "runs"
    empty.mkdir()
    with serving(context_over(empty, ui_root=ui)) as live:
        status, _, body = live.request("GET", ROUTE)
    assert status == 200
    assert json.loads(body) == {"runs": []}


@pytest.mark.parametrize(
    "target",
    [
        "/api/evidence/runs/..%2f..%2ftier",
        "/api/evidence/runs/%2e%2e/%2e%2e/tier/scenarios-e3a1/task.json",
        "/api/evidence/runs/../../tier/scenarios-e3a1/task.json",
        "/api/evidence/%252e%252e/runs",
        "/api/evidence/runs/0/..%2f..%2ftier",
        "/api/evidence/runs%2f..%2f..%2ftier",
    ],
)
def test_a_request_naming_the_tier_by_any_spelling_reads_nothing_there(
    built: tuple[EvidenceRuns, Path, Path], target: str
) -> None:
    made, _, _ = built
    with RECORDER.recording():
        ((status, body),) = _get(built, target)
    assert status in (400, 404), (target, status)
    assert b"task.json" not in body
    assert b"scenarios-e3a1" not in body
    tier = [os.path.realpath(r) for r in made.tier]
    assert [p for p in RECORDER.opened + RECORDER.listed if p.startswith(tuple(tier))] == []


def test_a_run_directory_linked_from_the_tier_is_never_listed_or_read(
    built: tuple[EvidenceRuns, Path, Path], tmp_path: Path
) -> None:
    import shutil

    made, ui, _ = built
    root = tmp_path / "runs"
    shutil.copytree(
        made.runs / "ev-development",
        root / "ev-development",
        symlinks=True,
        ignore=shutil.ignore_patterns("worktrees"),
    )
    held = tmp_path / "held"
    shutil.copytree(made.runs / "ev-reportable", held / "a-run", symlinks=True)
    (root / "ev-linked").symlink_to(held / "a-run")
    context = context_over(root, ui_root=ui, held_out=(str(held),))
    with serving(context) as live, RECORDER.recording():
        status, _, body = live.request("GET", ROUTE)
    assert status == 200
    assert [row["name"] for row in json.loads(body)["runs"]] == ["ev-development"]
    away = os.path.realpath(held)
    assert [p for p in RECORDER.opened if os.path.realpath(p).startswith(away)] == []


def test_a_run_with_no_log_yet_is_a_row_saying_so(
    built: tuple[EvidenceRuns, Path, Path], tmp_path: Path
) -> None:
    from ui_rig import write_run

    _, ui, _ = built
    root = tmp_path / "runs"
    write_run(root / "run-unstarted", "run-unstarted")
    with serving(context_over(root, ui_root=ui)) as live:
        status, _, body = live.request("GET", ROUTE)
    assert status == 200, body[:300]
    assert json.loads(body)["runs"] == [
        {
            "root": 0,
            "name": "run-unstarted",
            "record": "events.jsonl",
            "error": "the run directory holds no event log",
        }
    ]
