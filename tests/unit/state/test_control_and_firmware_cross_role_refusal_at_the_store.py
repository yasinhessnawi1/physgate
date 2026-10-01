"""Control and firmware at the store's own guard: cross-role write refusal, confirmed.

``write_node`` already compares the acting role against a node's own
``owner_role`` with no table to extend, and the suite already exercises
``"control"`` as a node owner extensively (``test_divergence_names_the_foreign_write.py``,
``test_store_guards_refuse_and_change_nothing.py``). What it has not exercised
is ``"firmware"`` writing, or a ``"control"``-vs-``"firmware"`` pair symmetrically
at this layer: control's writes to its own nodes land while a write to a
firmware node is refused, and the same the other way round. Confirmation, not
new enforcement: every assertion below holds against the store exactly as
landed.
"""

from __future__ import annotations

from helpers import node

from physgate.state.protocol import REJECT_CROSS_ROLE
from physgate.state.store import Store


def test_control_writes_its_own_node(store: Store) -> None:
    result = store.write_node(node("control.loop_gain", owner_role="control"), "control")
    assert result.accepted


def test_firmware_writes_its_own_node(store: Store) -> None:
    result = store.write_node(node("firmware.loop_period", owner_role="firmware"), "firmware")
    assert result.accepted


def test_control_cannot_create_a_firmware_node(store: Store) -> None:
    result = store.write_node(node("firmware.loop_period", owner_role="firmware"), "control")
    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE


def test_firmware_cannot_create_a_control_node(store: Store) -> None:
    result = store.write_node(node("control.loop_gain", owner_role="control"), "firmware")
    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE


def test_control_cannot_update_an_existing_firmware_node(store: Store) -> None:
    store.write_node(node("firmware.loop_period", owner_role="firmware"), "firmware")
    result = store.write_node(
        node("firmware.loop_period", owner_role="firmware", updated="t1"), "control"
    )
    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE


def test_firmware_cannot_update_an_existing_control_node(store: Store) -> None:
    store.write_node(node("control.loop_gain", owner_role="control"), "control")
    result = store.write_node(
        node("control.loop_gain", owner_role="control", updated="t1"), "firmware"
    )
    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE


def test_a_rejected_firmware_write_to_a_control_node_leaves_it_untouched(store: Store) -> None:
    store.write_node(node("control.loop_gain", owner_role="control"), "control")
    before = store.read_node("control.loop_gain")
    store.write_node(node("control.loop_gain", owner_role="control", updated="t1"), "firmware")
    assert store.read_node("control.loop_gain") == before


def test_the_step_dispatched_to_control_writes_only_control_and_is_clean(store: Store) -> None:
    """The divergence check over one control step, with firmware nodes present but untouched."""
    from physgate.state.divergence import divergence

    store.write_node(node("firmware.loop_period", owner_role="firmware"), "firmware")
    cursor = store.head_revision()
    store.write_node(node("control.loop_gain", owner_role="control"), "control")
    store.write_node(
        node(
            "control.loop_gain",
            owner_role="control",
            constrains=["firmware.loop_period"],
            updated="t1",
        ),
        "control",
    )

    assert divergence(store, store.diff(cursor), "control") == []
