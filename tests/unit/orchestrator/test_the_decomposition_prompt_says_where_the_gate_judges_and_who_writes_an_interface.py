"""The decomposition is told where the gate judges, and who writes an interface (M-195, M-196).

The gate judges a value only where a table bounds its name or kind, and a relation only where the
nodes and their ``constrains`` edges form it. Both are generated from what the gate loads, never
copied by hand, so the prompt cannot claim a bound the gate does not hold. In a run with the role
that owns the cross nodes, sizing keeps a node of its own joined to each interface it produces, and
the interface takes that node's values when sizing's opening pass merges; a run without that role
is told interface nodes are the plan's alone, as before.
"""

from __future__ import annotations

import pytest

from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import RELATIONS
from physgate.orchestrator.decompose import prompt_for

BRIEF = "Build a balancing robot."
WITH_SIZING = ["control", "firmware", "integration", "sizing"]
WITHOUT = ["control", "firmware"]

#: The opening words of the two generated sentences.
BOUNDS_OPENING = "The gate holds a value to a sourced span only"
RELATIONS_OPENING = "The gate's relations hold only where"


def sentence(prompt: str, opening: str) -> str:
    """The paragraph of ``prompt`` that starts with ``opening``, or an empty string."""
    found = [p for p in prompt.split("\n\n") if p.startswith(opening)]
    assert len(found) <= 1
    return found[0] if found else ""


@pytest.mark.parametrize("roles", [WITH_SIZING, WITHOUT])
def test_every_range_and_envelope_the_gate_loads_is_named_with_its_domains(
    roles: list[str],
) -> None:
    said = sentence(prompt_for(BRIEF, roles), BOUNDS_OPENING)
    assert said, "the prompt says nothing of where the gate has a bound"
    bounds = load_bounds()
    for domain, table in bounds.tables.items():
        for name in table.ranges:
            assert f"`{name}`" in said and domain in said
    assert bounds.envelopes, "no envelope is loaded"
    for kind in bounds.envelopes:
        assert kind.replace("_", " ") in said


@pytest.mark.parametrize("roles", [WITH_SIZING, WITHOUT])
def test_every_relation_the_gate_judges_is_stated_with_the_structure_that_forms_it(
    roles: list[str],
) -> None:
    said = sentence(prompt_for(BRIEF, roles), RELATIONS_OPENING)
    assert said, "the prompt says nothing of what forms a relation"
    for relation in RELATIONS.values():
        assert relation.statement in said
    assert "on its own node" in RELATIONS["current_limit"].statement


def test_a_run_with_sizing_is_told_that_sizing_joins_a_node_to_each_interface_it_produces() -> None:
    prompt = prompt_for(BRIEF, WITH_SIZING)
    assert "joined to each interface it produces" in prompt
    assert "before any module reads it" in prompt
    assert "a module that refines a value writes it in a node of its own" not in prompt


def test_a_run_without_sizing_keeps_the_interface_sentence_it_had() -> None:
    prompt = prompt_for(BRIEF, WITHOUT)
    assert "a module that refines a value writes it in a node of its own" in prompt
    assert "joined to each interface it produces" not in prompt
