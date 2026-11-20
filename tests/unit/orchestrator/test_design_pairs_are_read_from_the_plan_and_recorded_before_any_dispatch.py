"""Which module builds what another designs is read from the plan's specifications, and recorded.

A designer writes its design on a node of its own, which both specifications name. The pair is
read from that: a node the designer's specification names under its module's name (or, where no
other module could be meant, under that name with a hyphen-separated suffix left off, or its role),
no interface node and no component, which a module dispatched after it names too. A name is read
in any case and with its module's hyphen, in the id's own form. A node is named by its first two
parts; a name inside a file path is no node, and nor is a file's own name.
A designer dispatched after the module that names its node makes no pair, so the run order the
harness sets is never changed. The pairs are recorded once, in the run's opening after the contract
pairs, only where there are some; replay refuses a set no plan could give, a second one, one after
a dispatch, and a planning line after it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan import (
    NODES,
    SEED,
    integrated,
    line,
    lines,
    refusal,
    start,
)
from test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan import (
    sizing_registered as sizing_registered,  # noqa: F401 - the register, a fixture
)

from physgate.orchestrator.decompose import IntegratedPlan, PartsPlan, Plan, mint_id
from physgate.orchestrator.design_pairs import DesignPair, named_nodes, plan_design_pairs

CRITERIA = "\n\n## Acceptance criteria\n\n1. It holds.\n"

#: The shape of the plan that let firmware run with nothing to build: control designs on its own
#: node, which firmware's specification names as what it runs; control reads sizing's interface,
#: firmware produces its own, and sizing's own nodes are named by sizing alone.
SIZING = (
    "Keep a node of your own for each interface: `sizing.drive_motor` for `drive.motor`. "
    "Write modules/sizing/sizing.py." + CRITERIA
)
CONTROL = (
    "Reads `drive.motor` (from sizing) and `firmware.loop_io` as merged. "
    "`control.balance_design` (domain control, owner control) is this module's own node: every "
    "coefficient the firmware is to run. The firmware module's criteria compare the firmware "
    "with this node." + CRITERIA
)
FIRMWARE = (
    "Produces `firmware.loop_io`. Reads `drive.motor.duty_cycle` and `control.balance_design` "
    "(from control) as merged: its coefficients, as `control.balance_design.kp` names one. "
    "Implements the design on control.balance_design." + CRITERIA
)


def module(name: str, role: str, spec: str) -> dict[str, str]:
    return {"name": name, "role": role, "module_dir": f"modules/{name}", "spec": spec}


def interface(node_id: str, owner: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "interface",
        "domain": "cross",
        "owner_role": owner,
        "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": owner}},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-25T00:00:00Z",
    }


def balancer(**specs: str) -> IntegratedPlan:
    """sizing, control, firmware, with these specifications in place of the shape's own."""
    said = {"sizing": SIZING, "control": CONTROL, "firmware": FIRMWARE, **specs}
    answer = {
        "modules": [module(name, name, spec) for name, spec in said.items()],
        "interface_nodes": [
            interface("drive.motor", "sizing"),
            interface("firmware.loop_io", "firmware"),
        ],
        "interface_consumers": [
            {"interface": "drive.motor", "consumers": ["control", "firmware"]},
            {"interface": "firmware.loop_io", "consumers": ["control"]},
        ],
        "system_requirements": [
            {"requirement": "1", "contributing": [{"module": "control", "criterion": "1"}]}
        ],
    }
    return IntegratedPlan.model_validate_json(json.dumps(answer))


SUBTASK = {"sizing": "s-1", "control": "c-2", "firmware": "f-3"}
ORDER = ("sizing", "control", "firmware")


def pairs_of(plan: Plan, order: tuple[str, ...] = ORDER) -> list[tuple[str, str, tuple[str, ...]]]:
    return [(p.designer, p.builder, p.nodes) for p in plan_design_pairs(plan, SUBTASK, order)]


# --- what is read ------------------------------------------------------------------------------


def test_the_builder_of_the_designers_own_node_is_paired_with_it_and_nothing_else_is() -> None:
    # Control's own node, named by firmware (in backticks, under a quantity's path, and bare):
    # one pair. Sizing's own node is named by sizing alone; every interface is the contract's.
    assert pairs_of(balancer()) == [("c-2", "f-3", ("control.balance_design",))]


def test_a_node_is_named_by_its_first_two_parts_and_a_path_or_a_sentence_end_is_no_node() -> None:
    spec = (
        "Run `control.law.gain` and control.law. Read modules/control.law/x.py, "
        "./control.py and C:\\control.cfg; control_law is no node."
    )
    assert named_nodes(spec) == ["control.law"]
    assert named_nodes("Under drive.motor.duty_cycle.", ("drive.motor",)) == []


def test_a_file_s_own_name_is_no_node_whatever_its_case() -> None:
    spec = (
        "Write control.md, control.py and `firmware.c`, with firmware.h, README.MD, "
        "control.law.py and balance_design.json; run control.law."
    )
    assert named_nodes(spec) == ["control.law"]
    # Both specifications naming one file of control's is no design held: no pair.
    shared = {"control": CONTROL + " See control.md.", "firmware": FIRMWARE}
    for name, spec in shared.items():
        shared[name] = spec.replace("control.balance_design", "control.md")
    assert pairs_of(balancer(**shared)) == []


def test_a_node_in_capitals_or_with_its_module_s_hyphen_is_read_in_the_id_s_form() -> None:
    assert named_nodes("Run `Control.Balance_Design` and Control.Law.Gain.") == [
        "control.balance_design",
        "control.law",
    ]
    assert named_nodes("Run `balance-control.design`.") == ["balance_control.design"]
    capital = {
        name: spec.replace("control.balance_design", "Control.Balance_Design")
        for name, spec in {"control": CONTROL, "firmware": FIRMWARE}.items()
    }
    assert pairs_of(balancer(control=capital["control"])) == [
        ("c-2", "f-3", ("control.balance_design",))
    ]
    assert pairs_of(balancer(**capital)) == [("c-2", "f-3", ("control.balance_design",))]


def test_an_interface_or_a_component_under_the_designers_name_is_no_design() -> None:
    control = CONTROL + " It also writes `control.cmd`, the interface firmware reads."
    firmware = FIRMWARE + " It reads `control.cmd` and the part `control.board`."
    plan = balancer(control=control + " Its board is `control.board`.", firmware=firmware)
    answer = json.loads(plan.model_dump_json())
    nodes = [*answer["interface_nodes"], interface("control.cmd", "control")]
    consumers = [
        *answer["interface_consumers"],
        {"interface": "control.cmd", "consumers": ["firmware"]},
    ]
    with_iface = IntegratedPlan.model_validate_json(
        json.dumps({**answer, "interface_nodes": nodes, "interface_consumers": consumers})
    )
    found = pairs_of(with_iface)
    assert found == [("c-2", "f-3", ("control.balance_design", "control.board"))]
    parts = PartsPlan.model_validate_json(
        json.dumps(
            {
                "modules": answer["modules"],
                "interface_nodes": nodes,
                "components": [
                    {
                        "node": "control.board",
                        "domain": "electrical",
                        "role": "firmware",
                        "label": "a board",
                        "own": [],
                        "shared": [],
                    }
                ],
            }
        )
    )
    assert pairs_of(parts) == [("c-2", "f-3", ("control.balance_design",))]


def test_a_designer_dispatched_after_its_builder_makes_no_pair() -> None:
    # The run order is the harness's: a pair never moves a builder ahead of its designer, so a
    # specification of sizing that names control's node holds nothing.
    sizing = SIZING + " The control module's `control.balance_design` reads these."
    assert pairs_of(balancer(sizing=sizing)) == [("c-2", "f-3", ("control.balance_design",))]
    assert pairs_of(balancer(), ("sizing", "firmware", "control")) == []


def test_a_node_under_the_role_names_its_module_where_one_module_alone_has_that_role() -> None:
    answer = json.loads(balancer().model_dump_json())
    answer["modules"][1]["name"] = "balance"  # control's module, named otherwise
    plan = IntegratedPlan.model_validate_json(
        json.dumps(
            {
                **answer,
                "interface_consumers": [
                    {"interface": "drive.motor", "consumers": ["balance", "firmware"]},
                    {"interface": "firmware.loop_io", "consumers": ["balance"]},
                ],
                "system_requirements": [
                    {"requirement": "1", "contributing": [{"module": "balance", "criterion": "1"}]}
                ],
            }
        )
    )
    subtask = {"sizing": "s-1", "balance": "c-2", "firmware": "f-3"}
    found = plan_design_pairs(plan, subtask, ("sizing", "balance", "firmware"))
    assert found == (DesignPair(designer="c-2", builder="f-3", nodes=("control.balance_design",)),)


def modules_plan(*modules: tuple[str, str, str]) -> Plan:
    """A plan of these (name, role, specification) modules, with the shape's two interfaces."""
    answer = {
        "modules": [{**module(name, role, spec)} for name, role, spec in modules],
        "interface_nodes": [
            interface("drive.motor", "sizing"),
            interface("firmware.loop_io", "firmware"),
        ],
    }
    return Plan.model_validate_json(json.dumps(answer))


#: An earlier run's wording: control's module is ``balance-control``, its node ``balance.*``.
SHORT_CONTROL = (
    "Writes `balance.controller_design`, this module's own node: the gains the firmware runs."
    + CRITERIA
)
SHORT_FIRMWARE = "Runs the gains on `balance.controller_design` as merged." + CRITERIA


def test_a_node_under_the_name_less_a_hyphen_separated_suffix_names_its_module() -> None:
    plan = modules_plan(
        ("balance-control", "control", SHORT_CONTROL),
        ("firmware", "firmware", SHORT_FIRMWARE),
    )
    subtask = {"balance-control": "c-2", "firmware": "f-3"}
    found = plan_design_pairs(plan, subtask, ("balance-control", "firmware"))
    assert found == (
        DesignPair(designer="c-2", builder="f-3", nodes=("balance.controller_design",)),
    )
    # Under its full name with an underscore, or its role, the node is its own as well.
    for first in ("balance_control", "control"):
        renamed = modules_plan(
            ("balance-control", "control", SHORT_CONTROL.replace("balance.", f"{first}.")),
            ("firmware", "firmware", SHORT_FIRMWARE.replace("balance.", f"{first}.")),
        )
        pairs = plan_design_pairs(renamed, subtask, ("balance-control", "firmware"))
        assert [p.nodes for p in pairs] == [(f"{first}.controller_design",)]


def test_a_shortened_name_or_a_role_two_modules_could_be_meant_by_names_neither() -> None:
    # Two modules shorten to ``balance``: the node is neither's, and no pair is read from it.
    plan = modules_plan(
        ("balance-control", "control", SHORT_CONTROL),
        ("balance-sensing", "electrical", "Reads the sensor." + CRITERIA),
        ("firmware", "firmware", SHORT_FIRMWARE),
    )
    order = ("balance-control", "balance-sensing", "firmware")
    subtask = {"balance-control": "c-2", "balance-sensing": "e-3", "firmware": "f-4"}
    assert plan_design_pairs(plan, subtask, order) == ()
    # A module named so owns the part over one that shortens to it or has it as its role.
    named = modules_plan(
        ("balance", "control", SHORT_CONTROL),
        ("balance-control", "control", "Tunes it." + CRITERIA),
        ("firmware", "firmware", SHORT_FIRMWARE),
    )
    found = plan_design_pairs(
        named, {"balance": "b-1", **subtask}, ("balance", *order[:1], "firmware")
    )
    assert [(p.designer, p.builder) for p in found] == [("b-1", "f-4")]


# --- what is recorded ----------------------------------------------------------------------------


def _plan_with_design() -> IntegratedPlan:
    """The pair test's plan, where fw runs drive's own node ``drive.law``."""
    plan = integrated()
    modules = [m.model_dump() for m in plan.modules]
    for m in modules:
        if m["name"] == "drive":
            m["spec"] = "Write the law on `drive.law`, your own node." + CRITERIA
        if m["name"] == "fw":
            m["spec"] = "Run exactly what `drive.law` holds, as merged." + CRITERIA
    return integrated(modules=modules)


def test_the_pairs_are_recorded_once_after_the_contract_pairs_before_any_dispatch(
    tmp_path: Path,
) -> None:
    run_dir, _ = start(tmp_path, _plan_with_design())
    log = lines(run_dir)
    kinds = [one["kind"] for one in log]
    assert kinds.count("design_pairs_planned") == 1
    assert kinds[-2:] == ["contract_pairs_planned", "design_pairs_planned"]
    names = ["budget", "drive", "fw"]
    drive, fw = (mint_id(SEED, names.index(n), n) for n in ("drive", "fw"))
    assert log[-1]["pairs"] == [{"designer": drive, "builder": fw, "nodes": ["drive.law"]}]
    assert refusal(tmp_path, log) == ""


def test_a_plan_with_no_design_pair_records_no_line_and_its_opening_as_before(
    tmp_path: Path,
) -> None:
    log = lines(start(tmp_path, integrated())[0])
    assert "design_pairs_planned" not in [one["kind"] for one in log]
    plan = Plan.model_validate_json(
        json.dumps(
            {"modules": [m.model_dump() for m in integrated().modules], "interface_nodes": NODES}
        )
    )
    log = lines(start(tmp_path / "base", plan, ("control", "firmware", "sizing"))[0])
    assert "design_pairs_planned" not in [one["kind"] for one in log]


def test_replay_refuses_design_pairs_no_plan_could_give_or_out_of_their_place(
    tmp_path: Path,
) -> None:
    log = lines(start(tmp_path, _plan_with_design())[0])
    pairs = log[-1]
    (pair,) = pairs["pairs"]
    first = next(one["subtask_id"] for one in log if one["kind"] == "subtask_planned")
    closing = mint_id(SEED, 3, "budget-closing")

    def with_pairs(*changed: dict[str, Any]) -> list[dict[str, Any]]:
        return [*log[:-1], {**pairs, "pairs": list(changed)}]

    reversed_ = {**pair, "designer": pair["builder"], "builder": pair["designer"]}
    cases = {
        "before its builder": with_pairs(reversed_),
        "plans no module": with_pairs({**pair, "builder": closing}),
        "on an interface node": with_pairs({**pair, "nodes": ["iface.drive"]}),
        "each named once": with_pairs({**pair, "nodes": ["drive.law", "drive.law"]}),
        "each recorded once": with_pairs(pair, pair),
    }
    for said, edited in cases.items():
        assert said in refusal(tmp_path, edited), said
    assert "recorded once" in refusal(tmp_path, [*log, log[-1]])
    planned = {**next(one for one in log if one["kind"] == "subtask_planned")}
    planned["subtask_id"] = "late-000000"
    assert "or its design pairs" in refusal(tmp_path, [*log, planned])
    resolve = line("stage_entered", log[-1], subtask_id=first, attempt=1, stage="resolve")
    assert "before anything is dispatched" in refusal(tmp_path, [*log[:-1], resolve, pairs])
    swapped = [*log[:-2], log[-1], log[-2]]
    assert "follow its contract pairs" in refusal(tmp_path, swapped)
