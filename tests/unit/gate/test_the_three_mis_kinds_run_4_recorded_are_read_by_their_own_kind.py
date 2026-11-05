"""The three values the existing suffixes gave the wrong kind in run 4 (gate seq 271).

At a64e805f the ``_radius`` suffix reads ``angle_decay_one_count_spectral_radius`` (a spectral
radius, dimension one) as a length, and ``_frequency`` reads ``proposed_gain_crossover_frequency``
and ``tilt_mode_natural_frequency`` (both rad/s) as hertz figures written wrong. Each was recorded,
not refused, but each record said a correct value disagreed with its kind. The widening fixes all
three: a spectral radius is a modulus by the longer suffix ``_spectral_radius``, a gain crossover
frequency is an angular velocity by ``_gain_crossover_frequency`` (the catalogue's own entry for
``gain_crossover_frequency``), and a ``_frequency`` is read at either radian power.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import KINDS, kind_of
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import UncheckedDetails

#: The three values as run 4 wrote them, and the kind each is read by after the widening.
MIS_KINDS = [
    ("angle_decay_one_count_spectral_radius", 1.0, "1", "modulus"),
    ("proposed_gain_crossover_frequency", 18.5987, "rad/s", "angular_velocity"),
    ("tilt_mode_natural_frequency", 13.885, "rad/s", "frequency"),
]


@pytest.mark.parametrize(("name", "value", "unit", "kind"), MIS_KINDS)
def test_a_run_4_value_the_old_suffix_mis_kinded_is_read_by_its_own_kind(
    tmp_path: Path, name: str, value: float, unit: str, kind: str
) -> None:
    assert kind_of(name) is KINDS.get(kind)
    graph(
        tmp_path / "g",
        node("control.balance_result", domain="control", quantities={name: (value, unit)}),
    )
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))
    assert not any(o.outcome == "fail" for o in ran.observations)
    records = [
        o.message
        for o in ran.observations
        if isinstance(o.details, UncheckedDetails) and name in o.details.quantities
    ]
    assert not any("is not what its suffix" in m for m in records), records
