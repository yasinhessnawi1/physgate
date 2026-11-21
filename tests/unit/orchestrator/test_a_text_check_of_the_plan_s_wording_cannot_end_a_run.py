"""The check that reads a plan's specifications for a builder put before its designer reads text.

So it must not refuse an ordinary good plan for the wording of a sentence: a file's name is no
node, and every way a specification says what a node of its own constrains names a node it designs
for and implements nothing of. Each shape here is a plan a person would accept: control first,
firmware after, control's specification naming firmware's own node, and no refusal of it.
"""

from __future__ import annotations

import pytest
from test_a_plan_that_puts_a_builder_before_its_designer_is_refused_and_made_once_more import (
    CRITERIA,
    judged,
    module,
)

from physgate.orchestrator.design_pairs import named_nodes, plan_design_pairs

NODE = "firmware.loop_period"
#: Firmware's own node, which the later module (firmware) names as its own.
OWN = f"`{NODE}` is this module's own node: the loop's period." + CRITERIA
#: Control, first in the plan, and the sentence each wording puts firmware's node in.
CONTROL = "`control.balance_design` is this module's own node: the gains to run. "


def accepted(control_says: str, firmware: str = OWN) -> None:
    cause, detail, plan = judged(
        module("control", CONTROL + control_says + CRITERIA), module("firmware", firmware)
    )
    assert (cause, detail) == (None, "a plan"), detail
    order = ["control", "firmware"]
    assert plan_design_pairs(plan, {name: name for name in order}, order) == ()


SHAPES = {
    "a multi-line json list": 'Its node: {"id": "control.balance_design", "constrains": [\n'
    f'    "{NODE}"\n  ]}}',
    "a multi-line json list of two": (
        f'Its node: {{"constrains": [\n    "firmware.a_x",\n    "{NODE}"\n]}}'
    ),
    "a yaml list": f"Its node, as yaml:\n  constrains:\n    - {NODE}\n",
    "a yaml list of two": f"Its node, as yaml:\nconstrains:\n  - firmware.a_x\n  - {NODE}\n",
    "several names with and": f"It constrains firmware.a_x and {NODE}.",
    "several names with a comma": f"It constrains firmware.a_x, {NODE}.",
    "several names with an oxford comma": f"It constrains firmware.a_x, firmware.b_y, and {NODE}.",
    "the node": f"It constrains the node {NODE}.",
    "is constrained by": f"Its node is constrained by {NODE}.",
    "constrained by, in backticks": f"Its node is constrained by `{NODE}`.",
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_node_named_where_a_node_of_its_own_constrains_it_is_no_refusal(shape: str) -> None:
    accepted(SHAPES[shape])


def test_the_wording_is_read_apart_from_a_node_named_to_be_run() -> None:
    # The same node named as the design control runs, beyond the clause, is a misorder again.
    said = f"It constrains firmware.a_x and {NODE}. It runs {NODE} as merged."
    cause, _, _ = judged(module("control", CONTROL + said + CRITERIA), module("firmware", OWN))
    assert cause == "schema_refused"
    assert named_nodes(f'"constrains": [\n "{NODE}"\n], and run firmware.other') == [
        "firmware.other"
    ]
    assert named_nodes("Nothing constrains; run firmware.other, then firmware.third") == [
        "firmware.other",
        "firmware.third",
    ]


def test_a_firmware_file_named_in_control_s_specification_is_no_node_and_no_refusal() -> None:
    control = "Does not touch firmware.c or firmware.h." + CRITERIA
    firmware = "Writes firmware.c, which holds the loop; `firmware.timing` is its own node."
    cause, detail, plan = judged(
        module("control", CONTROL + control), module("firmware", firmware + CRITERIA)
    )
    assert (cause, detail) == (None, "a plan")
    order = ["control", "firmware"]
    assert plan_design_pairs(plan, {name: name for name in order}, order) == ()


def test_a_module_whose_name_a_header_shares_is_held_on_nothing_for_it() -> None:
    both = "Includes balance.h and builds the balance.s startup code." + CRITERIA
    firmware = "Runs the loop against balance.h as merged." + CRITERIA
    cause, _, plan = judged(module("balance", both, "control"), module("firmware", firmware))
    assert cause is None
    order = ["balance", "firmware"]
    assert plan_design_pairs(plan, {name: name for name in order}, order) == ()
    for name in ("c", "h", "cc", "s", "hex", "elf", "ld", "map"):
        assert named_nodes(f"See balance.{name} and modules/balance/balance.{name}") == []
    # A last part a quantity could carry is still a node.
    assert named_nodes("See balance.step, balance.m and balance.ts") == [
        "balance.step",
        "balance.m",
        "balance.ts",
    ]
