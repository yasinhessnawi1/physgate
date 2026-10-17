"""A four-role corpus for the instrument's pilot and its tests. It is not the measurement's.

The instrument's own test corpus has two artefacts, both for the electrical role. A pilot
of the instrument with real reviewers has to reach every role a measurement's artefacts go
to, so this one writes one artefact for each of the four: control, electrical, firmware
and mechanical, each with a clean twin the gate passes. Like the test corpus, it is written
by the person who built the gate, to exercise the apparatus: whether a reviewer, given the
neutral account and the packet, comes to a verdict at all, and in which form. Nothing about
any reviewer's skill is measured on it.

Its numbers cite their sources as a measurement's corpus does: a URL, ``derived:`` over a
row of the parts sheet, or ``design:`` for the two design choices. So the parts sheet each
review is given is one a source in the design actually cites.

The author model is the evaluation's implementer pin and the reviewers' is the reviewer
pin, so the instrument's model separation holds as it does for the measurement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from instrument_corpus import SOURCE_ROWS, node, with_quantity, write_corpus

#: The evaluation's pins: the corpus author's model and every reviewer's.
AUTHOR = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
ROLES = ("control", "electrical", "firmware", "mechanical")


def _sourced(payload: dict[str, Any], **sources: str) -> dict[str, Any]:
    """``payload`` with the named quantities' sources replaced."""
    quantities = {
        name: {**q, "source": sources.get(name, q["source"])}
        for name, q in payload["quantities"].items()
    }
    return {**payload, "quantities": quantities}


BALANCE = _sourced(
    node(
        "control.balance_loop",
        domain="control",
        quantities={"loop_gain": (0.8, "dimensionless"), "sample_rate": (100, "Hz")},
    ),
    loop_gain="design: the proportional gain of the balance loop, chosen for its step response",
    sample_rate="design: the balance loop runs once per main-loop tick",
)
MAIN_LOOP = _sourced(
    node(
        "firmware.main_loop",
        domain="firmware",
        quantities={"sample_rate": (100, "Hz")},
        constrains=["control.balance_loop"],
    ),
    sample_rate="design: the scheduler's tick, which sets the balance loop's rate",
)
DRIVER = node("electrical.driver", quantities={"current_limit": (1.8, "A")})
MOTOR = _sourced(
    node(
        "electrical.motor_left",
        quantities={"stall_current": (1.5, "A")},
        constrains=["electrical.driver"],
    ),
    stall_current="derived: [R1.01]",
)
IMU = node("electrical.imu", quantities={"sample_rate": (1000, "Hz")})
BRACKET = node("mechanical.motor_bracket", domain="mechanical", quantities={"mass": (0.012, "kg")})
BASE_NODES = (BALANCE, MAIN_LOOP, DRIVER, MOTOR, IMU, BRACKET)

ARTEFACTS: tuple[dict[str, Any], ...] = (
    {
        "id": "c1",
        "error_class": "unit",
        "expected_check": "units",
        "assigned_role": "control",
        "description": "the loop gain is written in radians per second, not as a pure number",
        "edge": None,
        "clean": {"nodes": [with_quantity(BALANCE, "loop_gain", 0.9, "dimensionless")]},
        "injected": {"nodes": [with_quantity(BALANCE, "loop_gain", 0.9, "rad/s")]},
    },
    {
        "id": "e1",
        "error_class": "magnitude",
        "expected_check": "magnitude",
        "assigned_role": "electrical",
        "description": "the IMU is sampled at 50 kHz, above the fastest rate its register sets",
        "edge": None,
        "clean": {"nodes": [with_quantity(IMU, "sample_rate", 800, "Hz")]},
        "injected": {"nodes": [with_quantity(IMU, "sample_rate", 50_000, "Hz")]},
    },
    {
        "id": "f1",
        "error_class": "propagation",
        "expected_check": "propagation",
        "assigned_role": "firmware",
        "description": "the tick doubles and the balance loop's rate is not revisited",
        "edge": {"source": "firmware.main_loop", "target": "control.balance_loop"},
        "clean": {
            "nodes": [
                with_quantity(MAIN_LOOP, "sample_rate", 200, "Hz"),
                with_quantity(BALANCE, "sample_rate", 200, "Hz"),
            ]
        },
        "injected": {"nodes": [with_quantity(MAIN_LOOP, "sample_rate", 200, "Hz")]},
    },
    {
        "id": "k1",
        "error_class": "unit",
        "expected_check": "units",
        "assigned_role": "mechanical",
        "description": "the bracket's mass is written in newtons",
        "edge": None,
        "clean": {"nodes": [with_quantity(BRACKET, "mass", 0.014, "kg")]},
        "injected": {"nodes": [with_quantity(BRACKET, "mass", 0.014, "N")]},
    },
)


def write_pilot_corpus(root: Path) -> Path:
    """Write the four-role corpus at ``root``, with its parts sheet and manifest."""
    return write_corpus(
        root, artefacts=ARTEFACTS, base_nodes=BASE_NODES, author=AUTHOR, rows=dict(SOURCE_ROWS)
    )
