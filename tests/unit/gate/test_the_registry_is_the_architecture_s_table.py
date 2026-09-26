"""The registry: where each check runs and what its failure does, as the architecture says."""

from __future__ import annotations

from gate_fixtures import fixed

from physgate.gate.registry import CADENCE, REGISTRY, RegisteredCheck
from physgate.orchestrator.protocols import CHECK_NUMBERS, CheckName

#: ARCH-080, transcribed: "runs at" and "on failure" for each of the seven checks.
ARCH_080: dict[CheckName, dict[str, str]] = {
    "units": {"subtask": "block"},
    "magnitude": {"subtask": "block"},
    "equilibrium": {"module": "block"},
    "power": {"module": "block", "system": "block"},
    "conservation": {"module": "block"},
    "thermal": {"module": "warn", "system": "block"},
    "propagation": {"system": "block"},
}


def order_problems(registry: tuple[RegisteredCheck, ...]) -> list[str]:
    """What is wrong with a registry's order: a repeat, or a check out of sequence."""
    numbers = [entry.number for entry in registry]
    problems = []
    if len(set(numbers)) != len(numbers):
        problems.append("a check is registered twice")
    if numbers != sorted(numbers):
        problems.append("the checks are not in the architecture's order")
    return problems


def test_the_cadence_is_the_architecture_s_table() -> None:
    assert {name: dict(scopes) for name, scopes in CADENCE.items()} == ARCH_080
    assert set(CADENCE) == set(CHECK_NUMBERS)


def test_the_real_registry_is_in_order_with_no_repeats() -> None:
    assert order_problems(REGISTRY) == []


def test_the_order_check_sees_a_repeat_and_a_check_out_of_sequence() -> None:
    assert order_problems((fixed("units"), fixed("units"))) == ["a check is registered twice"]
    assert order_problems((fixed("power"), fixed("units"))) == [
        "the checks are not in the architecture's order"
    ]
    assert order_problems((fixed("units"), fixed("magnitude"))) == []


def test_a_registered_check_knows_its_number() -> None:
    assert [fixed(name).number for name in ARCH_080] == [1, 2, 3, 4, 5, 6, 7]
