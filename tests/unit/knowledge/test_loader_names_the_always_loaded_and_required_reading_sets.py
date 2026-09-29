"""``loader.always_loaded``/``required_reading`` (ARCH-020, ARCH-023): pure path arithmetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.knowledge import loader
from physgate.knowledge.exceptions import RoleNameError


def test_always_loaded_is_cross_then_the_roles_own_standards_and_skill() -> None:
    assert loader.always_loaded("control") == (
        Path("knowledge/cross/standards.md"),
        Path("knowledge/control/standards.md"),
        Path("knowledge/control/skill.md"),
    )
    assert loader.always_loaded("firmware") == (
        Path("knowledge/cross/standards.md"),
        Path("knowledge/firmware/standards.md"),
        Path("knowledge/firmware/skill.md"),
    )


def test_the_cross_role_reads_only_its_own_one_file() -> None:
    assert loader.always_loaded("cross") == (Path("knowledge/cross/standards.md"),)


def test_a_role_whose_domain_has_no_curated_content_still_gets_a_named_path() -> None:
    # ARCH-101's own acceptance test refuses dispatch of a role with a missing
    # standards file; naming a path that does not exist yet is correct here, not
    # a bug the reading hook needs this module's help to catch.
    assert loader.always_loaded("mechanical") == (
        Path("knowledge/cross/standards.md"),
        Path("knowledge/mechanical/standards.md"),
        Path("knowledge/mechanical/skill.md"),
    )


@pytest.mark.parametrize(
    "role", ["Control", "control/x", "../control", "", " control", "control ", "1control"]
)
def test_an_unsafe_role_name_is_refused_before_a_path_is_built(role: str) -> None:
    with pytest.raises(RoleNameError, match="safe"):
        loader.always_loaded(role)
    with pytest.raises(RoleNameError):
        loader.required_reading(role, Path("spec.md"))


def test_required_reading_adds_the_module_spec_to_always_loaded() -> None:
    reading = loader.required_reading("control", Path(".physgate/specs/s1.md"))
    assert set(reading) == {
        Path("knowledge/cross/standards.md"),
        Path("knowledge/control/standards.md"),
        Path("knowledge/control/skill.md"),
        Path(".physgate/specs/s1.md"),
    }
    assert reading == tuple(sorted(reading))  # deterministic, so the hook's list is stable


def test_required_reading_adds_interface_contracts_and_deduplicates() -> None:
    reading = loader.required_reading(
        "control",
        Path(".physgate/specs/s1.md"),
        interfaces=(Path("interfaces/a.md"), Path("knowledge/cross/standards.md")),
    )
    assert reading.count(Path("knowledge/cross/standards.md")) == 1
    assert Path("interfaces/a.md") in reading


def test_a_custom_root_is_honoured_and_no_filesystem_is_touched(tmp_path: Path) -> None:
    # A path under a root that does not exist on disk: loader.py does no I/O of
    # its own, so this must not raise.
    root = tmp_path / "does-not-exist" / "knowledge"
    assert loader.always_loaded("control", root=root) == (
        root / "cross" / "standards.md",
        root / "control" / "standards.md",
        root / "control" / "skill.md",
    )
