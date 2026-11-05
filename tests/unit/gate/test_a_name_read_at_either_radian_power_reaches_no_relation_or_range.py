"""M-198 check, C8 and the first fix order: a reading at either radian power stays the name's.

A name read at either power of the radian (``EITHER_ANGLE``: a ``_frequency``, f or omega; a
``torque_constant``, Kt or Ke) is converted to its kind's unit as pint converts it. For a
torque constant that is exact. For a frequency it is not: pint takes the radian as one, so
13.885 rad/s becomes 13.885 Hz, not 2.21 Hz. Nothing reads that magnitude: the unit check reads
its dimension and its sign only, and no relation and no range takes such a name. These rows hold
that, so a relation or a range added later cannot quietly compare a figure 2 pi off.

Two invariants the wider reading loosened are held here too:

- the relation guard in ``relations.measured`` refuses a term the catalogue does not name. It
  asked whether the name has a kind, which a qualified name now has (``stall_current_max``);
- what ``EITHER_ANGLE`` holds changes how a name is read, as the qualifier words do, so it is part
  of ``catalogue_digest(load_laws())`` (the build STOP's first fix order).
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest
from gate_fixtures import graph, node

import physgate.gate.catalogue as catalogue
import physgate.gate.relations as relations
from physgate.gate import check_magnitude
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import KINDS, QUANTITIES, SUFFIXES, catalogue_digest, kind_of
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.laws import load_laws
from physgate.gate.relations import TermRef, measured


def _either() -> tuple[str, ...]:
    """The names and suffixes read at either power, as the catalogue lists them."""
    return tuple(catalogue.EITHER_ANGLE)


def _kind_of_key(key: str) -> str:
    if key in QUANTITIES:
        return QUANTITIES[key].kind
    (suffix,) = [s for s in SUFFIXES if s.suffix == key]
    return suffix.kind


def _relation_names() -> set[str]:
    """Every catalogued name the relations module names as a term."""
    tree = ast.parse(Path(relations.__file__).read_text())
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    return {s for s in strings if isinstance(s, str) and s in QUANTITIES}


def test_the_names_read_at_either_power_are_a_frequency_and_a_torque_constant() -> None:
    assert set(_either()) == {"_frequency", "torque_constant"}


def test_no_relation_reads_a_name_read_at_either_power() -> None:
    names = _relation_names()
    assert {"mass", "stall_current", "current_limit", "power_draw"} <= names  # the scan reads
    for key in _either():
        assert key not in names
        # A relation names catalogued names only, and a catalogued name is never read by a suffix.
        assert all(kind_of(name) is KINDS[QUANTITIES[name].kind] for name in names)


def test_no_range_or_envelope_takes_a_name_read_at_either_power() -> None:
    bounds = load_bounds()
    ranged = {name for table in bounds.tables.values() for name in table.ranges}
    # A range is by name, and every range is for a catalogued name, which no suffix reads.
    assert ranged and ranged <= set(QUANTITIES)
    for key in _either():
        assert key not in ranged
        assert _kind_of_key(key) not in bounds.envelopes


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("tilt_mode_natural_frequency", 13.885, "rad/s"),
        ("pwm_frequency_max", 20, "kHz"),
        ("torque_constant", 0.053755, "N*m/A"),
    ],
)
def test_the_magnitude_check_compares_no_name_read_at_either_power(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    graph(
        tmp_path / "g", node("control.balance", domain="control", quantities={name: (value, unit)})
    )
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_magnitude.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))
    assert ran.evaluated == 0
    assert [o.outcome for o in ran.observations] == ["unchecked"]
    assert "have no sourced range" in ran.observations[0].message


def test_a_term_the_catalogue_does_not_name_is_refused_by_the_relation_guard(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", node("electrical.motor", quantities={"stall_current_max": (1.5, "A")}))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    assert kind_of("stall_current_max") is KINDS["current"]  # it has a kind, by its reading
    with pytest.raises(ValueError, match="not in the catalogue"):
        measured(view, TermRef("electrical.motor", "stall_current_max"))


def test_what_is_read_at_either_power_is_part_of_the_catalogue_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = catalogue_digest(load_laws())
    either = catalogue.EITHER_ANGLE
    emptied: object = {} if isinstance(either, Mapping) else ()
    monkeypatch.setattr(catalogue, "EITHER_ANGLE", emptied)
    assert catalogue_digest(load_laws()) != before
