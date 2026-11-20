"""The Evidence screen's catch count: the gate's own count per kind of run, never added together.

``GET /api/evidence/catches`` reads every run the roots hold, holds each to its first line, and
counts its gate events with the catch count the composition root handed in, once per kind:
reportable, development, ablation, in that order, each with the runs it counted. No count spans
two kinds and no answer holds a total. A run that cannot be read is named apart with its reason,
counted in no kind.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from ui_evidence_rig import EvidenceRuns, evidence_runs
from ui_rig import context_over, fake_ui, serving

from physgate.orchestrator.catches import catches
from physgate.orchestrator.events import read_events
from physgate.orchestrator.gate_events import GateEvent, gate_events
from physgate.orchestrator.run_config import load_run_config

ROUTE = "/api/evidence/catches"
#: Each kind's runs, in the root's order.
BY_KIND = {
    "reportable": ["ev-reportable"],
    "development": ["ev-development", "ev-drifted"],
    "ablation": ["ev-ablation"],
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[EvidenceRuns, Path, Path]:
    base = tmp_path_factory.mktemp("catches")
    return evidence_runs(base), fake_ui(base / "checkout"), base


def _answer(root: Path, ui: Path, held_out: tuple[str, ...] = ()) -> dict[str, Any]:
    with serving(context_over(root, ui_root=ui, held_out=held_out)) as live:
        status, _, body = live.request("GET", ROUTE)
    assert status == 200, body[:300]
    answer: dict[str, Any] = json.loads(body)
    assert set(answer) == {"kinds", "unread"}, answer
    return answer


def _catches(built: tuple[EvidenceRuns, Path, Path]) -> dict[str, Any]:
    made, ui, _ = built
    return _answer(made.runs, ui, tuple(str(r) for r in made.tier))


def _events(run_dir: Path) -> list[GateEvent]:
    """The run's gate events as ``physgate catches`` reads them."""
    log = read_events(run_dir / "events.jsonl")
    return gate_events(log, load_run_config(run_dir / "run.json").sha256())


def test_the_kinds_are_counted_apart_reportable_then_development_then_ablation(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    answer = _catches(built)
    assert [kind["kind"] for kind in answer["kinds"]] == list(BY_KIND)
    for kind in answer["kinds"]:
        assert set(kind) == {"kind", "runs", "rows"}, kind


@pytest.mark.parametrize("kind", list(BY_KIND))
def test_each_kind_s_rows_are_the_catch_count_over_that_kind_s_runs_alone(
    built: tuple[EvidenceRuns, Path, Path], kind: str
) -> None:
    made, _, _ = built
    answer = _catches(built)
    (counted,) = [k for k in answer["kinds"] if k["kind"] == kind] or [None]
    assert counted is not None, answer
    events = [e for name in BY_KIND[kind] for e in _events(made.runs / name)]
    assert events, f"the fixture's {kind} runs record no gate event"
    assert counted["rows"] == [row.model_dump(mode="json") for row in catches(events)]
    assert counted["rows"], kind


@pytest.mark.parametrize("kind", list(BY_KIND))
def test_each_kind_names_the_runs_it_counted_with_their_manifest_ids(
    built: tuple[EvidenceRuns, Path, Path], kind: str
) -> None:
    made, _, _ = built
    answer = _catches(built)
    (counted,) = [k for k in answer["kinds"] if k["kind"] == kind] or [None]
    assert counted is not None, answer
    expected = []
    for name in BY_KIND[kind]:
        recorded = load_run_config(made.runs / name / "run.json")
        expected.append(
            {
                "root": 0,
                "name": name,
                "run_id": name,
                "manifest_id": recorded.sha256(),
                "kind": kind,
                "harness_commit": recorded.harness.commit,
                "harness_clean": recorded.harness.clean,
            }
        )
    assert counted["runs"] == expected


def test_the_development_count_is_the_observed_gate_s_and_the_ablation_s_its_own(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    kinds = {kind["kind"]: kind for kind in _catches(built)["kinds"]}
    assert {row["gate_mode"] for row in kinds["development"]["rows"]} == {"observe"}
    assert {row["gate_mode"] for row in kinds["ablation"]["rows"]} == {"on"}
    assert {row["gate_mode"] for row in kinds["reportable"]["rows"]} == {"on"}


def test_a_run_that_cannot_be_read_is_named_apart_with_its_reason_and_counted_nowhere(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    answer = _catches(built)
    unread = {row["name"]: row for row in answer["unread"]}
    assert set(unread) == {"ev-tampered", "ev-unreadable"}
    assert unread["ev-tampered"] == {
        "root": 0,
        "name": "ev-tampered",
        "record": "run.json",
        "error": "the run's first line does not name the configuration recorded beside it",
    }
    assert set(unread["ev-unreadable"]) == {"root", "name", "record", "error", "offset", "reason"}
    assert unread["ev-unreadable"]["record"] == "events.jsonl"
    counted = {run["name"] for kind in answer["kinds"] for run in kind["runs"]}
    assert not counted & set(unread)


def test_with_no_run_each_kind_counts_nothing_and_says_so_by_an_empty_list(
    built: tuple[EvidenceRuns, Path, Path], tmp_path: Path
) -> None:
    _, ui, _ = built
    empty = tmp_path / "runs"
    empty.mkdir()
    assert _answer(empty, ui) == {
        "kinds": [{"kind": kind, "runs": [], "rows": []} for kind in BY_KIND],
        "unread": [],
    }


def test_no_answer_names_a_path_on_disk(built: tuple[EvidenceRuns, Path, Path]) -> None:
    _, _, base = built
    text = json.dumps(_catches(built))
    assert str(base) not in text
    assert os.path.realpath(base) not in text
