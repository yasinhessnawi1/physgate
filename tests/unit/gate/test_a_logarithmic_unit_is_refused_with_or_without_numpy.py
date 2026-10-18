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
from typing import Any

import pytest

from physgate.gate import units
from physgate.gate.catalogue import KINDS
from physgate.gate.units import UREG, UnitRefusedError, measure, parse

REPOSITORY = Path(__file__).resolve().parents[3]

#: Each logarithmic unit pint knows by a name a role might write, alone and in a product,
#: where pint names it ``delta_decibel`` and keeps no logarithmic converter on it.
LOGARITHMIC = ("dB", "decibel", "decibels", "dBm", "dBW", "Np", "neper", "nepers", "oct", "octave")
COMBINED = ("dB*V", "V*dB", "dB/s", "dB/Hz", "dB*m", "dB**2", "1/dB", "decade*Hz", "dBm/Hz")
#: Prefixed: pint itself refuses to build a prefixed logarithmic unit, in both environments.
PREFIXED = ("mdB", "kNp", "millidecibel", "mdB*m", "m/kNp")


def _every_logarithmic_spelling() -> list[str]:
    """Every name, symbol and alias the registry defines with a logarithmic converter.

    Read off the registry, never a list kept by hand, so a unit pint reads as logarithmic is
    not missed because this file spelt it differently. Each alone, in products and powers,
    and with a prefix.
    """
    names: set[str] = set()
    for name, definition in UREG._units.items():  # noqa: SLF001 - no public view
        if definition.converter is not None and definition.converter.is_logarithmic:
            names |= {name, *definition.aliases}
            if definition.symbol:
                names.add(definition.symbol)
    forms = ("{}", "{}*m", "m*{}", "{}/Hz", "1/{}", "{}**2", "m", "k")
    found = []
    for name in sorted(names):
        for form in forms:
            found.append(form.format(name) if "{}" in form else form + name)
    return found


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


@pytest.mark.parametrize("unit", PREFIXED)
def test_a_prefixed_logarithmic_unit_is_refused(unit: str) -> None:
    with pytest.raises(UnitRefusedError):
        parse(1, unit)


def test_every_spelling_the_registry_reads_as_logarithmic_is_refused() -> None:
    spellings = _every_logarithmic_spelling()
    assert len(spellings) > 50
    slipped = []
    for unit in spellings:
        try:
            parse(1, unit)
        except UnitRefusedError:
            continue
        slipped.append(unit)
    assert slipped == []


def test_a_unit_the_registry_cannot_resolve_is_refused_not_taken_as_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule fails closed: a factor whose definition is not found is never read as plain."""
    real = UREG.parse_unit_name

    def unresolved(name: str, case_sensitive: bool | None = None) -> tuple[Any, ...]:
        return () if name == "volt" else real(name, case_sensitive)

    monkeypatch.setattr(units.UREG, "parse_unit_name", unresolved)
    with pytest.raises(UnitRefusedError, match="cannot say"):
        parse(1, "V")


@pytest.mark.parametrize(
    "unit", ["degC", "delta_degC", "K", "V", "mV", "db", "dimensionless", "rad/s"]
)
def test_a_unit_that_is_not_logarithmic_is_not_refused_by_the_rule(unit: str) -> None:
    parse(1, unit)


def _numpy_python() -> str | None:
    named = os.environ.get("PHYSGATE_NUMPY_PYTHON")
    if named:
        return named
    local = REPOSITORY / ".venv-evaluation" / "bin" / "python"
    return str(local) if local.exists() else None


def _outcomes(python: str) -> dict[str, object]:
    units = json.dumps(LOGARITHMIC + COMBINED + PREFIXED)
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
