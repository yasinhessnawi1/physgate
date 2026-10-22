"""A write that breaks a cross-cutting duty and reaches the graph is named off the durable record.

The hook and the apply step refuse a node of the ``cross`` domain from any role but the one
that owns the cross nodes, a node of a domain from that role, a new interface node from any
session, and any node from the role that owns completion. The store holds none of these
rules: frozen corpora and recorded runs were written straight into stores, and must replay
as they were. So a write that got past both reaches the graph, and the check after the step
must see it there, as it sees a node written by a role that does not own it.

The state package reads no role register. Its caller asks the register who owns each duty
and passes the answer: one owner, none, or more than one, which the register refuses when
it is built and a mapping changed afterwards can still hold. Without that answer only
ownership is checked, as it always was.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks import graph
from physgate.state.divergence import (
    COMPLETION_OWNER_NODE,
    CROSS_NODE,
    INTERFACE_CREATION,
    Divergence,
    Duties,
    divergence,
)
from physgate.state.protocol import REJECT_CROSS_ROLE
from physgate.state.store import Store

#: The register as it will stand once sizing ships: sizing owns the cross nodes, integration
#: owns completion.
SHIPPING = Duties(cross_nodes=("sizing",), completion=("integration",))


def node(node_id: str, owner: str, domain: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """A complete, legal node of ``domain``, owned and written by ``owner``."""
    base: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            "stall_current": {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-22T00:00:00Z",
    }
    base.update(fields)
    return base


@pytest.fixture
def graph_before(tmp_path: Path) -> Iterator[Store]:
    """A store holding what decomposition and earlier steps wrote; the step starts after it."""
    store = Store(tmp_path / "graph")
    for payload in (
        node("control.loop", "control", "control"),
        node("sizing.motor_left", "sizing", "cross"),
        node("iface.control.p01", "control", "cross", kind="interface", quantities={}),
    ):
        assert store.write_node(payload, str(payload["owner_role"])).accepted
    yield store
    store.close()


def _step(store: Store, role: str, *payloads: dict[str, Any]) -> list[Divergence]:
    """Write ``payloads`` as ``role`` through the store, which holds no duty, then check."""
    cursor = store.head_revision()
    for payload in payloads:
        result = store.write_node(payload, role)
        assert result.accepted, result.reason
    return divergence(store, store.diff(cursor), role, SHIPPING)


def _reasons(found: list[Divergence]) -> list[tuple[str, str]]:
    return [(d.node_id, d.reason) for d in found]


# --- the cross nodes ----------------------------------------------------------------------------


def test_a_cross_write_that_reaches_the_graph_is_named_by_divergence(graph_before: Store) -> None:
    found = _step(graph_before, "control", node("control.motor_current", "control", "cross"))
    assert _reasons(found) == [("control.motor_current", CROSS_NODE)]
    assert "only the sizing role writes" in found[0].detail


def test_a_domain_role_turning_its_own_node_cross_is_named(graph_before: Store) -> None:
    found = _step(graph_before, "control", node("control.loop", "control", "cross"))
    assert _reasons(found) == [("control.loop", CROSS_NODE)]


@pytest.mark.parametrize("domain", ["mechanical", "electrical", "control", "firmware"])
def test_a_domain_node_written_by_the_owner_of_the_cross_nodes_is_named(
    graph_before: Store, domain: str
) -> None:
    found = _step(graph_before, "sizing", node("sizing.bracket", "sizing", domain))
    assert _reasons(found) == [("sizing.bracket", CROSS_NODE)]
    assert "writes no node of a domain" in found[0].detail


def test_sizing_turning_its_own_cross_node_into_a_domain_node_is_named(
    graph_before: Store,
) -> None:
    found = _step(graph_before, "sizing", node("sizing.motor_left", "sizing", "electrical"))
    assert _reasons(found) == [("sizing.motor_left", CROSS_NODE)]


def test_sizings_cross_nodes_and_a_domain_roles_own_nodes_are_not_named(
    graph_before: Store,
) -> None:
    assert _step(graph_before, "sizing", node("sizing.motor_right", "sizing", "cross")) == []
    assert (
        _step(graph_before, "sizing", node("sizing.motor_left", "sizing", "cross", updated="t"))
        == []
    )
    assert _step(graph_before, "control", node("control.gain", "control", "control")) == []


def test_a_domain_role_handing_its_node_on_as_it_turns_it_cross_is_named(
    graph_before: Store,
) -> None:
    # The store lets an owner hand its node on. The writer is the step's role, not the owner
    # the new payload names: control wrote a cross node, whoever it says owns it now.
    handed = node("control.loop", "sizing", "cross")
    found = _step(graph_before, "control", handed)
    assert _reasons(found) == [("control.loop", CROSS_NODE)]


def test_a_node_turned_into_an_interface_is_still_held_to_the_cross_rule(
    graph_before: Store,
) -> None:
    # The store lets an owner change a node's kind. A node created as a component and
    # rewritten as a cross interface was not one of decomposition's interfaces, so the
    # exemption interfaces have does not reach it.
    turned = node("control.loop", "control", "cross", kind="interface", quantities={})
    found = _step(graph_before, "control", turned)
    assert _reasons(found) == [("control.loop", CROSS_NODE)]


# --- interface nodes ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "domain"), [("control", "cross"), ("control", "control"), ("sizing", "cross")]
)
def test_an_interface_node_created_in_a_step_is_named_by_divergence(
    graph_before: Store, role: str, domain: str
) -> None:
    created = node(f"iface.{role}.p09", role, domain, kind="interface", quantities={})
    found = _step(graph_before, role, created)
    assert _reasons(found) == [(f"iface.{role}.p09", INTERFACE_CREATION)]


def test_an_interface_written_before_the_step_is_not_a_creation_in_it(graph_before: Store) -> None:
    # Decomposition writes the interfaces before any step starts, and no step's check reads
    # them; read as if they were a step's, the same record would name the creation.
    cursor = graph_before.head_revision()
    whole = divergence(graph_before, graph_before.diff(0), "control", SHIPPING)
    assert ("iface.control.p01", INTERFACE_CREATION) in _reasons(whole)
    assert divergence(graph_before, graph_before.diff(cursor), "control", SHIPPING) == []


# --- the owner of completion ----------------------------------------------------------------------


@pytest.mark.parametrize("domain", ["mechanical", "electrical", "control", "firmware"])
def test_a_node_written_by_the_completion_owner_is_named(graph_before: Store, domain: str) -> None:
    found = _step(graph_before, "integration", node("integration.check", "integration", domain))
    assert _reasons(found) == [("integration.check", COMPLETION_OWNER_NODE)]


def test_the_completion_owner_s_new_interface_is_named_as_a_creation(graph_before: Store) -> None:
    created = node("iface.integration.p09", "integration", "cross", kind="interface", quantities={})
    found = _step(graph_before, "integration", created)
    assert _reasons(found) == [("iface.integration.p09", INTERFACE_CREATION)]


# --- what the register said ---------------------------------------------------------------------


def _with(store: Store, duties: Duties, role: str, *payloads: dict[str, Any]) -> list[Divergence]:
    cursor = store.head_revision()
    for payload in payloads:
        assert store.write_node(payload, role).accepted
    return divergence(store, store.diff(cursor), role, duties)


def test_with_no_owner_of_the_cross_nodes_every_cross_write_is_named(graph_before: Store) -> None:
    unowned = Duties(cross_nodes=(), completion=("integration",))
    found = _with(graph_before, unowned, "sizing", node("sizing.motor_right", "sizing", "cross"))
    assert _reasons(found) == [("sizing.motor_right", CROSS_NODE)]
    assert "no registered role owns the cross nodes" in found[0].detail
    assert _with(graph_before, unowned, "control", node("control.gain", "control", "control")) == []


def test_with_two_owners_of_the_cross_nodes_every_write_but_an_interface_is_named(
    graph_before: Store,
) -> None:
    contested = Duties(cross_nodes=("ballast", "sizing"), completion=("integration",))
    for role, payload in (
        ("sizing", node("sizing.motor_right", "sizing", "cross")),
        ("control", node("control.gain", "control", "control")),
    ):
        found = _with(graph_before, contested, role, payload)
        assert _reasons(found) == [(str(payload["id"]), CROSS_NODE)], role
        assert "more than one" in found[0].detail and "ballast,sizing" in found[0].detail
    created = node("iface.control.p09", "control", "cross", kind="interface", quantities={})
    found = _with(graph_before, contested, "control", created)
    assert _reasons(found) == [("iface.control.p09", INTERFACE_CREATION)]


def test_with_two_owners_of_completion_every_write_is_named(graph_before: Store) -> None:
    contested = Duties(cross_nodes=("sizing",), completion=("closer", "integration"))
    found = _with(graph_before, contested, "control", node("control.gain", "control", "control"))
    assert _reasons(found) == [("control.gain", COMPLETION_OWNER_NODE)]
    assert "more than one" in found[0].detail


def test_with_no_owner_of_completion_no_role_is_held_by_it(graph_before: Store) -> None:
    unowned = Duties(cross_nodes=("sizing",), completion=())
    payload = node("integration.check", "integration", "control")
    assert _with(graph_before, unowned, "integration", payload) == []


def test_the_owner_is_the_one_the_register_named_whatever_its_name(graph_before: Store) -> None:
    ballast = Duties(cross_nodes=("ballast",), completion=("integration",))
    assert _with(graph_before, ballast, "ballast", node("ballast.mass", "ballast", "cross")) == []
    found = _with(graph_before, ballast, "sizing", node("sizing.motor_right", "sizing", "cross"))
    assert _reasons(found) == [("sizing.motor_right", CROSS_NODE)]


# --- one entry per change, and the check as it was without the duties ---------------------------


def test_a_change_named_for_ownership_is_named_once_and_for_that(graph_before: Store) -> None:
    # Sizing's node changed during control's step: something wrote it that the step's role
    # does not own. That it would also break the cross rule is not named a second time: it
    # is a cross-role write first, as the hook and apply refuse it first.
    cursor = graph_before.head_revision()
    foreign = node("sizing.motor_left", "sizing", "electrical", updated="tampered")
    assert graph_before.write_node(foreign, "sizing").accepted
    found = divergence(graph_before, graph_before.diff(cursor), "control", SHIPPING)
    assert [(d.node_id, d.reason, d.owner_role) for d in found] == [
        ("sizing.motor_left", REJECT_CROSS_ROLE, "sizing")
    ]


def test_without_the_duties_only_ownership_is_checked(graph_before: Store) -> None:
    # What a store with no register behind it is checked for, as before the duties existed.
    cursor = graph_before.head_revision()
    assert graph_before.write_node(
        node("control.motor_current", "control", "cross"), "control"
    ).accepted
    assert divergence(graph_before, graph_before.diff(cursor), "control") == []


def test_every_offending_change_is_named_in_the_order_it_arrived(graph_before: Store) -> None:
    found = _step(
        graph_before,
        "control",
        node("control.motor_current", "control", "cross"),
        node("control.gain", "control", "control"),
        node("iface.control.p09", "control", "cross", kind="interface", quantities={}),
    )
    assert _reasons(found) == [
        ("control.motor_current", CROSS_NODE),
        ("iface.control.p09", INTERFACE_CREATION),
    ]
    assert found[0].revision < found[1].revision


def test_the_reasons_are_the_ones_the_hook_and_apply_give() -> None:
    assert (CROSS_NODE, INTERFACE_CREATION, COMPLETION_OWNER_NODE) == (
        graph.CROSS_NODE,
        graph.INTERFACE_CREATION,
        graph.COMPLETION_OWNER_NODE,
    )


def test_a_duty_divergence_says_which_node_which_step_and_why(graph_before: Store) -> None:
    (found,) = _step(graph_before, "control", node("control.motor_current", "control", "cross"))
    line = str(found)
    assert "control.motor_current" in line and f"revision {found.revision}" in line
    assert "'control'" in line and CROSS_NODE in line and found.detail in line


def test_an_ownership_divergence_reads_as_it_always_has() -> None:
    line = str(
        Divergence(
            node_id="electrical.motor", revision=7, owner_role="electrical", acting_role="control"
        )
    )
    assert line == (
        "electrical.motor at revision 7 is owned by 'electrical' but changed during a step "
        "assigned to 'control'"
    )
