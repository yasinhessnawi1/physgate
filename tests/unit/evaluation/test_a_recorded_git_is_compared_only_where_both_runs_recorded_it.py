"""The git binary a run recorded is compared, but only where both runs recorded one.

A run records the git every harness git command ran (its path and its version). Two runs that
recorded different gits are not comparable: ``compare`` names ``git_binary`` as drifted, and a
variance refuses them as repeats of one configuration. A run recorded before git was recorded
holds ``None``, which is nothing measured rather than a different git: ``compare`` does not
count it as drift, and a variance over a set where any run holds it leaves the field out of
every run's comparison.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.observe.compare import compare, drift
from physgate.evaluation.observe.exceptions import CompareRefusedError, VarianceError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.variance import measure_variance
from physgate.orchestrator.git import GitBinary

BRIEF = "Build a robot.\n"
HOMEBREW = GitBinary(path="/opt/homebrew/bin/git", version="2.54.0")
SYSTEM = GitBinary(path="/usr/bin/git", version="2.43.0")


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def _run(tmp_path: Path, repo: Path, run_id: str, git_binary: GitBinary | None) -> Path:
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    overrides = {"brief_sha256": digest, "git_binary": git_binary}
    return fake_run(tmp_path, run_id, repo, overrides=overrides)


def test_two_runs_that_recorded_different_gits_have_drifted(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    base = _run(tmp_path, repo, "base", HOMEBREW)
    cand = _run(tmp_path, repo, "cand", SYSTEM)
    assert drift(read_manifest(base).config, read_manifest(cand).config) == ["git_binary"]
    with pytest.raises(CompareRefusedError) as refusal:
        compare(base, cand)
    assert "git_binary" in refusal.value.context["drifted"].split(",")


def test_a_git_of_another_version_at_the_same_path_has_drifted(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    config = read_manifest(_run(tmp_path, repo, "base", HOMEBREW)).config
    upgraded = config.model_copy(
        update={"git_binary": HOMEBREW.model_copy(update={"version": "2.55.0"})}
    )
    assert drift(config, upgraded) == ["git_binary"]


@pytest.mark.parametrize(("base_git", "cand_git"), [(HOMEBREW, None), (None, SYSTEM), (None, None)])
def test_a_run_that_recorded_no_git_is_not_compared_on_it(
    tmp_path: Path, base_git: GitBinary | None, cand_git: GitBinary | None
) -> None:
    repo = target_repo(tmp_path)
    base = _run(tmp_path, repo, "base", base_git)
    cand = _run(tmp_path, repo, "cand", cand_git)
    assert drift(read_manifest(base).config, read_manifest(cand).config) == []
    assert drift(read_manifest(cand).config, read_manifest(base).config) == []
    compare(base, cand)  # not refused


def test_runs_that_all_recorded_one_git_are_repeats(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    runs = [_run(tmp_path, repo, f"run-{n}", HOMEBREW) for n in range(2)]
    assert measure_variance(runs).n == 2


def test_runs_that_all_recorded_different_gits_are_not_repeats(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    a = _run(tmp_path, repo, "run-a", HOMEBREW)
    b = _run(tmp_path, repo, "run-b", SYSTEM)
    with pytest.raises(VarianceError, match="not repeats") as refusal:
        measure_variance([a, b])
    assert refusal.value.context["changed"] == "git_binary"


@pytest.mark.parametrize("order", ["recorded first", "unrecorded first"])
def test_a_set_where_any_run_recorded_no_git_is_grouped_without_it(
    tmp_path: Path, order: str
) -> None:
    repo = target_repo(tmp_path)
    a = _run(tmp_path, repo, "run-a", HOMEBREW)
    b = _run(tmp_path, repo, "run-b", None)
    c = _run(tmp_path, repo, "run-c", SYSTEM)
    runs = [a, b, c] if order == "recorded first" else [b, a, c]
    assert measure_variance(runs).n == 3
