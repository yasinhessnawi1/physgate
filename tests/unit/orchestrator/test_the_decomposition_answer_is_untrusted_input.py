"""The decomposition's answer is read, judged and validated by code, never trusted."""

from __future__ import annotations

import json
from typing import Any

import pytest

from physgate.orchestrator.decompose import (
    Plan,
    judge,
    mint_id,
    plan_problems,
    plan_schema,
    prompt_for,
    read_stream,
)

NODE: dict[str, Any] = {
    "id": "power.bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}


def module(name: str, module_dir: str, role: str = "electrical") -> dict[str, str]:
    return {"name": name, "role": role, "module_dir": module_dir, "spec": "do it"}


def plan(modules: list[dict[str, str]], nodes: list[dict[str, Any]] | None = None) -> Plan:
    return Plan.model_validate_json(
        json.dumps({"modules": modules, "interface_nodes": nodes or [NODE]})
    )


def result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "modelUsage": {"claude-opus-5": {}},
        "structured_output": {
            "modules": [module("power", "modules/power")],
            "interface_nodes": [NODE],
        },
    }
    base.update(overrides)
    return base


def test_a_valid_answer_is_a_plan() -> None:
    cause, _, got, model, turns = judge(
        result(), exit_code=0, timed_out=False, model="claude-opus-5", roles=["electrical"]
    )
    assert cause is None and got is not None and model == "claude-opus-5" and turns == 2


@pytest.mark.parametrize(
    ("overrides", "exit_code", "cause"),
    [
        ({"structured_output": None}, 0, "no_structured_output"),
        ({"modelUsage": {"claude-sonnet-5": {}}}, 0, "model_mismatch"),
        ({"modelUsage": {}}, 0, "model_mismatch"),
        ({"terminal_reason": "max_turns", "is_error": True}, 1, "turn_limit"),
        ({"terminal_reason": "api_error", "is_error": True}, 1, "api_error"),
        ({"structured_output": {"modules": []}}, 0, "invalid_plan"),
        (
            {
                "structured_output": {
                    "modules": [module("p", "modules/p")],
                    "interface_nodes": [{**NODE, "quantities": {"v": {"value": 12}}}],
                }
            },
            0,
            "invalid_plan",
        ),
    ],
    ids=[
        "success with no plan",
        "answered by another model",
        "no model named",
        "the turn limit",
        "an API error",
        "an empty plan",
        "a bare number in an interface",
    ],
)
def test_an_answer_that_is_not_a_usable_plan_fails(
    overrides: dict[str, Any], exit_code: int, cause: str
) -> None:
    got = judge(
        result(**overrides),
        exit_code=exit_code,
        timed_out=False,
        model="claude-opus-5",
        roles=["electrical"],
    )
    assert got[0] == cause and got[2] is None


def test_no_result_and_the_wall_clock_are_failures_with_their_cause() -> None:
    assert judge(None, exit_code=-9, timed_out=False, model="m-1", roles=[])[0] == "no_result"
    assert judge(None, exit_code=None, timed_out=True, model="m-1", roles=[])[0] == "wall_clock"


@pytest.mark.parametrize(
    ("modules", "nodes", "problem"),
    [
        ([module("a", "modules/a"), module("a", "modules/b")], None, "share a name"),
        ([module("a", "modules/a", role="control")], None, "no model for"),
        ([module("a", "modules/../../outside")], None, "outside"),
        ([module("a", "modules/a"), module("b", "modules/a/b")], None, "overlap"),
        ([module("a", "modules/a")], [NODE, NODE], "share an id"),
        ([module("a", "modules/a")], [{**NODE, "kind": "component"}], "not an interface"),
        ([module("a", "modules/a")], [{**NODE, "owner_role": "control"}], "no module has"),
    ],
    ids=[
        "two modules, one name",
        "a role with no model",
        "a directory leaving the repository",
        "nested module directories",
        "two nodes, one id",
        "a node that is no interface",
        "an interface owned by nobody's role",
    ],
)
def test_what_the_schema_cannot_say_is_checked_by_code(
    modules: list[dict[str, str]], nodes: list[dict[str, Any]] | None, problem: str
) -> None:
    found = plan_problems(plan(modules, nodes), ["electrical"])
    assert any(problem in p for p in found), found


def test_usage_is_counted_once_per_message_and_garbage_lines_are_skipped() -> None:
    usage = {"input_tokens": 10, "output_tokens": 5}
    lines = [
        json.dumps({"type": "assistant", "message": {"id": "m1", "usage": usage}}),
        json.dumps({"type": "assistant", "message": {"id": "m1", "usage": usage}}),
        "not json at all",
        json.dumps(["a", "list"]),
        json.dumps({"type": "result", "num_turns": 2}),
    ]
    got_result, got_usage = read_stream("\n".join(lines))
    assert got_result == {"type": "result", "num_turns": 2}
    assert [(u.message_id, u.usage.input_tokens) for u in got_usage] == [("m1", 10)]


def test_ids_are_minted_from_the_seed_not_chosen_by_the_model() -> None:
    assert mint_id(7, 0, "power") == mint_id(7, 0, "power")
    assert mint_id(7, 0, "power") != mint_id(8, 0, "power")
    assert mint_id(7, 0, "power") != mint_id(7, 1, "power")
    assert mint_id(7, 0, "power").startswith("power-")


def test_the_prompt_is_a_template_around_the_brief() -> None:
    text = prompt_for("Build a robot.", ["electrical", "control"])
    assert text.endswith("Brief:\nBuild a robot.\n")
    assert "Roles available: control, electrical." in text
    assert prompt_for("Build a robot.", ["control", "electrical"]) == text


def test_the_schema_the_binary_holds_the_answer_to_is_the_plans() -> None:
    schema = json.loads(plan_schema())
    assert set(schema["properties"]) == {"modules", "interface_nodes"}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("module_dir", ["../outside", ".physgate/specs", "/abs", ""])
def test_the_schema_itself_refuses_a_directory_that_starts_outside(module_dir: str) -> None:
    with pytest.raises(ValueError):
        plan([module("a", module_dir)])
