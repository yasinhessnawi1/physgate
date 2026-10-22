"""A node of the cross domain is written by the role that owns the cross nodes, and by no other.

The quantities that tie domains together (a motor's stall current, which the
electrical, control and mechanical roles all depend on) live on nodes of the
``cross`` domain. ARCH-051 gives them one writer: the role the register names as
owning the cross nodes. The hook refuses everything else:

- a domain role's proposal for a cross node, new or by turning its own node cross;
- the owner's proposal for a node of a domain: the owner of the cross nodes writes
  no domain node;
- a cross node while no registered role owns the cross nodes: nobody may write it;
- a new interface node from any session. Interface nodes are written from the plan
  when the task is decomposed. A session that could create one could write a shared
  quantity on a node of its own that the cross rule exempts.

The owner is looked up in the register by what it owns, never by its name, and
the lookup counts the owners itself: the register refuses a second owner when it
is built, but it is a mapping that anything in the process can change afterwards.

Both rules come after the kind rule, so a cross write that is also a kind change
is refused as a kind change, the reason the earlier rule gives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hook_helpers import event, make_store, node, write_config

from physgate import roles
from physgate.hooks import graph
from physgate.hooks.config import HookInput, SessionConfig
from physgate.orchestrator.exceptions import DutyUnownedError, RoleRegisterError
from physgate.roles import CrossCuttingRole
from physgate.state.protocol import REJECT_INTERFACE_IMMUTABLE, REJECT_MISSING_UNIT

INTERFACE = "iface.control.p01"
#: A second owner of the cross nodes, for a register patched past its own check.
BALLAST = CrossCuttingRole(name="ballast", architecture="ARCH-051", owns="cross_nodes")


def _session(tmp_path: Path, role: str) -> SessionConfig:
    store = tmp_path / "store"
    if not store.exists():
        make_store(
            store,
            node("control.loop", "control"),
            node("sizing.motor_left", "sizing"),
            node(INTERFACE, "control", kind="interface", domain="cross", quantities={}),
        )
    home = tmp_path / role
    home.mkdir(exist_ok=True)
    _, _, cfg = write_config(home, role=role, store_root=str(store))
    return cfg


def _write(config: SessionConfig, payload: dict[str, object]) -> str:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / f"{payload['id']}.json"
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(payload)},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.fixture
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships: the stand-ins' way, written directly."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


# --- a domain role and the cross nodes ------------------------------------------------


#: Every kind of node but an interface, which the cross rule leaves to the rules that fix it.
NON_INTERFACE_KINDS = ("component", "module", "requirement")


@pytest.mark.parametrize("kind", NON_INTERFACE_KINDS)
@pytest.mark.parametrize("register", ["sizing registered", "as shipped"])
def test_a_domain_roles_proposal_to_a_cross_node_is_refused_at_the_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, register: str, kind: str
) -> None:
    if register == "sizing registered":
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    config = _session(tmp_path, "control")
    told = _write(config, node("control.motor_current", "control", domain="cross", kind=kind))
    assert told != "allow"
    assert graph.CROSS_NODE in told and "control.motor_current" in told


@pytest.mark.usefixtures("sizing_registered")
def test_a_domain_role_cannot_turn_its_own_node_cross(tmp_path: Path) -> None:
    config = _session(tmp_path, "control")
    told = _write(config, node("control.loop", "control", domain="cross"))
    assert told != "allow"
    assert graph.CROSS_NODE in told and "only the sizing role writes" in told


@pytest.mark.usefixtures("sizing_registered")
def test_a_domain_roles_own_domain_node_still_lands(tmp_path: Path) -> None:
    config = _session(tmp_path, "control")
    assert _write(config, node("control.gain", "control")) == "allow"
    assert _write(config, node("control.loop", "control", constrains=["x.y"])) == "allow"


# --- the owner of the cross nodes ---------------------------------------------------------


@pytest.mark.usefixtures("sizing_registered")
def test_sizings_write_to_a_cross_node_lands(tmp_path: Path) -> None:
    config = _session(tmp_path, "sizing")
    assert _write(config, node("sizing.motor_right", "sizing")) == "allow"
    assert _write(config, node("sizing.motor_left", "sizing", constrains=["x.y"])) == "allow"


@pytest.mark.usefixtures("sizing_registered")
@pytest.mark.parametrize("domain", ["mechanical", "electrical", "control", "firmware"])
def test_sizing_cannot_write_a_domain_node(tmp_path: Path, domain: str) -> None:
    config = _session(tmp_path, "sizing")
    told = _write(config, node("sizing.bracket", "sizing", domain=domain))
    assert told != "allow"
    assert graph.CROSS_NODE in told and "writes no node of a domain" in told


@pytest.mark.usefixtures("sizing_registered")
def test_sizing_cannot_turn_its_own_cross_node_into_a_domain_node(tmp_path: Path) -> None:
    config = _session(tmp_path, "sizing")
    told = _write(config, node("sizing.motor_left", "sizing", domain="electrical"))
    assert told != "allow"
    assert graph.CROSS_NODE in told


def test_the_owner_is_found_in_the_register_by_what_it_owns_not_by_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A register whose owner of the cross nodes is not called sizing: the rule follows
    # the register, and the name sizing then carries nothing.
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
    assert roles.owner_of("cross_nodes") == "ballast"
    assert _write(_session(tmp_path, "ballast"), node("ballast.mass", "ballast")) == "allow"
    told = _write(_session(tmp_path, "sizing"), node("sizing.motor_right", "sizing"))
    assert graph.CROSS_NODE in told and "only the ballast role writes" in told


# --- an owner the register does not settle ------------------------------------------------


def test_a_cross_node_with_no_registered_owner_is_refused(tmp_path: Path) -> None:
    # As shipped, no registered role owns the cross nodes: a cross node then has no
    # writer at all, and the hook fails closed for every session, sizing included.
    assert all(getattr(role, "owns", None) != "cross_nodes" for role in roles.ROLES.values())
    for role in ("sizing", "control"):
        told = _write(_session(tmp_path, role), node(f"{role}.motor_right", role, domain="cross"))
        assert told != "allow", role
        assert graph.CROSS_NODE in told and "no registered role owns the cross nodes" in told


def test_with_no_owner_registered_a_domain_node_is_unaffected(tmp_path: Path) -> None:
    assert _write(_session(tmp_path, "control"), node("control.gain", "control")) == "allow"


def test_the_owner_lookup_refuses_a_duty_nobody_owns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(roles, "ROLES", {"control": roles.CONTROL})
    with pytest.raises(DutyUnownedError, match="no registered role owns"):
        roles.owner_of("cross_nodes")


@pytest.mark.parametrize("duty", ["cross_nodes", "completion"])
def test_the_owner_lookup_refuses_two_owners_of_one_duty(
    monkeypatch: pytest.MonkeyPatch, duty: str
) -> None:
    # Patched straight into the mapping, past the check the register makes when it is
    # built, as a stand-in role is: the lookup counts the owners again.
    second = CrossCuttingRole(name="ballast", architecture="ARCH-051", owns=duty)  # type: ignore[arg-type]
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setitem(roles.ROLES, second.name, second)
    with pytest.raises(RoleRegisterError, match="more than one") as raised:
        roles.owner_of(duty)  # type: ignore[arg-type]
    assert raised.value.context["owners"] == ",".join(
        sorted(r.name for r in roles.ROLES.values() if getattr(r, "owns", None) == duty)
    )


def test_a_register_with_two_owners_of_the_cross_nodes_refuses_every_node_but_an_interface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
    for role, payload in (
        ("sizing", node("sizing.motor_right", "sizing")),
        ("ballast", node("ballast.mass", "ballast")),
        ("control", node("control.gain", "control")),
    ):
        told = _write(_session(tmp_path, role), payload)
        assert told != "allow", role
        assert graph.CROSS_NODE in told and "more than one" in told, role


# --- interface nodes ----------------------------------------------------------------------


@pytest.mark.usefixtures("sizing_registered")
@pytest.mark.parametrize(
    ("role", "domain"),
    [
        ("control", "cross"),
        ("control", "control"),
        ("sizing", "cross"),
        ("integration", "cross"),
    ],
)
def test_no_session_creates_an_interface_node(tmp_path: Path, role: str, domain: str) -> None:
    config = _session(tmp_path, role)
    payload = node(f"iface.{role}.p09", role, kind="interface", domain=domain, quantities={})
    told = _write(config, payload)
    assert told != "allow"
    assert graph.INTERFACE_CREATION in told and "decomposed" in told


@pytest.mark.usefixtures("sizing_registered")
def test_an_existing_interface_node_keeps_its_producer_and_its_own_refusal(
    tmp_path: Path,
) -> None:
    # Interface nodes are of the cross domain and owned by the role that produces them;
    # the cross rule leaves them to the refusal they always had.
    config = _session(tmp_path, "control")
    told = _write(config, node(INTERFACE, "control", kind="interface", domain="cross"))
    assert REJECT_INTERFACE_IMMUTABLE in told
    assert graph.CROSS_NODE not in told and graph.INTERFACE_CREATION not in told


# --- two faults at once: the earlier rule gives the reason ---------------------------------


@pytest.mark.usefixtures("sizing_registered")
def test_a_cross_write_that_is_also_a_kind_change_is_refused_as_a_kind_change(
    tmp_path: Path,
) -> None:
    config = _session(tmp_path, "control")
    told = _write(config, node("control.loop", "control", kind="module", domain="cross"))
    assert graph.KIND_CHANGE in told and graph.CROSS_NODE not in told


@pytest.mark.usefixtures("sizing_registered")
def test_turning_an_existing_node_into_an_interface_is_refused_as_a_kind_change(
    tmp_path: Path,
) -> None:
    config = _session(tmp_path, "control")
    told = _write(config, node("control.loop", "control", kind="interface", domain="cross"))
    assert graph.KIND_CHANGE in told and graph.INTERFACE_CREATION not in told


@pytest.mark.usefixtures("sizing_registered")
def test_a_cross_write_to_another_roles_node_is_refused_as_cross_role(tmp_path: Path) -> None:
    from physgate.state.protocol import REJECT_CROSS_ROLE

    config = _session(tmp_path, "control")
    told = _write(config, node("sizing.motor_left", "sizing"))
    assert REJECT_CROSS_ROLE in told and graph.CROSS_NODE not in told


@pytest.mark.usefixtures("sizing_registered")
def test_the_cross_rule_is_reported_before_a_bare_number(tmp_path: Path) -> None:
    config = _session(tmp_path, "control")
    payload = {
        **node("control.motor_current", "control", domain="cross"),
        "quantities": {"stall_current": 2.4},
    }
    told = _write(config, payload)
    assert graph.CROSS_NODE in told and REJECT_MISSING_UNIT not in told


@pytest.mark.usefixtures("sizing_registered")
def test_a_new_interface_is_reported_before_a_bare_number(tmp_path: Path) -> None:
    config = _session(tmp_path, "control")
    payload = {
        **node("iface.control.p09", "control", kind="interface", domain="cross"),
        "quantities": {"stall_current": 2.4},
    }
    told = _write(config, payload)
    assert graph.INTERFACE_CREATION in told and REJECT_MISSING_UNIT not in told


def test_the_new_rules_follow_the_kind_rule_in_the_ordered_list() -> None:
    names = [rule.__name__ for rule in graph.OWNERSHIP_RULES]
    assert names == [
        "_owner_is_the_session",
        "_owner_does_not_change",
        "_kind_does_not_change",
        "_cross_nodes_are_their_owners_alone",
        "_no_session_creates_an_interface",
        "_the_completion_owner_writes_no_node",
    ]


# --- a lookup that fails in a way nobody planned for ----------------------------------------


def test_an_unexpected_error_in_the_owner_lookup_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not a register error: the rule must not turn it into an answer of its own. It
    # reaches the hook's runtime, which refuses the call, as it refuses any failure.
    from physgate.hooks import runtime

    real = roles.owner_of

    def broken(duty: str) -> str:
        # Only the cross rule's lookup fails, so no later rule can raise in its place.
        if duty != "cross_nodes":
            return real(duty)  # type: ignore[arg-type]
        msg = "the register could not be read"
        raise RuntimeError(msg)

    monkeypatch.setattr(roles, "owner_of", broken)
    home = tmp_path / "control"
    home.mkdir()
    make_store(tmp_path / "store", node("control.loop", "control"))
    config_path, sha, config = write_config(
        home, role="control", store_root=str(tmp_path / "store")
    )
    payload = node("control.gain", "control")
    target = Path(config.worktree) / graph.PROPOSALS_DIR / "control.gain.json"
    stdin = json.dumps(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(payload)},
        )
    )
    with pytest.raises(RuntimeError):
        graph.pre_tool_use(HookInput.model_validate_json(stdin), config)
    argv = ["PreToolUse", "--hooks", "graph", "--config", str(config_path), "--config-sha256", sha]
    assert runtime.main(argv, stdin, {"graph": graph.HOOK}) == 2


# --- the owner of completion writes no node --------------------------------------------------


@pytest.mark.parametrize("domain", ["mechanical", "electrical", "control", "firmware"])
def test_the_completion_owner_writes_no_node(tmp_path: Path, domain: str) -> None:
    # As shipped, integration owns completion: its one write is the completion declaration,
    # never a node of the graph.
    assert roles.owner_of("completion") == "integration"
    told = _write(
        _session(tmp_path, "integration"), node("integration.check", "integration", domain=domain)
    )
    assert told != "allow"
    assert graph.COMPLETION_OWNER_NODE in told and "integration" in told


def test_the_completion_owner_is_found_by_what_it_owns_not_by_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.delitem(roles.ROLES, roles.INTEGRATION.name)
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    told = _write(_session(tmp_path, "closer"), node("closer.check", "closer", domain="control"))
    assert graph.COMPLETION_OWNER_NODE in told and "closer" in told
    payload = node("integration.check", "integration", domain="control")
    assert _write(_session(tmp_path, "integration"), payload) == "allow"


def test_with_no_owner_of_completion_no_role_is_held_by_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(roles.ROLES, roles.INTEGRATION.name)
    payload = node("integration.check", "integration", domain="control")
    assert _write(_session(tmp_path, "integration"), payload) == "allow"


def test_a_register_with_two_owners_of_completion_refuses_every_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    told = _write(_session(tmp_path, "control"), node("control.gain", "control"))
    assert graph.COMPLETION_OWNER_NODE in told and "more than one" in told
