"""Closed-form stress and deflection of a straight beam of rectangular section, as numbers.

A part script states a load case (a length, a section, a material stiffness and a force, each a
value with its unit) and gets back the deflection, the peak bending stress and the reactions the
textbook formula gives, in SI, with the formula and what it assumes written beside them. That
is all: no allowable stress goes in and no margin or judgement comes out. A margin of safety is
the script's own line, against a strength it states with its source, and whether the margin is
enough is the physics gate's and the reviewer's to say.

The formulas are Euler-Bernoulli beam theory (Roark's Formulas for Stress and Strain, table of
beam cases; any mechanics of materials text): a slender, straight, prismatic beam of a linear
elastic material, small deflections, shear deformation neglected. They are evidence for a part
that is close to such a beam and for no other.

This file runs on the tool environment's interpreter, needs the standard library only, and
imports nothing of the harness.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import SCHEMA, HelperRefusedError, checked, quantity  # noqa: E402

#: The spellings an input may have, and the factor that brings each to SI.
LENGTH_UNITS = {"m": 1.0, "mm": 1.0e-3}
STIFFNESS_UNITS = {"Pa": 1.0, "MPa": 1.0e6, "GPa": 1.0e9}
FORCE_UNITS = {"N": 1.0}

ASSUMPTIONS = [
    "a straight beam of constant rectangular section, bent about the axis across its width",
    "a linear elastic, isotropic material; stress below yield",
    "small deflections; plane sections stay plane (Euler-Bernoulli)",
    "shear deformation and stress concentrations (holes, corners) are neglected",
]


def in_si(given: Any, units: Mapping[str, float], what: str) -> float:  # noqa: ANN401 - an input as the script wrote it
    """``given`` in the SI unit of its kind; refused unless it is a positive value with a unit.

    Raises:
        HelperRefusedError: it is a bare number, names a unit that is not one of ``units``, or
            its value is not a finite number above zero.
    """
    if not isinstance(given, Mapping) or set(given) != {"value", "unit"}:
        raise HelperRefusedError(f"{what} is given as a value with its unit, and nothing else")
    value, unit = given["value"], given["unit"]
    if unit not in units:
        raise HelperRefusedError(f"{what} is in one of {sorted(units)}, not {unit!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HelperRefusedError(f"{what} has a value that is not a number")
    scaled = float(value) * units[unit]
    if not 0 < scaled < float("inf"):
        raise HelperRefusedError(f"{what} is a finite number above zero")
    return scaled


def _section(
    inputs: Mapping[str, Any], length_name: str
) -> tuple[float, float, float, float, float]:
    names = {length_name, "width", "thickness", "modulus", "force"}
    if set(inputs) != names:
        raise HelperRefusedError(f"this load case takes exactly {sorted(names)}")
    return (
        in_si(inputs[length_name], LENGTH_UNITS, f"the {length_name}"),
        in_si(inputs["width"], LENGTH_UNITS, "the width"),
        in_si(inputs["thickness"], LENGTH_UNITS, "the thickness"),
        in_si(inputs["modulus"], STIFFNESS_UNITS, "the modulus of elasticity"),
        in_si(inputs["force"], FORCE_UNITS, "the force"),
    )


def _case(
    case: str, model: str, formulas: dict[str, str], inputs: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    if not case or not case.isprintable():
        raise HelperRefusedError("a load case has a printable name")
    return checked(
        {
            "schema": SCHEMA,
            "kind": "load_case",
            "case": case,
            "model": model,
            "formulas": formulas,
            "assumptions": list(ASSUMPTIONS),
            "inputs": inputs,
            "values": values,
        }
    )


def cantilever_end_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401 - each a value with its unit
    """A beam clamped at one end with a transverse force at the other.

    ``inputs`` are ``length``, ``width``, ``thickness`` (the dimension along the force),
    ``modulus`` (of elasticity) and ``force``, each ``{"value": ..., "unit": ...}``.

    Raises:
        HelperRefusedError: an input is missing, extra, without a unit or not above zero.
    """
    length, width, thickness, modulus, force = _section(inputs, "length")
    second_moment = width * thickness**3 / 12
    return _case(
        case,
        "cantilever, transverse end load, rectangular section",
        {
            "second_moment_of_area": "I = b*h**3/12",
            "tip_deflection": "delta = F*L**3/(3*E*I)",
            "peak_bending_stress": "sigma = 6*F*L/(b*h**2), at the clamp, at the outer fibre",
            "reaction_force": "R = F, at the clamp",
            "reaction_moment": "M = F*L, at the clamp",
        },
        {
            "length": quantity(length, "m"),
            "width": quantity(width, "m"),
            "thickness": quantity(thickness, "m"),
            "modulus": quantity(modulus, "Pa"),
            "force": quantity(force, "N"),
        },
        {
            "second_moment_of_area": quantity(second_moment, "m**4"),
            "tip_deflection": quantity(force * length**3 / (3 * modulus * second_moment), "m"),
            "peak_bending_stress": quantity(6 * force * length / (width * thickness**2), "Pa"),
            "reaction_force": quantity(force, "N"),
            "reaction_moment": quantity(force * length, "N*m"),
        },
    )


def simply_supported_centre_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401 - each a value with its unit
    """A beam resting on two end supports with a transverse force at mid-span.

    ``inputs`` are ``span``, ``width``, ``thickness`` (the dimension along the force),
    ``modulus`` (of elasticity) and ``force``, each ``{"value": ..., "unit": ...}``.

    Raises:
        HelperRefusedError: an input is missing, extra, without a unit or not above zero.
    """
    span, width, thickness, modulus, force = _section(inputs, "span")
    second_moment = width * thickness**3 / 12
    return _case(
        case,
        "simply supported beam, transverse load at mid-span, rectangular section",
        {
            "second_moment_of_area": "I = b*h**3/12",
            "centre_deflection": "delta = F*L**3/(48*E*I)",
            "peak_bending_stress": "sigma = 3*F*L/(2*b*h**2), at mid-span, at the outer fibre",
            "reaction_force": "R = F/2, at each support",
        },
        {
            "span": quantity(span, "m"),
            "width": quantity(width, "m"),
            "thickness": quantity(thickness, "m"),
            "modulus": quantity(modulus, "Pa"),
            "force": quantity(force, "N"),
        },
        {
            "second_moment_of_area": quantity(second_moment, "m**4"),
            "centre_deflection": quantity(force * span**3 / (48 * modulus * second_moment), "m"),
            "peak_bending_stress": quantity(3 * force * span / (2 * width * thickness**2), "Pa"),
            "reaction_force": quantity(force / 2, "N", at="each of the two supports"),
        },
    )
