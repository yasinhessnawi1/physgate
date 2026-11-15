"""A run that asks which parts a person has plans the design's components, in its one call.

With the switch on, the decomposition's answer also lists the components: for each a node id
of its own, a domain, the role of the module it belongs to, a label, and the quantities a part
on hand must state, apart as those its own domain reads (``own``) and those more than one
domain depends on (``shared``, which only the role that writes the cross nodes can hold). The
list is untrusted input, bounded by the schema and held by code to the plan it sits in.

With the switch off nothing is asked: the prompt, the schema and the plan's form are those of
a run before the switch, byte for byte.

Whatever the switch, a plan declares nothing for a person: an interface node holding a
declared quantity is refused.

Every name the list adds is reached through a helper that falls back to the code before it, so
a row fails on its assertion, not at collection, in a tree without the list.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import make_config
from pydantic import ValidationError

from physgate import roles
from physgate.orchestrator import decompose
from physgate.orchestrator.decompose import (
    IntegratedPlan,
    Plan,
    judge,
    plan_model,
    plan_problems,
    plan_schema,
    plan_sha256,
    prompt_for,
)
from physgate.oslayer.probe import Present
from physgate.state.vocabulary import QUANTITY_NAMES

ROLES = ("control", "firmware", "integration", "sizing")
DOMAIN_ONLY = ("control", "firmware")
MODEL = "claude-opus-5-5"
BRIEF = (
    "Build a two-wheeled balancing robot.\n\n"
    "## Acceptance criteria\n\n"
    "1. It stands upright for 60 s.\n"
    "2. It recovers from a 5 N push.\n"
)
NOT_BUILT = "the list of components is not built"


@pytest.fixture(autouse=True)
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register with sizing in it, as the plan tests of the cross-cutting roles hold it."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _spec() -> str:
    return "Do the work.\n\n## Acceptance criteria\n\n1. It holds.\n2. It lasts.\n"


def _module(name: str, role: str) -> dict[str, str]:
    return {"name": name, "role": role, "module_dir": f"modules/{name}", "spec": _spec()}


def _interface(node_id: str = "iface.drive", owner: str = "control") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "interface",
        "domain": owner,
        "owner_role": owner,
        "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": owner}},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-11-12T00:00:00Z",
    }


def component(node: str | None = "control.motor_left", **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    entry: dict[str, Any] = {
        "node": node,
        "domain": "control",
        "role": "control",
        "label": "Left drive motor",
        "own": ["mass"],
        "shared": ["stall_current", "torque_constant"],
    }
    entry.update(changes)
    return {key: value for key, value in entry.items() if value is not None}


#: A good answer of a run with sizing and integration, its components listed.
GOOD: dict[str, Any] = {
    "modules": [
        _module("budget", "sizing"),
        _module("drive", "control"),
        _module("fw", "firmware"),
    ],
    "interface_nodes": [_interface()],
    "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw"]}],
    "system_requirements": [
        {"requirement": "2", "contributing": [{"module": "drive", "criterion": "1"}]}
    ],
    "components": [
        component(),
        component("firmware.imu", domain="firmware", role="firmware", label="IMU", shared=[]),
    ],
}
#: The same of a run with the two domain roles alone: no role writes shared quantities.
PLAIN: dict[str, Any] = {
    "modules": [_module("drive", "control"), _module("fw", "firmware")],
    "interface_nodes": [_interface()],
    "components": [component(shared=[])],
}


def answer(base: dict[str, Any] = GOOD, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    given = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            given.pop(key)
        else:
            given[key] = value
    return given


def _form(run_roles: tuple[str, ...], *, parts: bool) -> type[Plan]:
    """The plan's form for the run, asked with the switch where the code takes one."""
    try:
        return plan_model(run_roles, parts=parts)  # type: ignore[call-arg, unused-ignore]
    except TypeError:
        return plan_model(run_roles)


def _schema(run_roles: tuple[str, ...], *, parts: bool) -> dict[str, Any]:
    try:
        sent = plan_schema(run_roles, BRIEF, parts=parts)  # type: ignore[call-arg, unused-ignore]
    except TypeError:
        sent = plan_schema(run_roles, BRIEF)
    loaded: dict[str, Any] = json.loads(sent)
    return loaded


def _prompt(run_roles: tuple[str, ...], *, parts: bool) -> str:
    try:
        return prompt_for(BRIEF, run_roles, parts=parts)  # type: ignore[call-arg, unused-ignore]
    except TypeError:
        return prompt_for(BRIEF, run_roles)


def problems(structured: dict[str, Any], run_roles: tuple[str, ...] = ROLES) -> list[str]:
    """What the plan check says of a parts answer, or that it was refused before the check."""
    try:
        plan = _form(run_roles, parts=True).model_validate_json(json.dumps(structured))
    except ValidationError as exc:
        if any(
            error["loc"] == ("components",) and error["type"] == "extra_forbidden"
            for error in exc.errors()
        ):
            return [NOT_BUILT]
        return [f"schema: {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return plan_problems(plan, run_roles, BRIEF)


def judged(structured: dict[str, Any], run_roles: tuple[str, ...], *, parts: bool) -> Any:  # noqa: ANN401
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "structured_output": structured,
    }
    common: dict[str, Any] = {
        "exit_code": 0,
        "timed_out": False,
        "model": MODEL,
        "roles": run_roles,
        "answered": frozenset({MODEL}),
        "brief": BRIEF,
    }
    try:
        return judge(result, parts=parts, **common)
    except TypeError:
        return judge(result, **common)


# --- the good plan ---------------------------------------------------------------------------


def test_a_plan_that_lists_its_components_has_no_problem() -> None:
    assert problems(answer()) == []
    assert problems(answer(PLAIN), DOMAIN_ONLY) == []
    cause, detail, plan, _, _ = judged(answer(), ROLES, parts=True)
    assert (cause, detail) == (None, "a plan")
    listed = getattr(plan, "components", None)
    assert listed is not None and [entry.node for entry in listed] == [
        "control.motor_left",
        "firmware.imu",
    ]
    assert listed[0].own == ("mass",) and listed[0].shared == ("stall_current", "torque_constant")
    # The plan is still of the form integration needs: the two forms are held together.
    assert isinstance(plan, IntegratedPlan)


def test_a_design_with_no_part_lists_none() -> None:
    assert problems(answer(components=[])) == []
    cause, _, plan, _, _ = judged(answer(components=[]), ROLES, parts=True)
    assert cause is None and getattr(plan, "components", None) == ()


def test_the_plan_s_digest_covers_its_components() -> None:
    cause, _, one, _, _ = judged(answer(), ROLES, parts=True)
    assert cause is None, "the plan was refused"
    relabelled = answer()
    relabelled["components"][0]["label"] = "Right drive motor"
    _, _, other, _, _ = judged(relabelled, ROLES, parts=True)
    assert plan_sha256(one) != plan_sha256(other)


def test_a_run_that_asks_is_refused_an_answer_without_the_list() -> None:
    cause, detail, plan, _, _ = judged(answer(components=None), ROLES, parts=True)
    assert (cause, plan) == ("invalid_plan", None)
    assert "components" in detail


def test_a_run_that_does_not_ask_is_refused_an_answer_with_the_list() -> None:
    cause, detail, plan, _, _ = judged(answer(), ROLES, parts=False)
    assert (cause, plan) == ("invalid_plan", None)
    assert "components" in detail
    cause, _, plan, _, _ = judged(answer(components=None), ROLES, parts=False)
    assert cause is None and type(plan) is IntegratedPlan


# --- the schema's bounds ---------------------------------------------------------------------


def _schema_refusal(structured: dict[str, Any]) -> str:
    found = problems(structured)
    assert found != [NOT_BUILT], NOT_BUILT
    return "; ".join(found)


@pytest.mark.parametrize(
    ("entry", "at"),
    [
        (component(node="motor"), "components.0.node"),
        (component(node="Control.Motor"), "components.0.node"),
        (component(node="control/../motor.x"), "components.0.node"),
        (component(node="control.motor\n"), "components.0.node"),
        (component(node="a." + "b" * 127), "components.0.node"),
        (component(node=None), "components.0.node"),
        (component(domain="cross"), "components.0.domain"),
        (component(domain="thermal"), "components.0.domain"),
        (component(domain=None), "components.0.domain"),
        (component(role=""), "components.0.role"),
        (component(role=None), "components.0.role"),
        (component(label=""), "components.0.label"),
        (component(label="x" * 81), "components.0.label"),
        (component(label=None), "components.0.label"),
        (component(own=[f"q{i}" for i in range(13)]), "components.0.own"),
        (component(shared=[f"q{i}" for i in range(13)]), "components.0.shared"),
        (component(own=["Stall Current"]), "components.0.own.0"),
        (component(own=["stall-current"]), "components.0.own.0"),
        (component(own=[""]), "components.0.own.0"),
        (component(shared=["a" * 65]), "components.0.shared.0"),
        (component(shared=["mass\n"]), "components.0.shared.0"),
        (component(own=None), "components.0.own"),
        (component(shared=None), "components.0.shared"),
        (component(declared={"mass": {"value": 1, "unit": "kg"}}), "components.0.declared"),
        (component(choice="have"), "components.0.choice"),
    ],
    ids=[
        "id_of_one_part",
        "id_in_upper_case",
        "id_with_a_path",
        "id_ending_in_a_newline",
        "id_too_long",
        "no_id",
        "the_cross_domain",
        "an_unknown_domain",
        "no_domain",
        "an_empty_role",
        "no_role",
        "an_empty_label",
        "a_label_too_long",
        "no_label",
        "thirteen_own_names",
        "thirteen_shared_names",
        "a_name_with_a_space",
        "a_name_with_a_hyphen",
        "an_empty_name",
        "a_name_too_long",
        "a_name_ending_in_a_newline",
        "no_own_list",
        "no_shared_list",
        "a_value_in_the_plan",
        "a_choice_in_the_plan",
    ],
)
def test_a_malformed_component_is_refused_by_the_schema(entry: dict[str, Any], at: str) -> None:
    assert f"schema: {at}:" in _schema_refusal(answer(components=[entry]))


def test_the_bounds_are_crossed_by_one() -> None:
    def many(n: int) -> list[dict[str, Any]]:
        return [component(f"control.part_{i}", shared=[]) for i in range(n)]

    assert problems(answer(components=many(20))) == []
    assert "schema: components:" in _schema_refusal(answer(components=many(21)))
    twelve = [f"q{i}" for i in range(12)]
    assert problems(answer(components=[component(own=twelve, shared=[])])) == []
    assert problems(answer(components=[component(label="x" * 80)])) == []
    longest = "a." + "b" * 119  # sizing's node for it is still a node id
    assert problems(answer(components=[component(node=longest)])) == []


# --- what the plan check refuses -------------------------------------------------------------


def _refused(structured: dict[str, Any], said: str, run_roles: tuple[str, ...] = ROLES) -> None:
    found = problems(structured, run_roles)
    assert any(said in problem for problem in found), found


def test_two_components_with_one_id_are_refused() -> None:
    _refused(answer(components=[component(), component(label="Again")]), "share a node id")


def test_a_component_with_an_interface_node_s_id_is_refused() -> None:
    _refused(
        answer(components=[component("iface.drive")]),
        "component 'iface.drive' has the id of an interface node",
    )


def test_a_component_with_a_role_no_module_has_is_refused() -> None:
    plan = answer(PLAIN, components=[component(role="electrical", shared=[])])
    _refused(plan, "component 'control.motor_left' is given a role no module has", DOMAIN_ONLY)
    # A role the run has a model for, and no module of the plan: still no module's.
    one = answer(PLAIN, modules=[_module("drive", "control")])
    one["components"] = [component(role="firmware", shared=[])]
    _refused(one, "is given a role no module has", DOMAIN_ONLY)


def test_a_component_of_a_cross_cutting_role_is_refused() -> None:
    # The role that writes the cross nodes writes no node of a domain, and a component is one.
    _refused(
        answer(components=[component(role="sizing")]),
        "component 'control.motor_left' is given the sizing role, which writes no node of a domain",
    )
    _refused(answer(components=[component(role="integration")]), "is given a role no module has")


def test_shared_quantities_need_the_role_that_writes_them() -> None:
    _refused(
        answer(PLAIN, components=[component()]),
        "component 'control.motor_left' names shared quantities, and the run has no role that "
        "writes the quantities more than one domain depends on",
        DOMAIN_ONLY,
    )
    # The run has the role but the plan gives it no module: nothing would hold them.
    no_module = answer(modules=[_module("drive", "control"), _module("fw", "firmware")])
    _refused(no_module, "names shared quantities, and the plan has no sizing module")


def test_a_name_in_both_lists_or_twice_in_one_is_refused() -> None:
    _refused(
        answer(components=[component(own=["mass", "stall_current"])]),
        "component 'control.motor_left' names 'stall_current' as its own and as shared",
    )
    _refused(
        answer(components=[component(own=["mass", "mass"])]),
        "component 'control.motor_left' names 'mass' more than once",
    )
    _refused(
        answer(components=[component(shared=["stall_current", "stall_current"])]),
        "names 'stall_current' more than once",
    )


@pytest.mark.parametrize("where", ["own", "shared"])
def test_a_name_that_shadows_a_relation_s_quantity_is_refused(where: str) -> None:
    lists: dict[str, Any] = {"own": ["mass"], "shared": ["torque_constant"]}
    lists[where] = [*lists[where], "stall_currnt"]
    _refused(
        answer(components=[component(**lists)]),
        "component 'control.motor_left' names 'stall_currnt', which shadows 'stall_current'",
    )
    # A name the catalogue lacks and that shadows nothing is a part's own business.
    lists[where] = [*lists[where][:-1], "shaft_finish"]
    assert problems(answer(components=[component(**lists)])) == []


def test_a_component_whose_shared_node_is_another_node_is_refused() -> None:
    # Shared values go on the sizing role's node for the component, named from its id with
    # the dots as underscores. Two components that would share one, or one that is another
    # node of the plan, is refused: one number per fact, on one node.
    _refused(
        answer(components=[component("control.motor_left"), component("control_motor.left")]),
        "components 'control.motor_left' and 'control_motor.left' would share the sizing "
        "node 'sizing.control_motor_left'",
    )
    _refused(
        answer(components=[component(), component("sizing.control_motor_left", shared=[])]),
        "component 'sizing.control_motor_left' has the id of the sizing node of "
        "'control.motor_left'",
    )
    taken = answer(interface_nodes=[_interface("sizing.control_motor_left")])
    taken["interface_consumers"] = [{"interface": "sizing.control_motor_left", "consumers": ["fw"]}]
    _refused(taken, "the sizing node 'sizing.control_motor_left' of component 'control.motor_left'")
    # An id as long as an id may be leaves no room for the role's name before it.
    _refused(
        answer(components=[component("a." + "b" * 120)]),
        "the sizing node of component",
    )
    # With no shared value there is no such node, and the same ids are two plain components.
    apart = [component("control.motor_left", shared=[]), component("control_motor.left", shared=[])]
    assert problems(answer(components=apart)) == []


def test_each_fault_is_named_beside_another() -> None:
    # Two faults in one entry, and one in another: every one is named, none hides another.
    found = problems(
        answer(
            components=[
                component("iface.drive", role="electrical", own=["mass", "stall_current"]),
                component("firmware.imu", domain="firmware", role="firmware", own=["mas"]),
            ]
        )
    )
    for said in (
        "has the id of an interface node",
        "is given a role no module has",
        "as its own and as shared",
        "which shadows 'mass'",
    ):
        assert any(said in problem for problem in found), (said, found)
    # And a fault of the plan the list sits in keeps its own words.
    found = problems(answer(modules=[_module("drive", "control"), _module("drive", "firmware")]))
    assert "two modules share a name" in found


# --- a plan declares nothing for a person ----------------------------------------------------


def _declaring(node: dict[str, Any]) -> dict[str, Any]:
    owner = node["owner_role"]
    node["quantities"]["stall_current"] = {
        "value": 2.4,
        "unit": "A",
        "source": "declared by the person",
        "written_by": owner,
        "declared": {"item_id": "run-1-parts-1", "decision_sha256": "ab" * 32, "operator": "me"},
    }
    return node


@pytest.mark.parametrize("parts", [True, False], ids=["asking", "not_asking"])
def test_an_interface_node_holding_a_declared_quantity_is_refused(parts: bool) -> None:
    base = answer() if parts else answer(components=None)
    cause, _, _, _, _ = judged(base, ROLES, parts=parts)
    assert cause is None, "the plan without the declaration is refused"
    forged = copy.deepcopy(base)
    forged["interface_nodes"] = [_declaring(_interface())]
    cause, detail, plan, _, _ = judged(forged, ROLES, parts=parts)
    assert (cause, plan) == ("invalid_plan", None)
    assert "interface node 'iface.drive' holds 'stall_current' as declared by a person" in detail


# --- what is sent ----------------------------------------------------------------------------


def test_the_schema_holds_the_list_only_when_the_run_asks() -> None:
    for run_roles in (ROLES, DOMAIN_ONLY):
        on, off = _schema(run_roles, parts=True), _schema(run_roles, parts=False)
        assert "components" in on["properties"] and "components" in on["required"], run_roles
        assert "components" not in off["properties"] and "Component" not in off["$defs"]
        entry = on["$defs"]["Component"]
        assert sorted(entry["properties"]) == ["domain", "label", "node", "own", "role", "shared"]
        assert sorted(entry["required"]) == sorted(entry["properties"])
        assert entry["additionalProperties"] is False
        assert on["properties"]["components"]["maxItems"] == 20
        assert (
            entry["properties"]["own"]["maxItems"]
            == entry["properties"]["shared"]["maxItems"]
            == 12
        )
        assert entry["properties"]["label"]["maxLength"] == 80
        # The entry's meaning is sent with it, and the root still names nothing.
        assert "person" in entry["description"]
        assert "title" not in on and "description" not in on
        # Everything else the run is sent is what it is sent without the list.
        rest = copy.deepcopy(on)
        rest["properties"].pop("components")
        rest["required"].remove("components")
        rest["$defs"].pop("Component")
        assert rest == off


def test_a_run_that_does_not_ask_is_sent_what_it_was_sent_before() -> None:
    # Held to the seeded reference's digests, recorded before the switch existed.
    from off_identity_rig import BRIEF as REFERENCE_BRIEF
    from off_identity_rig import ROLE_SETS

    recorded = json.loads((Path(__file__).parent / "off_identity_reference.json").read_text())
    for run_roles in ROLE_SETS:
        key = "+".join(run_roles)
        try:
            prompt = prompt_for(REFERENCE_BRIEF, list(run_roles), parts=False)  # type: ignore[call-arg, unused-ignore]
            schema = plan_schema(list(run_roles), REFERENCE_BRIEF, parts=False)  # type: ignore[call-arg, unused-ignore]
        except TypeError:
            prompt = schema = NOT_BUILT
        assert hashlib.sha256(prompt.encode()).hexdigest() == recorded[f"prompt:{key}"]
        assert hashlib.sha256(schema.encode()).hexdigest() == recorded[f"schema:{key}"]
        assert _form(run_roles, parts=False) in (Plan, IntegratedPlan)


def test_the_prompt_gains_one_sentence_when_the_run_asks() -> None:
    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    for run_roles in (ROLES, DOMAIN_ONLY, ("control", "electrical", "firmware", "mechanical")):
        on, off = _prompt(run_roles, parts=True), _prompt(run_roles, parts=False)
        added = f"{sentence(run_roles)}\n\n"
        assert on.count(added) == 1 and added not in off
        # One sentence, before the closing instruction, and nothing else changed.
        assert on.replace(added, "") == off
        assert on.index(added) < on.index("Answer by calling StructuredOutput once.")
        assert "\n" not in sentence(run_roles)


def test_the_sentence_is_built_from_the_catalogue_and_the_run_s_roles() -> None:
    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    with_sizing, without = sentence(ROLES), sentence(DOMAIN_ONLY)
    for said in (with_sizing, without):
        assert "have" in said and "make" in said
        assert "mechanical, electrical, control or firmware" in said
    # Its example names are the catalogue's own, read from it and never copied.
    examples = getattr(decompose, "PARTS_EXAMPLE_NAMES", ())
    assert examples and set(examples) <= set(QUANTITY_NAMES)
    assert all(f"`{name}`" in with_sizing for name in examples)
    # Shared quantities are asked for only where a role of the run writes them.
    assert "the sizing module" in with_sizing
    assert "shared" in with_sizing and "leave `shared` empty" in without
    assert "sizing" not in without


def test_a_re_plan_asks_again_only_when_the_run_asks() -> None:
    from physgate.orchestrator.decompose import ReplanFindings, replan_prompt

    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    cause, _, plan, _, _ = judged(answer(), ROLES, parts=True)
    assert cause is None and plan is not None
    findings = ReplanFindings(
        text="The review's finding: the bus is unprotected", lacks_input=False
    )
    asked = outcome_of(lambda: replan_prompt(BRIEF, ROLES, plan, findings, parts=True))  # type: ignore[call-arg, unused-ignore]
    assert isinstance(asked, str), asked
    assert sentence(ROLES) in asked
    # The plan quoted back is the plan with its components, as its digest takes it.
    assert '\\"components\\"' in asked or '"components"' in asked
    assert sentence(ROLES) not in replan_prompt(BRIEF, ROLES, plan, findings)


def _sent_by_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **switch: Any) -> str:  # noqa: ANN401
    """Everything one call hands the binary under ``switch``: its arguments and its input."""
    import subprocess

    from physgate.orchestrator.credentials import Credential

    handed: list[str] = []

    def ran(argv: list[str], **given: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        handed.extend(str(word) for word in argv)
        handed.append(str(given.get("input") or ""))
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    config = outcome_of(lambda: make_config(**switch))
    assert not isinstance(config, Exception), config
    monkeypatch.setattr(decompose, "claude_binary", lambda: "/nonexistent/claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.272")
    monkeypatch.setattr(subprocess, "run", ran)
    decompose.call(
        BRIEF,
        config=config,
        workdir=tmp_path / "decomposition",
        base_url=None,
        credential=Credential(mode="api_key", secret="sk-ant-test-dummy-not-a-credential"),
    )
    return "\n".join(handed)


def test_the_call_asks_exactly_when_the_run_s_configuration_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    run_roles = ("electrical",)  # the helper configuration's one role
    asking = {
        "parts_on_hand": "on",
        "queue_decisions": "act",
        "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
    }
    on = _sent_by_the_call(tmp_path / "on", monkeypatch, **asking)
    assert sentence(run_roles) in on
    assert plan_schema(run_roles, BRIEF, parts=True) in on
    off = _sent_by_the_call(tmp_path / "off", monkeypatch)
    assert sentence(run_roles) not in off and '"components"' not in off
    # What a run that does not ask hands the binary is the prompt and the schema as before.
    assert prompt_for(BRIEF, run_roles) in off and plan_schema(run_roles, BRIEF) in off


# --- the one retry, and a unit respelt ------------------------------------------------------


def _unit_refusal(run_roles: tuple[str, ...], *, parts: bool) -> Any:  # noqa: ANN401 - the outcome
    """The outcome of a call whose plan spelt an interface unit as the grammar refuses."""
    from physgate.orchestrator.decompose import Outcome

    misspelt = answer() if parts else answer(components=None)
    misspelt["interface_nodes"][0]["quantities"]["v"]["unit"] = "V/(rad/s)"
    cause, detail, plan, model, turns = judged(misspelt, run_roles, parts=parts)
    assert (cause, plan) == ("schema_refused", None), (cause, detail)
    return Outcome(
        session_id="decomposition-1",
        ok=False,
        cause=cause,
        detail=detail,
        plan=None,
        usage=(),
        model=model,
        num_turns=turns,
    )


def test_the_retry_after_a_refused_unit_asks_again_only_when_the_run_asks() -> None:
    from physgate.orchestrator.decompose import retry_prompt

    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    refused = _unit_refusal(ROLES, parts=True)
    asked = outcome_of(lambda: retry_prompt(BRIEF, ROLES, None, refused, parts=True))  # type: ignore[call-arg, unused-ignore]
    assert isinstance(asked, str), asked
    assert asked.startswith(_prompt(ROLES, parts=True)) and sentence(ROLES) in asked
    plain = retry_prompt(BRIEF, ROLES, None, _unit_refusal(ROLES, parts=False))
    assert plain is not None and plain.startswith(_prompt(ROLES, parts=False))
    assert sentence(ROLES) not in plain


@pytest.mark.parametrize(
    ("design_review", "steps"),
    [("off", ("refused", "fail")), ("on", ("refused", "pass"))],
    ids=["a_run_that_does_not_review_its_plan", "a_reviewed_round"],
)
def test_the_command_s_one_retry_asks_as_its_run_does(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    design_review: str,
    steps: tuple[str, str],
) -> None:
    # Through the decompose command with a scripted call: the first call's plan is refused
    # for a unit, and the retry is sent the brief's prompt again. Each run's own, so one that
    # asks is asked again, and one that does not is not.
    import replan_rig

    import physgate.orchestrator.cli as orchestrator_cli

    sentence = getattr(decompose, "parts_sentence", None)
    assert sentence is not None, NOT_BUILT
    refusal = _unit_refusal(ROLES, parts=True).detail
    scripted = replan_rig.Script.call

    def call(self: Any, brief: str, *, workdir: Path, **given: Any) -> Any:  # noqa: ANN401
        outcome = scripted(self, brief, workdir=workdir, **given)
        if outcome.cause != "schema_refused":
            return outcome
        return outcome.model_copy(update={"detail": refusal})

    monkeypatch.setattr(replan_rig.Script, "call", call)
    script = [replan_rig.Step(call="schema_refused"), replan_rig.Step(review=steps[1])]
    rig_roles = ("electrical",)
    plain = replan_rig.decompose(tmp_path / "plain", design_review, script)
    assert len(plain.script.calls) == 2, plain.code
    assert sentence(rig_roles) not in plain.script.calls[1]["prompt"]

    configured = orchestrator_cli._config
    monkeypatch.setattr(
        orchestrator_cli,
        "_config",
        lambda given, credential: configured(given, credential).model_copy(
            update={"parts_on_hand": "on"}
        ),
    )
    asking = replan_rig.decompose(tmp_path / "asking", design_review, script)
    assert len(asking.script.calls) == 2, asking.code
    again = asking.script.calls[1]["prompt"]
    assert again.startswith(prompt_for(replan_rig.BRIEF, rig_roles, parts=True))
    assert again.count(sentence(rig_roles)) == 1 and again.count(refusal) == 1


def test_a_unit_respelt_as_its_product_leaves_the_components_in_the_plan() -> None:
    # A unit the grammar takes in another spelling is rewritten as its product, and the plan
    # read again: as the form it was read in, with its list.
    respelt = answer()
    respelt["interface_nodes"][0]["quantities"]["v"]["unit"] = "V/(A*s)"
    read = outcome_of(lambda: judged(respelt, ROLES, parts=True))
    assert not isinstance(read, Exception), read
    cause, detail, plan, _, _ = read
    assert (cause, detail) == (None, "a plan")
    assert plan.interface_nodes[0].quantities["v"].unit == "V/A/s"
    assert [entry.node for entry in getattr(plan, "components", ())] == [
        "control.motor_left",
        "firmware.imu",
    ]


# --- the plan's form is the run's ------------------------------------------------------------


def _planned(
    structured: dict[str, Any], run_roles: tuple[str, ...], *, parts: bool, on: bool
) -> Any:  # noqa: ANN401
    _, _, plan, _, _ = judged(structured, run_roles, parts=parts)
    assert plan is not None
    models = make_config().models.model_copy(
        update={
            "roles": dict.fromkeys(run_roles, "claude-sonnet-5"),
            "reviewers": dict.fromkeys(run_roles, "claude-opus-5-5"),
        }
    )
    switch: dict[str, Any] = (
        {
            "parts_on_hand": "on",
            "queue_decisions": "act",
            "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
        }
        if on
        else {}
    )
    config = outcome_of(lambda: make_config(models=models, **switch))
    assert not isinstance(config, Exception), config
    return outcome_of(lambda: decompose._planned_subtasks(plan, config))


def test_a_plan_of_another_form_than_the_run_s_switch_is_not_started() -> None:
    listed, bare = answer(PLAIN), answer(PLAIN, components=None)
    matching = _planned(listed, DOMAIN_ONLY, parts=True, on=True)
    assert isinstance(matching, list) and len(matching) == 2, matching
    unasked = _planned(listed, DOMAIN_ONLY, parts=True, on=False)
    assert isinstance(unasked, Exception), "a plan with a parts list started a run that asks none"
    assert "the plan is not of the form the run's switch for a parts list calls for" in str(unasked)
    unanswered = _planned(bare, DOMAIN_ONLY, parts=False, on=True)
    assert isinstance(unanswered, Exception), "a plan with no parts list started a run that asks"
    assert "the plan is not of the form" in str(unanswered)
    assert isinstance(_planned(bare, DOMAIN_ONLY, parts=False, on=False), list)
