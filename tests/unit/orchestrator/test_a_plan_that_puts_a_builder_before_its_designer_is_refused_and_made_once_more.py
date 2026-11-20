"""A plan that puts a module before the module whose design it implements is refused, and told why.

The run dispatches the domain modules in the plan's order (ARCH-051), and a builder is held only on
a designer dispatched before it. A plan that lists firmware before control, while firmware's
specification names control's own node as the design it runs, would have firmware dispatched with
no design to build and no hold: the failure the hold exists for, passed in silence. So the plan is
refused at the schema stage, as a plan whose interface unit the grammar refuses is: the call is made
once more, told which module was put before which and on what node, and the refusal is on the
record, with the way out: the two modules the other way round, or the quantity on an interface
node where both sides must agree on it. A second such plan ends the decomposition. The module of
the role that opens the domain work runs first whatever the plan says, and sizes from the domain's
nodes, so its specification naming a domain module's node refuses nothing. Two modules that each
name a node of the other's own are no misorder, in either order: no order could satisfy a refusal
of them. The later builds what the earlier designs, as the plan orders them, and the earlier
module's naming of the later one's node holds nothing.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import replan_rig
from test_the_decomposition_prompt_states_how_a_unit_is_spelt import REFUSED, _outcome, _told

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.decompose import ORDER_REFUSAL_HEAD, judge
from physgate.orchestrator.design_pairs import plan_design_pairs, plan_mutual_namings

MODEL = "claude-sonnet-5"
CRITERIA = "\n\n## Acceptance criteria\n\n1. It holds.\n"
#: Control designs on its own node; firmware runs what that node holds.
CONTROL = "`control.balance_design` is this module's own node: the gains to run." + CRITERIA
FIRMWARE = "Runs the gains on `control.balance_design` as merged." + CRITERIA
SIZING = "Sizes the motor from `control.balance_design`'s gains." + CRITERIA
NODE: dict[str, Any] = {
    "id": "firmware.loop_io",
    "kind": "interface",
    "domain": "cross",
    "owner_role": "firmware",
    "quantities": {
        "rate": {"value": 200, "unit": "Hz", "source": "brief", "written_by": "firmware"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-11-20T00:00:00Z",
}


def module(name: str, spec: str, role: str | None = None) -> dict[str, str]:
    return {"name": name, "role": role or name, "module_dir": f"modules/{name}", "spec": spec}


def judged(*modules: dict[str, str], roles: tuple[str, ...] = ("control", "firmware")) -> Any:  # noqa: ANN401
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "modelUsage": {MODEL: {}},
        "structured_output": {"modules": list(modules), "interface_nodes": [copy.deepcopy(NODE)]},
    }
    cause, detail, plan, *_ = judge(
        result,
        exit_code=0,
        timed_out=False,
        model=MODEL,
        roles=list(roles),
        answered=frozenset({MODEL}),
        brief="Build a robot.",
    )
    return cause, detail, plan


#: The refusal a plan that lists firmware before control is given.
MISORDERED = (
    f"{ORDER_REFUSAL_HEAD}'firmware' before module 'control', whose design on "
    "control.balance_design it implements: the designing module comes before the implementing "
    "module in the plan; put the two modules the other way round, or, where both sides must agree "
    "on the quantity, put it on an interface node and name that instead"
)


def test_a_builder_listed_before_its_designer_is_refused_naming_both_and_the_node() -> None:
    assert judged(module("firmware", FIRMWARE), module("control", CONTROL)) == (
        REFUSED,
        MISORDERED,
        None,
    )


def test_the_same_plan_in_the_designer_s_order_is_a_plan() -> None:
    cause, _, plan = judged(module("control", CONTROL), module("firmware", FIRMWARE))
    assert (cause, [m.name for m in plan.modules]) == (None, ["control", "firmware"])


def test_a_one_way_misorder_is_refused_and_the_plan_reordered_as_told_is_a_plan() -> None:
    # Firmware also names a node of its own that control does not name: still one way, refused.
    firmware = FIRMWARE + " Its own `firmware.timing` holds the loop's period."
    assert judged(module("firmware", firmware), module("control", CONTROL))[:2] == (
        REFUSED,
        MISORDERED,
    )
    cause, detail, plan = judged(module("control", CONTROL), module("firmware", firmware))
    assert (cause, detail, [m.name for m in plan.modules]) == (
        None,
        "a plan",
        ["control", "firmware"],
    )


#: Each names a node of the other's own: control reads firmware's timing, firmware runs control's
#: design.
MUTUAL_CONTROL = CONTROL + " It reads `firmware.timing`, the firmware module's own node."
MUTUAL_FIRMWARE = FIRMWARE + " `firmware.timing` is this module's own node: the loop's period."


@pytest.mark.parametrize("order", [("control", "firmware"), ("firmware", "control")])
def test_two_modules_naming_each_other_s_node_are_a_plan_in_either_order_paired_in_its_order(
    order: tuple[str, str],
) -> None:
    specs = {"control": MUTUAL_CONTROL, "firmware": MUTUAL_FIRMWARE}
    cause, detail, plan = judged(*(module(name, specs[name]) for name in order))
    assert (cause, detail) == (None, "a plan")
    assert [m.name for m in plan.modules] == list(order)
    # The later builds what the earlier designs; the earlier's naming of the later's node is the
    # pair the other way round, held to nothing and read for the record.
    first, later = order
    own = {"control": ("control.balance_design",), "firmware": ("firmware.timing",)}
    found = plan_design_pairs(plan, {n: n for n in order}, order)
    assert [(p.designer, p.builder, p.nodes) for p in found] == [(first, later, own[first])]
    crossed = plan_mutual_namings(plan, {n: n for n in order}, order)
    assert [(p.designer, p.builder, p.nodes) for p in crossed] == [(later, first, own[later])]


def test_a_builder_found_by_the_shortened_name_is_refused_too() -> None:
    control = CONTROL.replace("control.", "balance.")
    firmware = FIRMWARE.replace("control.", "balance.")
    cause, detail, _ = judged(
        module("firmware", firmware), module("balance-control", control, "control")
    )
    assert cause == REFUSED
    assert detail.startswith(f"{ORDER_REFUSAL_HEAD}'firmware' before module 'balance-control'")


def test_the_opening_module_naming_a_domain_module_s_node_refuses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from physgate import roles

    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    # Listed first, as plans list it, or last: sizing runs first and only sizes from the node.
    control, firmware, sizing = (
        module("control", CONTROL),
        module("firmware", FIRMWARE),
        module("sizing", SIZING),
    )
    for listed in ((sizing, control, firmware), (control, firmware, sizing)):
        cause, detail, plan = judged(*listed, roles=("control", "firmware", "sizing"))
        assert (cause, detail) == (None, "a plan")
        assert [m.name for m in plan.modules] == [m["name"] for m in listed]


def test_the_retry_is_sent_its_prompt_then_the_refusal() -> None:
    sent = decompose.retry_prompt("Build a robot.", ("control",), None, _outcome(MISORDERED))
    _told(sent, decompose.prompt_for("Build a robot.", ("control",)), MISORDERED)
    replan = decompose.prompt_for("Build a robot.", ("control",)) + "\nA re-plan's words.\n"
    _told(
        decompose.retry_prompt("Build a robot.", ("control",), replan, _outcome(MISORDERED)),
        replan,
        MISORDERED,
    )


@pytest.fixture
def misordered(monkeypatch: pytest.MonkeyPatch) -> str:
    """The rig's refused calls refused as a misordered plan is: the refusal's text."""
    real = replan_rig.Script.call

    def call(self: replan_rig.Script, brief: str, *, workdir: Path, **given: Any) -> Any:  # noqa: ANN401
        outcome = real(self, brief, workdir=workdir, **given)
        if outcome.cause != REFUSED:
            return outcome
        return outcome.model_copy(update={"detail": MISORDERED})

    monkeypatch.setattr(replan_rig.Script, "call", call)
    return MISORDERED


def test_a_run_that_does_not_review_its_plan_records_the_refusal_and_tells_its_one_retry(
    tmp_path: Path, misordered: str
) -> None:
    ran = replan_rig.decompose(tmp_path, "off", [replan_rig.Step(call=REFUSED), replan_rig.Step()])
    assert len(ran.script.calls) == 2 and ran.code == 0, ran.err
    _, second = ran.script.calls
    _told(second["prompt"], decompose.prompt_for(replan_rig.BRIEF, ("electrical",)), misordered)
    (retried,) = [e for e in replan_rig.events(ran.run_dir) if e["kind"] == "decomposition_retried"]
    assert retried["detail"] == misordered


def test_a_reviewed_round_journals_the_refusal_and_tells_its_one_retry(
    tmp_path: Path, misordered: str
) -> None:
    steps = [replan_rig.Step(call=REFUSED), replan_rig.Step(review="pass")]
    ran = replan_rig.decompose(tmp_path, "on", steps)
    assert len(ran.script.calls) == 2 and ran.code == 0, ran.err
    _told(
        ran.script.calls[1]["prompt"],
        decompose.prompt_for(replan_rig.BRIEF, ("electrical",)),
        misordered,
    )
    (refused,) = [one for one in replan_rig.journal(ran.run_dir) if one["kind"] == "call_refused"]
    assert refused["detail"] == misordered


def test_a_plan_misordered_twice_ends_the_decomposition_and_no_third_call_is_made(
    tmp_path: Path, misordered: str
) -> None:
    steps = [replan_rig.Step(call=REFUSED), replan_rig.Step(call=REFUSED), replan_rig.Step()]
    ran = replan_rig.decompose(tmp_path, "off", steps)
    assert len(ran.script.calls) == 2 and ran.code == 1
    assert replan_rig.events(ran.run_dir)[-1]["detail"] == f"{REFUSED}: {misordered}"
