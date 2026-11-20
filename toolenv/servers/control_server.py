"""A tool server for python-control: margins, step and frequency responses, poles and zeros.

Every system is given inline, as a transfer function or a state-space model, so the server
reads no file and writes none. Every quantity it answers is a value with its unit. It is a
working aid for exploring a design: nothing it answers stands behind a reported number, which
comes from a module script that ran the library and recorded its output.

Run on the tool environment's interpreter: ``python -I control_server.py``. It imports nothing
of the harness, and python-control only inside a tool, so the protocol needs no library.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_stdio import RefusedError, Server, quantity  # noqa: E402 - the line above finds it

#: Told to every answer's reader, so an answer is never mistaken for evidence.
NOTE = "A working aid: nothing here is evidence. Compute it in a module script and record it."

_NUMBER = {"type": "number"}
_POLYNOMIAL = {"type": "array", "items": _NUMBER, "minItems": 1, "maxItems": 30}
_MATRIX = {
    "type": "array",
    "items": {"type": "array", "items": _NUMBER, "maxItems": 20},
    "maxItems": 20,
}


def _quantity_schema(unit: list[str], items: int | None, what: str) -> dict[str, Any]:
    value: dict[str, Any] = (
        {"type": "number", "minimum": 0}
        if items is None
        else {
            "type": "array",
            "items": {"type": "number", "minimum": 0},
            "minItems": 1,
            "maxItems": items,
        }
    )
    return {
        "type": "object",
        "description": what,
        "additionalProperties": False,
        "required": ["value", "unit"],
        "properties": {"value": value, "unit": {"type": "string", "enum": unit, "maxLength": 8}},
    }


SYSTEM = {
    "type": "object",
    "description": (
        "A linear time-invariant system, given as exactly one of transfer_function or "
        "state_space. Time is in s; frequencies are in rad/s. With sample_time it is sampled, "
        "and its polynomials are in z."
    ),
    "additionalProperties": False,
    "properties": {
        "transfer_function": {
            "type": "object",
            "description": "Coefficients in descending powers of s (or z).",
            "additionalProperties": False,
            "required": ["numerator", "denominator"],
            "properties": {"numerator": _POLYNOMIAL, "denominator": _POLYNOMIAL},
        },
        "state_space": {
            "type": "object",
            "description": "The matrices A, B, C and D, each a list of rows.",
            "additionalProperties": False,
            "required": ["A", "B", "C", "D"],
            "properties": {"A": _MATRIX, "B": _MATRIX, "C": _MATRIX, "D": _MATRIX},
        },
        "sample_time": _quantity_schema(["s"], None, "The sample period of a sampled system."),
    },
}
OMEGA = _quantity_schema(["rad/s", "Hz"], 2000, "The frequencies to evaluate at.")
TIMES = _quantity_schema(["s"], 2000, "The times to evaluate at, increasing from 0.")


def _object(required: list[str], **properties: Any) -> dict[str, Any]:  # noqa: ANN401 - schemas
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _floats(values: Any) -> list[float | None]:  # noqa: ANN401 - an array of the library's
    return [float(v) if math.isfinite(float(v)) else None for v in values]


def _system(arguments: dict[str, Any], *, siso: bool = True) -> Any:  # noqa: ANN401 - a library system
    given = arguments["system"]
    forms = [form for form in ("transfer_function", "state_space") if form in given]
    if len(forms) != 1:
        raise RefusedError("the system is given as exactly one of transfer_function or state_space")
    sample = given.get("sample_time")
    dt: float = 0
    if sample is not None:
        if sample["value"] <= 0:
            raise RefusedError("a sample time is greater than zero")
        dt = float(sample["value"])
    # Judged before the library is imported: a refusal needs no library.
    os.environ.setdefault("MPLBACKEND", "Agg")
    import control

    if forms[0] == "transfer_function":
        tf = given["transfer_function"]
        if not any(tf["denominator"]):
            raise RefusedError("the denominator is zero")
        system = control.tf(tf["numerator"], tf["denominator"], dt)
    else:
        ss = given["state_space"]
        system = control.ss(ss["A"], ss["B"], ss["C"], ss["D"], dt)
    if siso and (system.ninputs != 1 or system.noutputs != 1):
        raise RefusedError("this tool takes a single-input, single-output system")
    return system


def _omega(given: dict[str, Any]) -> list[float]:
    scale = 2 * math.pi if given["unit"] == "Hz" else 1.0
    return [scale * w for w in given["value"]]


def margins(arguments: dict[str, Any]) -> dict[str, Any]:
    """Gain, phase and stability margins of the loop as given, broken where they are claimed."""
    loop = _system(arguments)
    import control

    gm, pm, sm, wpc, wgc, wms = (float(x) for x in control.stability_margins(loop))
    every = control.stability_margins(loop, returnall=True)
    gains, phase_crossings = every[0], every[3]
    return {
        "gain_margin": quantity(gm, "dimensionless", note_scale="a ratio, not dB"),
        "phase_margin": quantity(pm, "deg"),
        "stability_margin": quantity(sm, "dimensionless", note_scope="smallest interior minimum"),
        "phase_crossover_frequency": quantity(wpc, "rad/s"),
        "gain_crossover_frequency": quantity(wgc, "rad/s"),
        "stability_margin_frequency": quantity(wms, "rad/s"),
        "every_gain_margin": [
            {
                "gain_margin": quantity(float(g), "dimensionless"),
                "frequency": quantity(float(w), "rad/s"),
            }
            for g, w in zip(gains, phase_crossings, strict=True)
        ],
        "note": NOTE,
    }


def step_response(arguments: dict[str, Any]) -> dict[str, Any]:
    """The unit step response of the system as given, and its step information."""
    system = _system(arguments)
    import control

    times = arguments["times"]["value"]
    if any(b <= a for a, b in zip(times, times[1:], strict=False)) or times[0] != 0:
        raise RefusedError("times increase strictly from 0")
    unit = arguments.get("output_unit", "dimensionless")
    response = control.step_response(system, T=times)
    info = control.step_info(system, T=times)
    return {
        "time": quantity(_floats(response.time), "s"),
        "output": quantity(_floats(response.outputs), unit),
        "rise_time": quantity(float(info["RiseTime"]), "s", note_scope="10 to 90 percent"),
        "settling_time": quantity(float(info["SettlingTime"]), "s", note_scope="within 2 percent"),
        "overshoot": quantity(float(info["Overshoot"]), "percent"),
        "peak": quantity(float(info["Peak"]), unit),
        "peak_time": quantity(float(info["PeakTime"]), "s"),
        "steady_state_value": quantity(float(info["SteadyStateValue"]), unit),
        "note": NOTE,
    }


def frequency_response(arguments: dict[str, Any]) -> dict[str, Any]:
    """Magnitude and phase of the system as given, on the frequencies given."""
    system = _system(arguments)
    import control
    import numpy

    # An array, never a list: python-control reads a list or tuple of exactly two
    # frequencies as the limits of a range of its own choosing, not as two frequencies.
    omega = numpy.asarray(_omega(arguments["omega"]), dtype=float)
    magnitude, phase, evaluated = control.frequency_response(system, omega)
    return {
        "omega": quantity(_floats(evaluated), "rad/s"),
        "magnitude": quantity(_floats(magnitude), "dimensionless", note_scale="a ratio, not dB"),
        "phase": quantity(_floats(phase), "rad", note_scope="wrapped to [-pi, pi]"),
        "note": NOTE,
    }


def poles_zeros(arguments: dict[str, Any]) -> dict[str, Any]:
    """The poles and transmission zeros of the system as given."""
    system = _system(arguments, siso=False)
    import control

    unit = "dimensionless" if system.dt else "rad/s"
    plane = "z-plane" if system.dt else "s-plane"

    def roots(values: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - the library's array
        return [
            {"real": quantity(float(v.real), unit), "imaginary": quantity(float(v.imag), unit)}
            for v in values
        ]

    return {
        "poles": roots(control.poles(system)),
        "zeros": roots(control.zeros(system)),
        "plane": plane,
        "note": NOTE,
    }


TOOLS = {
    "margins": (
        "Gain margin (a ratio), phase margin (deg), stability margin and their frequencies "
        "(rad/s) of an open loop given inline, broken where the margins are claimed; every "
        "gain margin when there are several.",
        _object(["system"], system=SYSTEM),
        margins,
    ),
    "step_response": (
        "The unit step response of a system given inline, on the times given, with rise time "
        "(10-90 %), settling time (2 %), overshoot and peak.",
        _object(
            ["system", "times"],
            system=SYSTEM,
            times=TIMES,
            output_unit={"type": "string", "maxLength": 32, "description": "The output's unit."},
        ),
        step_response,
    ),
    "frequency_response": (
        "Magnitude (a ratio) and phase (rad, wrapped) of a system given inline, on the "
        "frequencies given.",
        _object(["system", "omega"], system=SYSTEM, omega=OMEGA),
        frequency_response,
    ),
    "poles_zeros": (
        "The poles and zeros of a system given inline.",
        _object(["system"], system=SYSTEM),
        poles_zeros,
    ),
}


if __name__ == "__main__":
    Server("control", "1", TOOLS).serve()
