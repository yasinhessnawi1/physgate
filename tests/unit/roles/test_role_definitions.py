"""``physgate.roles``: the control and firmware rows of ARCH-050, made executable.

Reads the real ``knowledge/`` tree at the repository root (not a fixture copy),
because this is ARCH-050's own acceptance test: "each role's skill file exists
and is non-empty before that role is ever dispatched." ``scripts/check.sh``
always runs from the repository root, which is this test's working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.roles import CONTROL, FIRMWARE, ROLES, Role


def test_control_is_the_control_domain_row() -> None:
    assert CONTROL.name == "control"
    assert CONTROL.domain == "control"
    assert CONTROL.architecture == "ARCH-050"


def test_firmware_is_the_firmware_domain_row() -> None:
    assert FIRMWARE.name == "firmware"
    assert FIRMWARE.domain == "firmware"
    assert FIRMWARE.architecture == "ARCH-050"


def test_the_register_holds_exactly_these_two_roles_so_far() -> None:
    assert ROLES == {"control": CONTROL, "firmware": FIRMWARE}


def test_a_role_is_frozen() -> None:
    with pytest.raises(Exception, match="frozen|immutable"):
        CONTROL.name = "other"  # type: ignore[misc]


@pytest.mark.parametrize("role", [CONTROL, FIRMWARE])
def test_always_loaded_matches_the_knowledge_loader_directly(role: Role) -> None:
    from physgate.knowledge import loader

    assert role.always_loaded() == loader.always_loaded(role.name)


@pytest.mark.parametrize("role", [CONTROL, FIRMWARE])
def test_required_reading_adds_the_module_spec(role: Role) -> None:
    spec = Path(".physgate/specs/s1.md")
    reading = role.required_reading(spec)
    assert spec in reading
    assert set(role.always_loaded()).issubset(reading)


@pytest.mark.parametrize("role", [CONTROL, FIRMWARE])
def test_arch_050_acceptance_every_always_loaded_file_exists_and_is_non_empty(
    role: Role,
) -> None:
    """ARCH-050's acceptance test: a role's standards and skill file are real before dispatch."""
    for relative in role.always_loaded():
        path = Path(relative)
        assert path.exists(), f"{path} does not exist; {role.name} cannot be dispatched"
        assert path.stat().st_size > 0, f"{path} is empty; {role.name} cannot be dispatched"
