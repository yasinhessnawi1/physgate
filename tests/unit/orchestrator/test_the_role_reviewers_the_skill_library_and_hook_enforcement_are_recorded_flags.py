"""Role reviewers, the skill library and hook enforcement are flags of the register.

ARCH-140 makes each a switch a run is measured with or without: ``reviewers`` is ``paired``,
``generalist`` or ``off``; ``skills`` and ``hooks`` are ``on`` or ``off``. Each is a required
parameter of a new run with no default, recorded in the run's configuration and never read from
the environment. A run recorded before a switch existed ran with the component, and reads so
(``paired``, ``on``, ``on``), with exactly the digest its first line carries: a run at those
values leaves the fields out of its recorded form.

The register names every value. A value whose switch is not built yet is refused at the run's
configuration, by a rule that names it, so no run records an arm nothing implements.

The escalation backend is a flag of the same register (ARCH-132): its values are the backend
register's names.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, make_config

import physgate.flags as flags
from physgate.orchestrator import escalation
from physgate.orchestrator.events import RunStarted
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.run_config import (
    BUILT,
    RunConfig,
    load_run_config,
    write_run_config,
)

#: Each new flag: its register entry, its type, its values, and what a run before it reads as.
NEW: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "reviewers": ("REVIEWERS", "Reviewers", ("paired", "generalist", "off"), "paired"),
    "skills": ("SKILLS", "Skills", ("on", "off"), "on"),
    "hooks": ("HOOKS", "Hooks", ("on", "off"), "on"),
}
BEFORE: dict[str, Any] = {name: row[3] for name, row in NEW.items()} | {"ablation": False}
#: Every value other than what an earlier run ran with, built or not.
DIFFERS = [(name, value) for name, row in NEW.items() for value in row[2] if value != row[3]]
#: The values no run takes yet, because nothing implements them.
NOT_BUILT = [(name, value) for name, value in DIFFERS if value not in BUILT[name]]

#: The digest of the helper's configuration on a clean checkout, taken before the flags existed.
DIGEST_BEFORE_THE_FLAGS = "c1f3ab6192f60f8c1a81549b0386a23895b0e3984fe596557e3d7583befdb6d3"


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**(BEFORE | fields)))


@pytest.mark.parametrize("name", NEW)
def test_the_register_names_the_flag_and_its_type_is_exactly_its_values(name: str) -> None:
    entry, kind, values, before = NEW[name]
    flag = getattr(flags, entry, None)
    assert flag is not None, f"the register has no {name} flag"
    assert flag.name == name
    assert flag.values == values
    assert flag.architecture == "ARCH-140"
    assert flag in flags.REGISTER
    assert typing.get_args(getattr(flags, kind, None)) == values
    assert "every run recorded before the switch existed reads as this" in flag.meanings[before]


@pytest.mark.parametrize("name", NEW)
def test_the_flag_is_a_required_field_with_no_default(name: str) -> None:
    field = RunConfig.model_fields.get(name)
    assert field is not None, f"the run's configuration has no {name}"
    assert field.is_required(), f"{name} has a default"
    assert typing.get_args(field.annotation) == NEW[name][2]


@pytest.mark.parametrize("name", BEFORE)
def test_a_run_configuration_without_the_key_is_refused(name: str) -> None:
    refused = outcome_of(lambda: RunConfig.model_validate({}))
    missing = {tuple(e["loc"]) for e in refused.errors() if e["type"] == "missing"}
    assert (name,) in missing


@pytest.mark.parametrize("name", NEW)
def test_a_value_the_register_does_not_name_is_refused(name: str) -> None:
    refused = outcome_of(lambda: RunConfig.model_validate({name: "sometimes"}))
    assert any(e["loc"] == (name,) and e["type"] == "literal_error" for e in refused.errors())


def test_a_key_the_run_configuration_does_not_know_is_refused() -> None:
    unknown = _config(research="on")
    assert not isinstance(unknown, RunConfig), unknown
    assert any(
        e["loc"] == ("research",) and e["type"] == "extra_forbidden" for e in unknown.errors()
    )
    assert isinstance(_config(), RunConfig)


def test_a_run_at_what_every_earlier_run_ran_with_keeps_its_recorded_bytes() -> None:
    config = _config(harness=CLEAN_HARNESS)
    assert isinstance(config, RunConfig), config
    assert not set(BEFORE) & set(json.loads(config.canonical_bytes()))
    assert config.sha256() == DIGEST_BEFORE_THE_FLAGS


def test_a_run_recorded_before_the_flags_reads_as_it_ran_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    config = _config(harness=CLEAN_HARNESS)
    assert isinstance(config, RunConfig), config
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert not set(BEFORE) & set(json.loads(path.read_bytes()))  # what an earlier run wrote
    loaded = outcome_of(lambda: load_run_config(path))
    assert isinstance(loaded, RunConfig), loaded
    assert {name: getattr(loaded, name, None) for name in BEFORE} == BEFORE
    assert loaded.sha256() == DIGEST_BEFORE_THE_FLAGS


@pytest.mark.parametrize("ablation", [False, True])
@pytest.mark.parametrize(("name", "value"), NOT_BUILT)
def test_a_value_whose_switch_is_not_built_is_refused_by_a_rule_that_names_it(
    name: str, value: str, ablation: bool
) -> None:
    refused = _config(**{name: value}, ablation=ablation, harness=CLEAN_HARNESS)
    assert not isinstance(refused, RunConfig), refused
    assert f"{name}: {value} is not built" in str(refused)
    # The same run at the value every run has had is a run.
    assert isinstance(_config(ablation=ablation, harness=CLEAN_HARNESS), RunConfig)


def _line(**said: Any) -> Any:  # noqa: ANN401 - the line, or why there is none
    return outcome_of(
        lambda: RunStarted(
            seq=0,
            ts="2026-11-12T00:00:00.000000Z",
            run_id="run-1",
            gate_mode="on",
            config_sha256="0" * 64,
            **said,
        )
    )


@pytest.mark.parametrize(("name", "value"), DIFFERS)
def test_the_run_s_first_line_names_a_flag_only_where_it_differs(name: str, value: str) -> None:
    plain = _line()
    assert isinstance(plain, RunStarted), plain
    assert name in RunStarted.model_fields
    assert name not in json.loads(plain.model_dump_json())  # an earlier line keeps its bytes
    named = _line(**{name: value})
    assert isinstance(named, RunStarted), named
    assert json.loads(named.model_dump_json())[name] == value
    assert RunStarted.model_validate_json(named.model_dump_json()) == named
    # What every run before the flag ran with is said by leaving it out, never by naming it.
    assert not isinstance(_line(**{name: NEW[name][3]}), RunStarted)


def _first_line(run_dir: Path, config: RunConfig) -> dict[str, Any]:
    record = RunRecord(config, run_dir)
    record.start([])
    record.close()
    first: dict[str, Any] = json.loads((run_dir / "events.jsonl").read_text().splitlines()[0])
    return first


def test_a_run_s_first_line_is_written_from_its_configuration(tmp_path: Path) -> None:
    config = _config()
    assert isinstance(config, RunConfig), config
    assert not set(NEW) & set(_first_line(tmp_path / "plain", config))
    for name, value in DIFFERS:
        # Built or not, the line is held to whatever the configuration says.
        differs = config.model_copy(update={name: value})
        first = _first_line(tmp_path / f"{name}-{value}", differs)
        assert {key: first.get(key) for key in NEW} == {
            key: value if key == name else None for key in NEW
        }


def test_the_escalation_backend_is_a_flag_whose_values_are_the_backend_register_s() -> None:
    flag = getattr(flags, "ESCALATION_BACKEND", None)
    assert flag is not None, "the register has no escalation_backend flag"
    assert flag.name == "escalation_backend"
    assert flag.architecture == "ARCH-132"
    assert flag in flags.REGISTER
    rows = escalation.REGISTER.rows
    assert flag.values == tuple(row.name for row in rows)
    assert typing.get_args(getattr(flags, "EscalationBackend", None)) == flag.values
    for row in rows:
        assert row.status in flag.meanings[row.name]
    # The run's configuration holds a name to the backend register itself, and takes only a
    # backend that ships: of the flag's values, exactly those.
    taken = [v for v in flag.values if isinstance(_config(escalation_backend=v), RunConfig)]
    assert taken == [row.name for row in rows if row.status == "ships"]
