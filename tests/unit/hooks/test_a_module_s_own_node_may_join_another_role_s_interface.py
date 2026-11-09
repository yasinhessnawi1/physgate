"""A module's own node may name another role's interface in its ``constrains``, and so join it.

A reopened consumer is told to join the interface it reads by that edge. Interface nodes are fixed
at decomposition, so the edge can only be written on the consumer's own node: the hook lets that
proposal through, the store writes it, and the contract then reads the node as joined.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hook_helpers import event, make_store, node, write_config

from physgate import roles
from physgate.contracts.clause import check_pair
from physgate.contracts.pairs import ContractPair, Side
from physgate.hooks import graph
from physgate.hooks.config import HookInput
from physgate.state.schema import Node
from physgate.state.store import Store

INTERFACE = "drivetrain.motor"
CURRENT = {"value": 1.8, "unit": "A", "source": "plan", "written_by": "sizing"}


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def test_a_consumer_s_proposal_joining_another_role_s_interface_is_written_and_read_as_joined(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    interface = node(
        INTERFACE, "sizing", kind="interface", domain="cross", quantities={"current_limit": CURRENT}
    )
    make_store(store_root, interface)
    home = tmp_path / "control"
    home.mkdir()
    _, _, config = write_config(home, role="control", store_root=str(store_root))
    own = node(
        "balance_design.controller",
        "control",
        constrains=[INTERFACE],
        quantities={"current_limit": CURRENT | {"source": "interface", "written_by": "control"}},
    )
    target = Path(config.worktree) / graph.PROPOSALS_DIR / f"{own['id']}.json"
    decision = graph.pre_tool_use(
        HookInput.model_validate(
            event(
                tool_name="Write",
                cwd=config.worktree,
                tool_input={"file_path": str(target), "content": json.dumps(own)},
            )
        ),
        config,
    )
    assert decision.allow, decision.reason
    store = Store(store_root)
    try:
        written = store.write_node(own, "control")
    finally:
        store.close()
    assert written.accepted, written.reason
    pair = ContractPair(
        producer=Side(module="drivetrain", subtask_id="drivetrain-658771", role="sizing"),
        consumer=Side(module="balance", subtask_id="balance-48286f", role="control"),
        interfaces=(INTERFACE,),
    )
    nodes = {payload["id"]: Node.model_validate(payload) for payload in (interface, own)}
    (check,) = check_pair(pair, nodes).interfaces
    assert check.consumer_nodes == ("balance_design.controller",)
    assert check.not_joined == ("producer",)
