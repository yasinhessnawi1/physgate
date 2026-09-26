"""A run starts only with every input chosen, recorded once, and resumes only under it."""

from __future__ import annotations

from pathlib import Path

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config
from pydantic import ValidationError

from physgate.orchestrator.exceptions import RunConfigError
from physgate.orchestrator.run_config import (
    ModelStrings,
    RunBounds,
    RunConfig,
    load_run_config,
    require_recorded,
    write_run_config,
)


@pytest.mark.parametrize("field", sorted(RunConfig.model_fields))
def test_a_run_without_any_one_input_does_not_start(field: str) -> None:
    complete = make_config().model_dump()
    del complete[field]
    with pytest.raises(ValidationError) as caught:
        RunConfig.model_validate(complete)
    assert caught.value.errors()[0]["loc"] == (field,)
    assert caught.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize("field", sorted(RunBounds.model_fields))
def test_no_bound_has_a_default(field: str) -> None:
    complete = SCRIPTED_BOUNDS.model_dump()
    del complete[field]
    with pytest.raises(ValidationError):
        RunBounds.model_validate(complete)


@pytest.mark.parametrize("alias", ["sonnet", "opus", "haiku", "claude-sonnet", "default", ""])
def test_a_model_alias_is_refused(alias: str) -> None:
    with pytest.raises(ValidationError, match="full model string|at least 1"):
        ModelStrings(decomposition=alias, roles={}, reviewers={})
    with pytest.raises(ValidationError):
        ModelStrings(decomposition="claude-sonnet-5", roles={"control": alias}, reviewers={})


@pytest.mark.parametrize(
    "full",
    [
        "claude-sonnet-5",
        "claude-sonnet-4-5-20250929",
        "claude-opus-5-5",
        "claude-haiku-4-5-20251001",
        "claude-fable-5-1",
    ],
)
def test_a_full_model_string_is_accepted(full: str) -> None:
    assert ModelStrings(decomposition=full, roles={}, reviewers={}).decomposition == full


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gate_mode", "block"),
        ("token_ceiling", 0),
        ("seed", "7"),
        ("target_head", "HEAD"),
        ("brief_sha256", "x"),
    ],
)
def test_a_value_outside_its_domain_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_config(**{field: value})


def test_the_configuration_is_written_once_and_read_back_exactly(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    config = make_config()
    write_run_config(path, config)
    assert path.read_bytes() == config.canonical_bytes()
    assert load_run_config(path) == config
    with pytest.raises(RunConfigError, match="written once"):
        write_run_config(path, make_config(seed=8))
    assert load_run_config(path) == config


def test_a_resume_under_a_different_configuration_is_refused_and_names_the_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.json"
    write_run_config(path, make_config())
    assert require_recorded(path, make_config()) == make_config()
    changed = make_config(
        seed=8, bounds=SCRIPTED_BOUNDS.model_copy(update={"session_max_turns": 21})
    )
    with pytest.raises(RunConfigError) as caught:
        require_recorded(path, changed)
    assert caught.value.context["changed"] == "bounds,seed"


def test_a_missing_or_damaged_configuration_is_a_domain_error(tmp_path: Path) -> None:
    with pytest.raises(RunConfigError, match="no run configuration"):
        load_run_config(tmp_path / "absent.json")
    damaged = tmp_path / "run.json"
    damaged.write_bytes(b"\xff not json")
    with pytest.raises(RunConfigError, match="not valid"):
        load_run_config(damaged)


def test_the_digest_follows_the_recorded_bytes() -> None:
    assert make_config().sha256() == make_config().sha256()
    assert make_config().sha256() != make_config(seed=8).sha256()
