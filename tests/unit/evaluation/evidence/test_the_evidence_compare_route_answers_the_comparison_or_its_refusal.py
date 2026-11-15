"""The Evidence screen's comparison: the comparison's own answer for two runs, or its refusal.

``GET /api/evidence/compare/{a_root}/{a_name}/{b_root}/{b_name}`` holds both runs to the roots
and to their first lines, then calls the comparison the composition root handed in: its side by
side as it serialises, beside each run's place, id, manifest id and kind. Two runs answered under
different pins are its refusal, 422, naming every drifted setting by its path and no value of
it; a held-out tier's digest is named as a field and never shown. A run that is not there is
404; a run that cannot be read is 422 naming which run, by its place, never a path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from ui_evidence_rig import CANARIES, DRIFTED_MODEL, EvidenceRuns, evidence_runs, tier_digest
from ui_rig import context_over, fake_ui, serving

from physgate.evaluation.observe.compare import compare, drift
from physgate.orchestrator.run_config import load_run_config

REFUSED = (
    "the runs were answered under different pins, or asked different things: re-run "
    "the baseline under the candidate's before comparing"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[EvidenceRuns, Path, Path]:
    base = tmp_path_factory.mktemp("compare")
    return evidence_runs(base), fake_ui(base / "checkout"), base


def _compare(built: tuple[EvidenceRuns, Path, Path], a: str, b: str) -> tuple[int, Any]:
    made, ui, _ = built
    context = context_over(made.runs, ui_root=ui, held_out=tuple(str(r) for r in made.tier))
    with serving(context) as live:
        status, _, body = live.request("GET", f"/api/evidence/compare/0/{a}/0/{b}")
    return status, json.loads(body)


def _source(built: tuple[EvidenceRuns, Path, Path], name: str) -> dict[str, object]:
    made, _, _ = built
    recorded = load_run_config(made.runs / name / "run.json")
    kind = "ablation" if recorded.ablation else "development"
    kind = "reportable" if recorded.reportable else kind
    return {
        "root": 0,
        "name": name,
        "run_id": recorded.run_id,
        "manifest_id": recorded.sha256(),
        "kind": kind,
        "harness_commit": recorded.harness.commit,
        "harness_clean": recorded.harness.clean,
    }


def test_a_matched_pair_is_the_comparison_s_own_answer(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    made, _, _ = built
    status, body = _compare(built, "ev-development", "ev-ablation")
    assert status == 200, body
    expected = compare(made.runs / "ev-development", made.runs / "ev-ablation")
    assert body == {
        "a": _source(built, "ev-development"),
        "b": _source(built, "ev-ablation"),
        "comparison": expected.model_dump(mode="json"),
    }
    # What the ablation varies on purpose is reported, never refused.
    assert {"ablation", "hooks"} <= set(body["comparison"]["differs_in"])


def test_the_baseline_is_the_first_run_named(built: tuple[EvidenceRuns, Path, Path]) -> None:
    status, body = _compare(built, "ev-ablation", "ev-development")
    assert status == 200, body
    assert body["comparison"]["baseline"]["run_id"] == "ev-ablation"
    assert body["comparison"]["candidate"]["run_id"] == "ev-development"


def test_a_run_compared_with_itself_differs_in_nothing(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    status, body = _compare(built, "ev-development", "ev-development")
    assert status == 200, body
    assert body["comparison"]["differs_in"] == []


def test_a_drifted_pair_is_refused_naming_every_drifted_setting_and_no_value(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    made, _, _ = built
    status, body = _compare(built, "ev-development", "ev-drifted")
    assert status == 422, body
    wanted = drift(
        load_run_config(made.runs / "ev-development" / "run.json"),
        load_run_config(made.runs / "ev-drifted" / "run.json"),
    )
    assert wanted == ["models.decomposition", "max_output_tokens"]
    assert body == {
        "error": REFUSED,
        "drifted": wanted,
        "a": _source(built, "ev-development"),
        "b": _source(built, "ev-drifted"),
    }
    text = json.dumps(body)
    assert DRIFTED_MODEL not in text
    assert "32000" not in text
    assert "64000" not in text


def test_a_pair_withholding_different_tiers_is_refused_naming_the_field_alone(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    made, _, _ = built
    status, body = _compare(built, "ev-development", "ev-reportable")
    assert status == 422, body
    assert "held_out_sha256" in body["drifted"]
    text = json.dumps(body)
    leaks = [*CANARIES, *(tier_digest(r) for r in made.tier), *(r.name for r in made.tier)]
    assert [leak for leak in leaks if leak in text] == []
    assert not {"comparison", "held_out", "held_out_canaries"} & set(body)


@pytest.mark.parametrize("side", ["a", "b"])
def test_a_run_whose_configuration_changed_after_it_started_is_refused_naming_that_run(
    built: tuple[EvidenceRuns, Path, Path], side: str
) -> None:
    a, b = ("ev-tampered", "ev-development") if side == "a" else ("ev-development", "ev-tampered")
    status, body = _compare(built, a, b)
    assert status == 422, body
    assert body == {
        "error": "the run's first line does not name the configuration recorded beside it",
        "root": "0",
        "name": "ev-tampered",
        "record": "run.json",
    }


def test_a_run_whose_log_cannot_be_read_is_refused_naming_that_run(
    built: tuple[EvidenceRuns, Path, Path],
) -> None:
    status, body = _compare(built, "ev-development", "ev-unreadable")
    assert status == 422, body
    assert (body["root"], body["name"], body["record"]) == ("0", "ev-unreadable", "events.jsonl")
    assert {"offset", "reason"} <= set(body)


@pytest.mark.parametrize("side", ["a", "b"])
def test_a_run_that_is_not_there_is_not_found(
    built: tuple[EvidenceRuns, Path, Path], side: str
) -> None:
    a, b = ("ev-none", "ev-development") if side == "a" else ("ev-development", "ev-none")
    status, body = _compare(built, a, b)
    assert status == 404, body
    assert body == {"error": "no run of that name under that root", "root": "0", "name": "ev-none"}


def test_no_answer_names_a_path_on_disk(built: tuple[EvidenceRuns, Path, Path]) -> None:
    _, _, base = built
    pairs = [
        ("ev-development", "ev-ablation"),
        ("ev-development", "ev-drifted"),
        ("ev-tampered", "ev-development"),
        ("ev-development", "ev-unreadable"),
    ]
    for a, b in pairs:
        _, body = _compare(built, a, b)
        text = json.dumps(body)
        assert str(base) not in text, (a, b)
        assert os.path.realpath(base) not in text, (a, b)
