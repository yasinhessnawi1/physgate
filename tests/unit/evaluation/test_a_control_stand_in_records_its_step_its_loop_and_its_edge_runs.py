"""A control session's records: its step response, its loop's frequency response, its edge runs.

Through the real loop, the real change check, real git and the real collection, a stand-in
control session runs a standard-library script under its module. The script simulates a small
stable loop, ``L(s) = K / (s (s + 1) (0.1 s + 1))`` under unity feedback; it is a stand-in, not
the robot. Through the writer it records:

- the nominal step response;
- the loop's frequency response;
- four edge-of-region step responses, one per gain, under one group.

It then reports the phase margin and the step's peak as it reads them off its own records,
with the published extractors, each naming the record it was read off.

What is held: every record is sealed on the session's end line, both linked quantities agree
with their records, the attempt merges, and the review packet both arms are given lists every
record and both checks. A rerun from the recorded configuration reproduces the run exactly,
series seals included. The same through the real binary on a scripted endpoint is held in the
integration tier; a real run waits for real runs to resume.
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import write_fixture
from observe_rig import Reviewer, fake_driver, fake_run, target_repo
from stand_in_control import CONTROL_SCRIPT, RECORD_IDS

# The reviewers' own placeholder rubric, from their test helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reviewers"))
from rubric_fixture import PLACEHOLDER  # noqa: E402

from physgate.evaluation.observe.rerun import rerun
from physgate.orchestrator.events import Merged, ProposalsChecked, SessionEnded, read_events
from physgate.orchestrator.protocols import Artefact
from physgate.reviewers.packet import build_packet, check_parts, joined_parts
from physgate.reviewers.rubric import Rubric
from physgate.series.reader import attempt_records, read_record

BRIEF = "Build two modules.\n"
SEED = 7

EXPECTED = sorted(RECORD_IDS)


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def _drive(**extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"records": SEED, "role": "control", "script": CONTROL_SCRIPT, **extra}


def _run(tmp_path: Path, repo: Path, reviewer: Reviewer) -> Path:
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    return fake_run(
        tmp_path,
        "run-a",
        repo,
        overrides={"brief_sha256": digest},
        **_drive(reviewers={"control": reviewer}),
    )


def test_every_record_is_sealed_both_quantities_agree_and_the_attempt_merges(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    run = _run(tmp_path, repo, Reviewer())
    events = read_events(run / "events.jsonl")
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert len(ended) == 2
    for session in ended:
        assert sorted(r.record_id for r in session.series.records) == EXPECTED
        assert session.series.refused == ()
        entries = attempt_records(events, session.subtask_id, session.attempt)
        groups = {
            e.record.record_id: read_record(e.path(run), e.seal()).group or "" for e in entries
        }
        assert sorted(groups.values()) == ["edge_runs"] * 4 + ["frequency_response", "step"]
    checks = [c for e in events if isinstance(e, ProposalsChecked) for c in e.series_checks]
    assert sorted((c.quantity, c.outcome) for c in checks) == [
        ("phase_margin", "agrees"),
        ("phase_margin", "agrees"),
        ("step_peak", "agrees"),
        ("step_peak", "agrees"),
    ]
    margin = next(c for c in checks if c.quantity == "phase_margin")
    assert margin.read_value is not None
    assert math.isclose(margin.read_value, _exact_phase_margin(2.0), rel_tol=1e-4)
    assert len([e for e in events if isinstance(e, Merged)]) == 2


def _exact_phase_margin(k: float) -> float:
    """The stand-in loop's phase margin, its crossover found by bisection."""
    lo, hi = 0.01, 100.0
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        gain = k / (mid * math.hypot(1.0, mid) * math.hypot(1.0, 0.1 * mid))
        lo, hi = (mid, hi) if gain > 1 else (lo, mid)
    return math.pi / 2 - math.atan(lo) - math.atan(0.1 * lo)


def _artefact(tmp_path: Path) -> Artefact:
    repo = target_repo(tmp_path)
    reviewer = Reviewer()
    _run(tmp_path, repo, reviewer)
    return reviewer.seen[0]


@pytest.mark.parametrize("kind", ["paired", "generalist"])
def test_the_packet_both_review_arms_are_given_lists_every_record_and_both_checks(
    tmp_path: Path, kind: str
) -> None:
    artefact = _artefact(tmp_path)
    assert artefact.series is not None
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    paired = Rubric(
        role="control", text=PLACEHOLDER, sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest()
    )
    # The arm differs only in its kind here: what the listing holds does not depend on it.
    rubric = paired.model_copy(update={"kind": kind})
    repo = Path(artefact.repository) if artefact.repository else tmp_path / "target"
    assert artefact.base_commit is not None
    packet = build_packet(
        tmp_path / "reviews" / "r0",
        artefact,
        repo=repo,
        base_commit=artefact.base_commit,
        rubric=rubric,
        library=library,
        spec=None,
    )
    text = joined_parts(Path(packet.read_root), packet.series_parts).decode()
    for record_id in EXPECTED:
        assert f"## {record_id}\n" in text
    assert text.count("- group: edge_runs;") == 4
    assert "Quantities checked: 2." in text
    assert text.count("| agrees |") == 2
    for part in packet.series_parts:
        assert str(Path(packet.read_root) / part.name) in packet.required_reading
    check_parts(packet, repo=repo, base_commit=artefact.base_commit)


def test_a_rerun_from_the_recorded_configuration_reproduces_the_run_series_included(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    run = _run(tmp_path, repo, Reviewer())
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    outcome = rerun(
        run,
        brief=brief,
        run_id="run-r",
        run_dir=tmp_path / "elsewhere" / "run-r",
        target=repo,
        install=tmp_path / "install",
        review_root=tmp_path / "review-scratch",
        driver=fake_driver(tmp_path / "elsewhere", repo, **_drive()),
    )
    assert outcome.level == "exact" and outcome.reproduced and outcome.first is None, outcome
