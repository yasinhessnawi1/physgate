"""A logarithmic unit is refused by the gate's unit layer, the same with or without numpy.

pint converts a decibel, a neper, an octave or a decade through ``log``, which is numpy's
when numpy is installed and the standard library's otherwise. The gate computes in exact
fractions, and only the standard library's ``log`` takes one, so pint alone would refuse a
decibel with its own error in one environment and crash with a ``TypeError`` in the other
(measured on pint 0.26.1). A gate verdict never depends on an optional package, so the unit
layer refuses every logarithmic unit by its own rule, as a series record already did, before
pint converts anything: a decibel is 20 log10 of an amplitude ratio to a control engineer
and 10 log10 of a power ratio to the registry, and no single conversion of it is right.

The same file runs in both environments: in whichever this suite runs, and, through
:func:`test_the_refusals_are_the_same_where_numpy_is_installed`, under an interpreter that
has numpy (``PHYSGATE_NUMPY_PYTHON``, else the repository's ``.venv-evaluation``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.gate.catalogue import KINDS
from physgate.gate.units import UnitRefusedError, measure, parse

REPOSITORY = Path(__file__).resolve().parents[3]

#: Each logarithmic unit pint knows by a name a role might write, alone and in a product,
#: where pint names it ``delta_decibel`` and keeps no logarithmic converter on it.
LOGARITHMIC = ("dB", "decibel", "dBm", "dBW", "Np", "neper", "octave", "decade")
COMBINED = ("dB*V", "V*dB", "dB/s", "dB**2", "1/dB")

#: What each unit does in the gate's unit layer: parsed, and measured against every kind.
#: Run as a script under a second interpreter; prints the outcomes as JSON.
OUTCOMES = """
import json, sys
sys.path.insert(0, sys.argv[1])
from physgate.gate.catalogue import KINDS
from physgate.gate.units import measure, parse

def outcome(call):
    try:
        call()
    except Exception as exc:
        try:
            said = str(exc)
        except Exception:
            said = "<unprintable>"
        return [type(exc).__name__, said]
    return ["accepted", ""]

units = json.loads(sys.argv[2])
found = {}
for unit in units:
    found[unit + " parsed"] = outcome(lambda: parse(1, unit))
    for name in sorted(KINDS):
        found[unit + " as " + name] = outcome(lambda: measure(KINDS[name], 1, unit))
try:
    import numpy  # noqa: F401
    found["numpy"] = True
except ImportError:
    found["numpy"] = False
print(json.dumps(found, sort_keys=True))
"""


@pytest.mark.parametrize("unit", LOGARITHMIC + COMBINED)
def test_a_logarithmic_unit_is_refused_when_it_is_parsed(unit: str) -> None:
    with pytest.raises(UnitRefusedError, match="logarithmic") as refused:
        parse(1, unit)
    assert "rule of this gate" in str(refused.value)


@pytest.mark.parametrize("unit", LOGARITHMIC + COMBINED)
def test_a_logarithmic_unit_is_refused_for_every_kind_by_the_same_rule(unit: str) -> None:
    for kind in KINDS.values():
        with pytest.raises(UnitRefusedError, match="logarithmic"):
            measure(kind, 1, unit)


@pytest.mark.parametrize("unit", ["degC", "delta_degC", "K", "V", "dimensionless", "rad/s"])
def test_a_unit_that_is_not_logarithmic_is_not_refused_by_the_rule(unit: str) -> None:
    parse(1, unit)


def _numpy_python() -> str | None:
    named = os.environ.get("PHYSGATE_NUMPY_PYTHON")
    if named:
        return named
    local = REPOSITORY / ".venv-evaluation" / "bin" / "python"
    return str(local) if local.exists() else None


def _outcomes(python: str) -> dict[str, object]:
    units = json.dumps(LOGARITHMIC + COMBINED)
    done = subprocess.run(
        [python, "-c", OUTCOMES, str(REPOSITORY / "src"), units],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    found: dict[str, object] = json.loads(done.stdout)
    return found


def test_the_refusals_are_the_same_where_numpy_is_installed() -> None:
    other = _numpy_python()
    if other is None:
        pytest.skip("no interpreter with numpy: set PHYSGATE_NUMPY_PYTHON or make .venv-evaluation")
    here, there = _outcomes(sys.executable), _outcomes(other)
    assert there.pop("numpy") is True, f"{other} has no numpy"
    here.pop("numpy")
    assert here == there
    assert {tuple(v)[0] for v in here.values()} == {"UnitRefusedError"}  # type: ignore[arg-type]
