"""Laws for the laws check's tests, one per pattern and tolerance class, and the gate to run them.

Each row starts from :func:`law_fixtures.sound_law` and changes what its case needs; each carries
worked examples that give their stated outcomes, because the loader runs them. The laws are the
tests' own, over names the catalogue holds today: they exercise the evaluator, they are not the
law library's content, which a person approves.

The laws check is reached through the real gate, built with the table under test, so a check
that is not registered fails a test by an assertion (its records are missing), never by an
import error.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from law_fixtures import load, sound_law

from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import CheckRecord, PassDetails, RunningGateMode, Scope


def check_laws_module() -> ModuleType:
    """The laws check, or a failed test saying it does not exist yet."""
    try:
        return importlib.import_module("physgate.gate.check_laws")
    except ImportError:
        pytest.fail("the gate has no laws check (physgate.gate.check_laws) yet")


def example(outcome: str, **values: Any) -> dict[str, Any]:
    """A worked example: each value ``(number, unit)``, or a list of them for a summed symbol."""

    def one(value: Any) -> Any:
        if isinstance(value, list):
            return [one(v) for v in value]
        number, unit = value
        return {"value": number, "unit": unit}

    return {
        "outcome": outcome,
        "source": "the test's own numbers",
        "values": {k: one(v) for k, v in values.items()},
    }


def symbols(**places: tuple[str, str]) -> dict[str, dict[str, str]]:
    """Each symbol's catalogue name and place."""
    return {s: {"name": name, "place": place} for s, (name, place) in places.items()}


def within_rating(**changes: Any) -> dict[str, Any]:
    """A node's current draw is within its own current limit (an inequality)."""
    row = sound_law(
        "within_rating",
        statement="a node's current draw is within its own current limit",
        expression="I <= L",
        anchor="I",
        tolerance="inequality",
        symbols=symbols(I=("current_draw", "self"), L=("current_limit", "self")),
        example=[
            example("pass", I=(1.2, "A"), L=(2, "A")),
            example("fail", I=(2.5, "A"), L=(2, "A")),
        ],
    )
    row.update(changes)
    return row


def rate_throughput(**changes: Any) -> dict[str, Any]:
    """A consumer is updated no faster than the node its edge names delivers (an edge law)."""
    row = sound_law(
        "rate_throughput",
        statement="a consumer is updated no faster than its producer delivers",
        expression="U <= R",
        pattern="edge",
        anchor="U",
        tolerance="inequality",
        symbols=symbols(U=("update_rate", "self"), R=("output_data_rate", "target")),
        example=[
            example("pass", U=(100, "Hz"), R=(200, "Hz")),
            example("fail", U=(400, "Hz"), R=(200, "Hz")),
        ],
    )
    row.update(changes)
    return row


def reaction_sum(**changes: Any) -> dict[str, Any]:
    """A carrier's reaction moment is the sum of its members' (a members law)."""
    row = sound_law(
        "reaction_moment_sum",
        statement="a carrier reacts the sum of the moments of the units it carries",
        expression="M == T",
        pattern="members",
        anchor="M",
        symbols=symbols(M=("reaction_moment", "subject"), T=("reaction_moment", "each")),
        example=[
            example("pass", M=(3, "N*m"), T=[(1, "N*m"), (2, "N*m")]),
            example("fail", M=(4, "N*m"), T=[(1, "N*m"), (2, "N*m")]),
        ],
    )
    row.update(changes)
    return row


def stall_by_resistance(**changes: Any) -> dict[str, Any]:
    """A stall current is its rated voltage over its winding resistance (a model law)."""
    row = sound_law(
        "stall_by_resistance",
        statement="a motor's stall current is its rated voltage over its winding resistance",
        expression="I == V / R",
        anchor="I",
        tolerance="model",
        model={"share": "1/10", "source": "a motor text's brush-drop estimate"},
        symbols=symbols(
            I=("stall_current", "self"), V=("rated_voltage", "self"), R=("motor_resistance", "self")
        ),
        example=[
            example("pass", I=(2, "A"), V=(12, "V"), R=(6, "ohm")),
            example("fail", I=(3, "A"), V=(12, "V"), R=(6, "ohm")),
        ],
    )
    row.update(changes)
    return row


def joule_heating(**changes: Any) -> dict[str, Any]:
    """A winding's heat is its current squared times its resistance (a power of two)."""
    row = sound_law(
        "joule_heating",
        statement="a winding dissipates its current squared times its resistance",
        expression="Q == I**2 * R",
        anchor="Q",
        symbols=symbols(
            Q=("heat_dissipation", "self"),
            I=("current_draw", "self"),
            R=("motor_resistance", "self"),
        ),
        example=[
            example("pass", Q=(4, "W"), I=(2, "A"), R=(1, "ohm")),
            example("fail", Q=(5, "W"), I=(2, "A"), R=(1, "ohm")),
        ],
    )
    row.update(changes)
    return row


def output_within_rating(**changes: Any) -> dict[str, Any]:
    """A rated output power is at least the output power delivered (a ``>=`` law)."""
    row = sound_law(
        "output_within_rating",
        statement="a stage's rated output power is at least the power it delivers",
        expression="P >= O",
        anchor="P",
        tolerance="inequality",
        symbols=symbols(P=("rated_output_power", "self"), O=("output_power", "self")),
        example=[
            example("pass", P=(10, "W"), O=(8, "W")),
            example("fail", P=(8, "W"), O=(10, "W")),
        ],
    )
    row.update(changes)
    return row


def every_case() -> list[dict[str, Any]]:
    """One law of each pattern and tolerance class, the sound law among them."""
    return [
        sound_law(),
        within_rating(),
        rate_throughput(),
        reaction_sum(),
        stall_by_resistance(),
        joule_heating(),
        output_within_rating(),
    ]


def table(root: Path, laws: Iterable[dict[str, Any]]) -> Any:
    """``laws`` written and loaded through the gate's loader."""
    return load(root, list(laws))


def gate(laws: Any) -> PhysicsGate:
    """The real gate, every registered check, built with the law table ``laws``."""
    return PhysicsGate(laws=laws)


def laws_records(
    laws: Any,
    view: GraphView,
    scopes: Sequence[Scope] = ("system",),
    mode: RunningGateMode = "on",
) -> list[CheckRecord]:
    """The laws check's records when the real gate runs over ``view`` with ``laws``."""
    result = gate(laws).run(view, scopes, mode)
    return [r for r in result.checks if r.name == "laws"]


def one[T](items: Sequence[T]) -> T:
    """The one item of ``items``; a failed assertion, saying how many, if there is not one."""
    assert len(items) == 1, f"expected exactly one, found {len(items)}"
    return items[0]


def of_law(records: Iterable[CheckRecord], law_id: str) -> list[CheckRecord]:
    """The records that name ``law_id``."""
    return [r for r in records if getattr(r.details, "law_id", None) == law_id]


def evaluated(records: Iterable[CheckRecord], law_id: str) -> int | None:
    """``law_id``'s count, from its pass record or its failing records; ``None`` if neither."""
    for r in of_law(records, law_id):
        if isinstance(r.details, PassDetails):
            return r.details.evaluated
        count = getattr(r.details, "evaluated", None)
        if isinstance(count, int):
            return count
    return None
