"""Sizing and integration, the two cross-cutting roles of ARCH-051, as register rows.

Neither is a domain role. Sizing alone writes the quantities that tie domains
together; integration alone may declare a module complete. Neither has a domain of
its own, so neither is a :class:`~physgate.roles.Role` with a ``domain`` bent to fit:
both are :class:`~physgate.roles.CrossCuttingRole`, which names what the role owns
instead. Integration in particular is never given the ``cross`` domain to satisfy a
type.

A role enters the register only once everything its dispatch needs exists: its
always-loaded reading set (ARCH-050's acceptance test) and a paired reviewer whose
rubric is its promoted version (ARCH-061: no automated role is dispatched
unsupervised without one). The reverse does not hold: content existing does not make
a role ready (the module docstring of ``physgate.roles`` says why), so nothing here
asks that every ready role be registered.

Reads the real ``knowledge/`` tree at the repository root, as ARCH-050's own
acceptance test does; ``scripts/check.sh`` runs from there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from physgate import roles
from physgate.knowledge import loader
from physgate.orchestrator import exceptions
from physgate.reviewers.rubric import RubricError, load_rubric

KNOWLEDGE = Path("knowledge")


def _cross_cutting() -> tuple[roles.CrossCuttingRole, ...]:
    return (roles.SIZING, roles.INTEGRATION)


def _missing(role: roles.RegisteredRole, root: Path = KNOWLEDGE) -> list[str]:
    """What ``role`` lacks before it may be dispatched: reading files, then its reviewer."""
    missing = [
        str(path)
        for path in role.always_loaded(root=root)
        if path.is_symlink() or not path.is_file() or not path.read_bytes().strip()
    ]
    try:
        load_rubric(root, role.name)
    except RubricError as exc:
        missing.append(f"reviewer rubric: {exc}")
    return missing


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it ships: the suite's stand-in roles taken out."""
    for name in ("electrical", "mechanical"):
        monkeypatch.delitem(roles.ROLES, name, raising=False)


@pytest.mark.parametrize("name", ["sizing", "integration"])
def test_sizing_and_integration_enter_the_register_only_with_reading_and_a_reviewer(
    name: str, shipped: None
) -> None:
    role = getattr(roles, name.upper())
    missing = _missing(role)
    if role in roles.SHIPPED:
        assert roles.ROLES[name] is role
        assert missing == [], f"{name} is registered without {missing}"
    if missing:
        assert role not in roles.SHIPPED
        assert name not in roles.ROLES
        with pytest.raises(exceptions.RoleNotRegisteredError):
            roles.require_registered([name])


def test_every_shipped_role_has_its_reading_and_a_promoted_reviewer(shipped: None) -> None:
    assert roles.SHIPPED, "the register ships no role"
    for role in roles.SHIPPED:
        assert _missing(role) == [], role.name


def test_a_role_without_a_promoted_reviewer_is_seen_as_not_ready(tmp_path: Path) -> None:
    # The readiness reading above is not vacuous: the reading set alone is not enough.
    for relative in roles.SIZING.always_loaded(root=tmp_path):
        relative.parent.mkdir(parents=True, exist_ok=True)
        relative.write_text("content\n")
    missing = _missing(roles.SIZING, tmp_path)
    assert len(missing) == 1
    assert missing[0].startswith("reviewer rubric")


def test_sizing_owns_the_cross_nodes_and_integration_owns_completion() -> None:
    assert roles.SIZING.name == "sizing"
    assert roles.SIZING.owns == "cross_nodes"
    assert roles.INTEGRATION.name == "integration"
    assert roles.INTEGRATION.owns == "completion"
    for role in _cross_cutting():
        assert role.architecture == "ARCH-051"


def test_a_cross_cutting_role_has_no_domain_and_is_not_a_domain_role() -> None:
    for role in _cross_cutting():
        assert not isinstance(role, roles.Role)
        assert not hasattr(role, "domain")
    with pytest.raises(ValidationError):
        roles.CrossCuttingRole(
            name="integration",
            architecture="ARCH-051",
            owns="completion",
            domain="cross",  # type: ignore[call-arg]
        )


def test_a_cross_cutting_role_owns_one_of_the_two_duties_only() -> None:
    with pytest.raises(ValidationError):
        roles.CrossCuttingRole(
            name="sizing",
            architecture="ARCH-051",
            owns="interfaces",  # type: ignore[arg-type]
        )


def test_the_shared_standards_folder_is_not_a_cross_cutting_role() -> None:
    # ``cross`` is what every role reads, not a role: it has no skill file of its own.
    with pytest.raises(ValidationError):
        roles.CrossCuttingRole(name="cross", architecture="ARCH-051", owns="cross_nodes")


def test_a_cross_cutting_role_is_frozen() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        roles.SIZING.owns = "completion"  # type: ignore[misc]


@pytest.mark.parametrize("name", ["sizing", "integration"])
def test_a_cross_cutting_role_reads_what_the_loader_names_for_it(name: str) -> None:
    role = getattr(roles, name.upper())
    assert role.always_loaded() == loader.always_loaded(name)
    spec = Path(".physgate/specs/s1.md")
    interface = Path(".physgate/interfaces/i1.md")
    assert role.required_reading(spec, interfaces=(interface,)) == loader.required_reading(
        name, spec, interfaces=(interface,)
    )


def test_the_register_refuses_two_roles_of_one_name() -> None:
    twin = roles.Role(name="control", domain="firmware", architecture="ARCH-050")
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((roles.CONTROL, twin))
    assert refused.value.context["role"] == "control"


@pytest.mark.parametrize("duty", ["cross_nodes", "completion"])
def test_the_register_refuses_two_roles_owning_one_duty(duty: roles.CrossCuttingDuty) -> None:
    # Exclusive is exclusive: two writers of the cross quantities, or two roles able to
    # declare completion, would each be one too many.
    second = roles.CrossCuttingRole(name="second", architecture="ARCH-051", owns=duty)
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((roles.CONTROL, roles.SIZING, roles.INTEGRATION, second))
    assert refused.value.context["owns"] == duty
    assert refused.value.context["role"] == "second"


@pytest.mark.parametrize("order", ["domain_first", "cross_cutting_first"])
def test_a_domain_role_and_a_cross_cutting_role_of_one_name_are_refused(order: str) -> None:
    domain = roles.Role(name="balance", domain="mechanical", architecture="ARCH-050")
    cross_cutting = roles.CrossCuttingRole(
        name="balance", architecture="ARCH-051", owns="cross_nodes"
    )
    pair = (domain, cross_cutting) if order == "domain_first" else (cross_cutting, domain)
    with pytest.raises(exceptions.RoleRegisterError, match="already holds a role of this name"):
        roles.register_of(pair)


@pytest.mark.parametrize(
    ("name", "domain"),
    [("integration", "cross"), ("cross", "cross"), ("cross", "mechanical"), ("balance", "cross")],
)
def test_the_register_refuses_a_domain_role_of_the_cross_domain_or_name(
    name: str, domain: str
) -> None:
    # A domain role in the cross domain would be a second writer of the cross quantities
    # by another route, and ``cross`` is the standards every role reads, not a role.
    row = roles.Role(name=name, domain=domain, architecture="ARCH-050")  # type: ignore[arg-type]
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((roles.CONTROL, row))
    assert refused.value.context["role"] == name


@pytest.mark.parametrize(("name", "domain"), [("sizing", "mechanical"), ("integration", "control")])
def test_the_register_refuses_a_domain_role_named_after_a_cross_cutting_role(
    name: str, domain: str
) -> None:
    row = roles.Role(name=name, domain=domain, architecture="ARCH-050")  # type: ignore[arg-type]
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((roles.CONTROL, row))
    assert refused.value.context["role"] == name


@pytest.mark.parametrize(
    ("name", "duty"), [("integration", "cross_nodes"), ("sizing", "completion")]
)
def test_the_register_refuses_a_cross_cutting_row_unlike_the_one_its_name_defines(
    name: str, duty: roles.CrossCuttingDuty
) -> None:
    # Integration given the cross quantities by its own type is integration given
    # ``cross`` all the same.
    row = roles.CrossCuttingRole(name=name, architecture="ARCH-051", owns=duty)
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((row,))
    assert refused.value.context["role"] == name


@pytest.mark.parametrize(
    "row",
    [
        roles.Role(name="design", domain="mechanical", architecture="ARCH-050"),
        roles.CrossCuttingRole(name="design", architecture="ARCH-051", owns="completion"),
    ],
    ids=["domain", "cross_cutting"],
)
def test_the_register_refuses_any_role_named_design(row: roles.RegisteredRole) -> None:
    # ``design`` names the plan's reviewer in a run's reviewer pins; a role of that name
    # would share its pin with the reviewer of the plan.
    with pytest.raises(exceptions.RoleRegisterError) as refused:
        roles.register_of((roles.CONTROL, row))
    assert refused.value.context["role"] == "design"


def test_the_fields_of_each_row_are_in_their_recorded_order() -> None:
    assert list(roles.Role.model_fields) == ["name", "domain", "architecture"]
    assert list(roles.CrossCuttingRole.model_fields) == ["name", "architecture", "owns"]


def test_the_register_holds_both_kinds_of_role_by_name() -> None:
    register = roles.register_of((roles.CONTROL, roles.SIZING, roles.INTEGRATION))
    assert register == {
        "control": roles.CONTROL,
        "sizing": roles.SIZING,
        "integration": roles.INTEGRATION,
    }
