"""The flag register: every ablation switch is declared, required, and never defaulted."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from physgate.flags import GATE_MODE, REGISTER, Flag, GateMode
from physgate.orchestrator.common import GateMode as OrchestratorGateMode
from physgate.orchestrator.run_config import RunConfig

ROOT = Path(__file__).resolve().parents[2]


def test_the_register_is_not_empty_and_names_the_gate_mode() -> None:
    assert [flag.name for flag in REGISTER] == ["gate_mode"]
    assert GATE_MODE.architecture == "ARCH-140"


def test_the_gate_mode_type_is_exactly_the_registered_values() -> None:
    assert typing.get_args(GateMode) == GATE_MODE.values
    assert OrchestratorGateMode is GateMode


@pytest.mark.parametrize("flag", REGISTER, ids=lambda f: f.name)
def test_every_flag_is_a_required_field_of_the_run_configuration_with_no_default(
    flag: Flag,
) -> None:
    field = RunConfig.model_fields[flag.name]
    assert field.is_required(), f"{flag.name} has a default"
    assert typing.get_args(field.annotation) == flag.values


@pytest.mark.parametrize("flag", REGISTER, ids=lambda f: f.name)
def test_a_run_configuration_without_the_flag_is_refused(flag: Flag) -> None:
    with pytest.raises(ValidationError) as caught:
        RunConfig.model_validate({})
    missing = {tuple(e["loc"]) for e in caught.value.errors() if e["type"] == "missing"}
    assert (flag.name,) in missing


def test_a_value_the_register_does_not_name_is_refused_by_the_run_configuration() -> None:
    with pytest.raises(ValidationError) as caught:
        RunConfig.model_validate({"gate_mode": "block"})
    assert any(e["loc"] == ("gate_mode",) for e in caught.value.errors())


@pytest.mark.parametrize("flag", REGISTER, ids=lambda f: f.name)
def test_no_flag_is_read_from_the_environment(flag: Flag) -> None:
    source = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    example = (ROOT / ".env.example").read_text()
    for spelling in (flag.name.upper(), f"PHYSGATE_{flag.name.upper()}"):
        assert f'environ.get("{spelling}"' not in source
        assert f'environ["{spelling}"' not in source
        assert f"\n{spelling}=" not in example


def test_a_flag_needs_a_meaning_for_every_value_and_nothing_else() -> None:
    with pytest.raises(ValidationError):
        Flag(name="x", values=("a", "b"), meanings={"a": "one"}, architecture="ARCH-140")
    with pytest.raises(ValidationError):
        Flag(
            name="x",
            values=("a", "b"),
            meanings={"a": "one", "b": "two", "c": "three"},
            architecture="ARCH-140",
        )
    with pytest.raises(ValidationError):
        Flag(name="x", values=("a",), meanings={"a": "one"}, architecture="ARCH-140")
