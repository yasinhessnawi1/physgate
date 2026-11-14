"""A binary's request defaults are recorded per version and model; a pair not listed is refused.

What the binary sends that no run setting pins (the thinking field, context management, the
beta flags) was measured to depend on the request's model as well as on the binary's version:
on 2.1.301 a claude-sonnet-5 decomposition request leaves out two beta flags that a
claude-opus-5-5 one carries. So the table is keyed by both, each entry names the pair it was
measured on, and a run's manifest carries one entry per model its decomposition call and its
role sessions ran on. A run on a pair no one measured has no manifest: its defaults would be a
guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.observe.exceptions import ManifestError
from physgate.evaluation.observe.manifest import BINARY_DEFAULTS, read_manifest
from physgate.orchestrator.run_config import ModelStrings

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5"


def _models(decomposition: str, role: str, reviewer: str) -> ModelStrings:
    return ModelStrings(
        decomposition=decomposition, roles={"electrical": role}, reviewers={"electrical": reviewer}
    )


def _run(tmp_path: Path, version: str, models: ModelStrings) -> Path:
    overrides = {"claude_version": version, "models": models}
    return fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides=overrides)


def test_every_entry_is_keyed_by_the_version_and_model_it_was_measured_on() -> None:
    for key, entry in BINARY_DEFAULTS.items():
        assert key == (entry.claude_version, getattr(entry, "model", None)), key


def test_the_entries_are_the_pairs_measured() -> None:
    assert sorted(BINARY_DEFAULTS) == [
        ("2.1.272", SONNET),  # 2.1.272 refuses claude-opus-5-5; measured on the pins of the day
        ("2.1.283", OPUS),
        ("2.1.301", OPUS),
        ("2.1.322", OPUS),
    ]


def test_a_run_on_a_listed_pair_carries_that_pair_s_entry(tmp_path: Path) -> None:
    manifest = read_manifest(_run(tmp_path, "2.1.301", _models(OPUS, OPUS, SONNET)))
    assert manifest.binary_defaults == (BINARY_DEFAULTS.get(("2.1.301", OPUS)),)


def test_a_run_on_a_version_s_unmeasured_model_is_refused_and_named(tmp_path: Path) -> None:
    run = _run(tmp_path, "2.1.301", _models(SONNET, SONNET, OPUS))
    with pytest.raises(ManifestError, match="model") as refused:
        read_manifest(run)
    assert refused.value.context.get("model") == SONNET
    assert refused.value.context.get("claude_version") == "2.1.301"


def test_a_run_whose_role_sessions_ran_on_an_unmeasured_model_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, "2.1.301", _models(OPUS, SONNET, OPUS))
    with pytest.raises(ManifestError, match="model") as refused:
        read_manifest(run)
    assert refused.value.context.get("model") == SONNET


def test_a_run_whose_decomposition_alone_ran_on_an_unmeasured_model_is_refused(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, "2.1.301", _models(SONNET, OPUS, "claude-haiku-5-5"))
    with pytest.raises(ManifestError, match="model") as refused:
        read_manifest(run)
    assert refused.value.context.get("model") == SONNET


def test_the_reviewers_model_is_not_one_the_entries_describe(tmp_path: Path) -> None:
    # The entries hold the decomposition call's and the role sessions' requests; a reviewer's
    # request is not among them, so its model alone neither adds an entry nor refuses one.
    manifest = read_manifest(_run(tmp_path, "2.1.301", _models(OPUS, OPUS, SONNET)))
    assert [getattr(d, "model", None) for d in manifest.binary_defaults] == [OPUS]
