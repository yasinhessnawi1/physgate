"""A planned interface node's id is held to the store's form, and the decomposition is told it.

The store keeps a node only under a dotted identifier, and the plan's interface nodes are written
into the store at the run's opening. A plan whose ids are of another form (a hyphenated
``drive-train``, say) is refused before anything is written, so the decomposition is told the form
in three places: the schema the binary holds the answer to carries the store's own pattern, the
prompt states the form with an example, and the refusal of a plan that missed it names the form.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan as pairs

from physgate import roles
from physgate.orchestrator.decompose import ReplanFindings, plan_schema, prompt_for, replan_prompt
from physgate.orchestrator.exceptions import PlanRefusedError
from physgate.state.schema import NODE_ID_PATTERN

#: The run role sets the schema and the prompt differ by: neither cross-cutting role, sizing
#: alone, and both.
RUN_ROLES = [("control", "firmware"), ("control", "firmware", "sizing"), pairs.BOTH]


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _id_sentences(prompt: str) -> list[str]:
    """The prompt's sentences that speak of a node's id."""
    return [one for one in re.split(r"(?<=\.)\s+", prompt) if re.search(r"\bids?\b", one)]


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_schema_s_node_id_carries_the_store_s_pattern(run_roles: tuple[str, ...]) -> None:
    schema = json.loads(plan_schema(run_roles))
    node_id = schema["$defs"]["Node"]["properties"]["id"]
    assert node_id.get("pattern") == NODE_ID_PATTERN.pattern, node_id
    assert node_id["maxLength"] == 128


@pytest.mark.parametrize("run_roles", RUN_ROLES, ids=", ".join)
def test_the_prompt_states_the_form_with_an_example_of_it(run_roles: tuple[str, ...]) -> None:
    prompt = prompt_for("Build a robot.", run_roles)
    found = _id_sentences(prompt)
    assert len(found) == 1, found
    (sentence,) = found
    for word in ("dot", "lowercase letters", "digits", "underscores", "begin"):
        assert word in sentence, (word, sentence)
    examples = re.findall(r'"([^"]+)"', sentence)
    assert len(examples) == 1, sentence
    assert NODE_ID_PATTERN.fullmatch(examples[0]), examples
    # Neutral: an example of the form, not a quantity any brief or fixture plans.
    assert not {"robot", "motor", "drive", "iface"} & set(re.split(r"[._]", examples[0]))
    # A re-plan is sent the same prompt, so it is told the form too.
    plan = pairs.integrated()
    again = replan_prompt("Build a robot.", run_roles, plan, ReplanFindings("found", False))
    assert sentence in again


def _hyphenated() -> Any:  # noqa: ANN401
    nodes = [{**node, "id": node["id"].replace(".", "-")} for node in pairs.NODES]
    consumers = [
        {**entry, "interface": entry["interface"].replace(".", "-")} for entry in pairs.CONSUMERS
    ]
    return pairs.integrated(interface_nodes=nodes, interface_consumers=consumers)


def test_a_plan_with_a_hyphenated_interface_id_is_refused_naming_the_form(tmp_path: Path) -> None:
    with pytest.raises(PlanRefusedError) as caught:
        pairs.start(tmp_path, _hyphenated(), brief=pairs.BRIEF)
    message = str(caught.value)
    assert message.startswith("an interface node's id is not a node id"), message
    # The refusal names the form the id must take, in the words the prompt gives it.
    for word in ("dot", "lowercase letters", "digits", "underscores", "begin"):
        assert word in message, (word, message)
    assert caught.value.context["node"] == "iface-drive"
    assert not (tmp_path / "run" / "events.jsonl").exists()
