"""Ordering and merge-decision variance, measured on repeated fake-session runs.

Criterion: N runs of one brief and seed on the fake session give both numbers
at exactly zero, which is the deterministic binding's baseline; a set with one
changed decision gives the value worked out by hand; every report names each
run's manifest id and n. Runs of different configurations are refused.
"""

from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path

import pytest
from observe_rig import Gate, fake_driver, fake_run, target_repo

from physgate.evaluation.observe.exceptions import VarianceError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.variance import measure_variance, repeat_run

BRIEF = "Build two modules.\n"


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def recorded(tmp_path: Path, repo: Path, run_id: str, **kwargs: object) -> Path:
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    overrides = {"brief_sha256": digest, **kwargs.pop("overrides", {})}  # type: ignore[dict-item]
    return fake_run(tmp_path, run_id, repo, overrides=overrides, **kwargs)


def test_five_repeats_of_one_fake_run_vary_by_exactly_zero(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    run = recorded(tmp_path, repo, "run-a")
    runs_dir = tmp_path / "repeats"
    report = repeat_run(
        run,
        n=5,
        brief=brief,
        target=repo,
        install=tmp_path / "install",
        runs_dir=runs_dir,
        driver=fake_driver(runs_dir, repo),
    )
    assert report.n == 5
    assert (report.ordering_variance, report.merge_decision_variance) == ("0", "0")
    assert (report.ordering_variance_value, report.merge_decision_variance_value) == (0.0, 0.0)
    assert (report.distinct_orderings, report.distinct_decisions) == (1, 1)
    assert [r.run_id for r in report.runs] == ["run-a", *(f"run-a-repeat-{k}" for k in range(1, 5))]
    assert report.runs[0].manifest_id == read_manifest(run).manifest_id
    assert len({r.manifest_id for r in report.runs}) == 5
    assert report.runs[0].dispatch == (("s1-af41ca", 1), ("s2-5e2ad0", 1))
    assert report.runs[0].ends == {"s1-af41ca/1": "merged", "s2-5e2ad0/1": "merged"}


def test_one_run_of_three_with_a_rejected_attempt_gives_the_hand_worked_values(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    a, b = recorded(tmp_path, repo, "run-a"), recorded(tmp_path, repo, "run-b")
    c = recorded(tmp_path, repo, "run-c", gate=Gate(fail_on={1}))
    report = measure_variance([a, b, c])
    assert report.runs[2].dispatch == (("s1-af41ca", 1), ("s1-af41ca", 2), ("s2-5e2ad0", 1))
    # Ordering: one insertion over 3, in two of three pairs: (0 + 1/3 + 1/3) / 3.
    assert Fraction(report.ordering_variance or "x") == Fraction(2, 9)
    # Decisions: s1/1 differs and s1/2 only one ran, of 3 attempts, in two pairs.
    assert Fraction(report.merge_decision_variance or "x") == Fraction(4, 9)
    assert report.merge_decision_variance_value == pytest.approx(4 / 9)
    assert (report.distinct_orderings, report.distinct_decisions) == (2, 2)


def test_one_run_has_a_count_and_no_variance(tmp_path: Path) -> None:
    run = recorded(tmp_path, target_repo(tmp_path), "run-a")
    report = measure_variance([run])
    assert report.n == 1 and report.ordering_variance is None
    assert report.merge_decision_variance_value is None


def test_runs_of_different_configurations_are_refused_and_the_field_named(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    a = recorded(tmp_path, repo, "run-a")
    b = recorded(tmp_path, repo, "run-b", overrides={"seed": 2})
    with pytest.raises(VarianceError, match="not repeats") as refusal:
        measure_variance([a, b])
    assert refusal.value.context["changed"] == "seed"
    c = recorded(tmp_path, repo, "run-c", overrides={"gate_mode": "observe"})
    with pytest.raises(VarianceError) as refusal:
        measure_variance([a, c])
    assert refusal.value.context["changed"] == "gate_mode"


def test_a_run_given_twice_or_no_run_at_all_is_refused(tmp_path: Path) -> None:
    run = recorded(tmp_path, target_repo(tmp_path), "run-a")
    with pytest.raises(VarianceError, match="twice"):
        measure_variance([run, run])
    with pytest.raises(VarianceError, match="at least one"):
        measure_variance([])


def test_repeating_a_run_fewer_than_twice_is_refused(tmp_path: Path) -> None:
    run = recorded(tmp_path, target_repo(tmp_path), "run-a")
    with pytest.raises(VarianceError, match="at least two"):
        repeat_run(run, n=1, brief=tmp_path, target=tmp_path, install=tmp_path, runs_dir=tmp_path)
