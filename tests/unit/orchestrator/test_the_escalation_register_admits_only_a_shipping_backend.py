"""A backend enters by name, with a status and an entry condition, and only ``rules`` ships.

ARCH-132: a binding enters only through the register, and a row whose experiment has
not passed cannot be enabled. So the register refuses a name it has no row for, a row
cannot exist without a status and an entry condition, and only a row that ships, with
an implementation, can be bound.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from physgate.orchestrator.escalation import (
    IMPLEMENTATIONS,
    REGISTER,
    BackendRow,
    EscalationInterface,
    Register,
    RulesBackend,
    bind,
)
from physgate.orchestrator.exceptions import EscalationBackendError

ROW: dict[str, Any] = {
    "name": "candidate",
    "status": "parked",
    "entry_condition": "a pre-registered experiment's pass",
    "evidence": ("R-XX-01",),
    "version": None,
}


def test_rules_is_the_only_row_that_ships_and_the_only_implementation() -> None:
    assert [row.name for row in REGISTER.rows if row.status == "ships"] == ["rules"]
    assert set(IMPLEMENTATIONS) == {"rules"}
    assert {row.name: row.status for row in REGISTER.rows} == {
        "rules": "ships",
        "llm": "off",
        "tsetlin": "parked",
        "laya": "parked",
    }


def test_rules_binds() -> None:
    assert bind("rules").backend_id == "rules"


@pytest.mark.parametrize("name", ["", "Rules", "rule", "learned", "rules "])
def test_a_name_with_no_row_is_refused(name: str) -> None:
    with pytest.raises(EscalationBackendError) as caught:
        bind(name)
    assert caught.value.context["backend"] == name


@pytest.mark.parametrize("name", ["llm", "tsetlin", "laya"])
def test_a_row_that_does_not_ship_is_refused_even_with_an_implementation(name: str) -> None:
    with pytest.raises(EscalationBackendError) as caught:
        bind(name, implementations={name: RulesBackend})
    assert caught.value.context["status"] == REGISTER.row(name).status


@pytest.mark.parametrize("missing", ["status", "entry_condition"])
def test_a_row_without_a_status_or_an_entry_condition_cannot_exist(missing: str) -> None:
    with pytest.raises(ValidationError):
        BackendRow.model_validate({k: v for k, v in ROW.items() if k != missing})
    with pytest.raises(ValidationError):
        BackendRow.model_validate({**ROW, missing: ""})


def test_a_status_the_register_does_not_name_is_refused() -> None:
    with pytest.raises(ValidationError):
        BackendRow.model_validate({**ROW, "status": "contingent"})


def test_a_row_that_ships_names_the_version_a_run_records() -> None:
    with pytest.raises(ValidationError):
        BackendRow.model_validate({**ROW, "status": "ships", "version": None})


def test_a_name_registered_twice_is_refused() -> None:
    row = BackendRow.model_validate(ROW)
    with pytest.raises(ValidationError):
        Register(rows=(row, row))


def test_a_shipping_row_with_nothing_to_build_it_is_refused() -> None:
    ships = BackendRow.model_validate({**ROW, "status": "ships", "version": "candidate/1"})
    register = Register(rows=(ships,))
    with pytest.raises(EscalationBackendError):
        bind("candidate", register=register, implementations={})
    assert bind("candidate", register=register, implementations={"candidate": RulesBackend})


def test_every_parked_row_cites_the_experiments_it_rests_on() -> None:
    for row in REGISTER.rows:
        if row.status == "parked":
            assert row.evidence
            assert all(e.startswith("R-") for e in row.evidence)


@pytest.mark.parametrize("status", ["off", "parked"])
def test_a_built_and_versioned_row_is_still_refused_until_it_ships(status: str) -> None:
    # Every row that does not ship in the register today has no version, and a missing
    # version is refused on its own; a backend that is built but has not passed its
    # experiment would have both, so only the status can refuse it here.
    built = BackendRow.model_validate({**ROW, "status": status, "version": "candidate/1"})
    register = Register(rows=(built,))
    with pytest.raises(EscalationBackendError) as caught:
        bind("candidate", register=register, implementations={"candidate": RulesBackend})
    assert caught.value.context["status"] == status
    with pytest.raises(EscalationBackendError):
        EscalationInterface(RulesBackend(), built)
