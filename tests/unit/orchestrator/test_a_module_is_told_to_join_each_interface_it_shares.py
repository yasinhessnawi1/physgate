"""A module is told how to join each interface it shares, in the graph's own terms.

A contract clause reads only a module's joined nodes: a node of its role, not an interface node,
whose ``constrains`` list names the interface. A module that writes every value right but names
no interface is not joined, and the contract fails on every clause. So a module is told the
edge, not only the values:

- the first brief of a module whose role produces or reads an interface of the plan's pairs names
  each such interface, and says that a node of its own lists the interface's id in its
  ``constrains`` and carries every one of its quantities under the same name;
- the order a reopen gives a module that is not joined names each interface it is not joined to,
  and says the same, beside the values.

The shape is a recorded run's: a reopened consumer wrote every value into its node, wrote
``"constrains": []``, passed the gate and the review, merged, and failed the same clauses again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from orch_helpers import SCRIPTED_BOUNDS
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (
    MENDED_FW,
    chosen,
    opened,
    requests_of,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    kinds,
    lines,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    DRIVE,
    FW,
    node,
)

from physgate import roles
from physgate.orchestrator.dispatch import role_prompt
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.repair import contract_conform_instruction

#: fw as the recorded consumer wrote it: the interface's value, in a node joined only to the
#: interface fw itself produces, so the interface it reads finds no node of fw's.
UNJOINED_FW = node("fw.main", "firmware", "iface.tilt", v=12, period=10)

#: What the order says about the edge, for fw, which is not joined to the interface it reads.
JOIN_DRIVE = (
    'This module is not joined to interface "iface.drive", so the contract reads none of its '
    "nodes. Join it: in a node of this module's own (never the interface node, which no session "
    "writes), list the interface's id in the node's \"constrains\" array, and carry there every "
    "one of the interface's quantities under the same name, as the interface holds it. A node "
    'whose "constrains" names an interface is held to all of that interface\'s quantities.'
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def test_a_reopened_consumer_that_is_not_joined_is_told_the_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chosen(tmp_path, monkeypatch, writes={FW: [UNJOINED_FW]}, mended={FW: MENDED_FW})
    assert "subtask_reopened" in kinds(lines(rig))
    fw = requests_of(rig, FW)
    assert [r.attempt for r in fw] == [1, 2]
    told = fw[1].repair_instruction
    assert told is not None
    assert JOIN_DRIVE in told, told
    # The values are still told, and the edge comes before the clauses it explains.
    assert told.index(JOIN_DRIVE) < told.index("The clauses this module fails:")
    assert 'Interface "iface.drive", quantity "v": the interface holds 12 "volt"' in told


def test_the_order_names_every_interface_the_module_is_not_joined_to() -> None:
    told = contract_conform_instruction(
        "a-run-contract-2",
        2,
        ['Interface "drivetrain.body" has no quantity, and this module is not joined to it.'],
        None,
        ("drivetrain.body", "drivetrain.motor"),
    )
    assert (
        'This module is not joined to interfaces "drivetrain.body" and "drivetrain.motor", so '
        "the contract reads none of its nodes. Join it to each:"
    ) in told
    assert told.count('"constrains" array') == 1


def test_each_module_s_first_brief_names_the_interfaces_it_shares_and_how_to_join_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch, writes={FW: [UNJOINED_FW]}, mended={FW: MENDED_FW})
    firsts = {r.subtask_id: r for r in rig.dispatcher.requests if r.attempt == 1}
    # fw reads iface.drive and produces iface.tilt; drive the other way round.
    assert firsts[FW].interfaces == ("iface.drive", "iface.tilt")
    assert firsts[DRIVE].interfaces == ("iface.drive", "iface.tilt")
    told = role_prompt(firsts[FW])
    assert (
        'Your module shares the design graph\'s interfaces "iface.drive" and "iface.tilt" with '
        "other modules, and a contract test holds it to each once both modules have merged. Join "
        "your module to each: in a node of your own (never the interface node, which no session "
        "writes), list the interface's id in the node's \"constrains\" array, and carry there "
        "every one of the interface's quantities under the same name, as the interface holds it. "
        'A node whose "constrains" names an interface is held to all of that interface\'s '
        "quantities."
    ) in told


def test_a_module_that_shares_no_interface_is_told_nothing_of_joins() -> None:
    plain = SessionRequest(
        subtask_id="integ",
        attempt=1,
        assigned_role="integration",
        spec_path=".physgate/specs/integ.md",
        module_dir="modules/integration",
        model="claude-sonnet-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    assert plain.interfaces == ()
    assert "constrains" not in role_prompt(plain)
    shared = plain.model_copy(update={"interfaces": ("iface.drive",)})
    told = role_prompt(shared)
    assert told.count('"constrains" array') == 1
    assert 'interface "iface.drive" with other modules' in told
    # The sentence comes before any repair instruction, which still ends the prompt.
    fixed = shared.model_copy(update={"repair_instruction": "Attempt 1 of 3 was rejected."})
    assert role_prompt(fixed).rstrip().endswith("Attempt 1 of 3 was rejected.")
