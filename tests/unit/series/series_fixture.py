"""A well-formed series record, and ways to spell it, shared by the series tests.

The record is a fixture, not a simulation result: a short step response with made-up
numbers, labelled as such, so no test reads it as evidence of anything.
"""

from __future__ import annotations

import copy
import json
from typing import Any

DIGEST = "0" * 64


def record_dict(**overrides: Any) -> dict[str, Any]:
    """A record every rule admits, with ``overrides`` applied at the top level."""
    record: dict[str, Any] = {
        "format": "series.v1",
        "id": "step_nominal",
        "title": "Fixture step response, not a simulation result",
        "group": "step",
        "axis": "time",
        "x": {"name": "time", "unit": "s", "values": [0.0, 0.01, 0.02, 0.03]},
        "traces": [
            {"name": "position", "unit": "m", "values": [0.0, 0.02, 0.05, 0.08]},
            {"name": "tilt", "unit": "rad", "values": [0.0, -0.01, -0.005, 0]},
        ],
        "inputs": {
            "seed": {"value": 7, "unit": "dimensionless"},
            "step": {"value": 0.1, "unit": "m"},
        },
        "producer": {
            "script": {"path": "modules/control/sim.py", "sha256": DIGEST},
            "loaded": [{"path": "modules/control/controller.py", "sha256": DIGEST}],
        },
    }
    record.update(copy.deepcopy(overrides))
    return record


def frequency_record_dict(**overrides: Any) -> dict[str, Any]:
    """A frequency record every rule admits: a loop's magnitude and phase."""
    base = record_dict(
        id="loop_nominal",
        group="frequency_response",
        axis="frequency",
        x={"name": "angular_frequency", "unit": "rad/s", "values": [0.1, 1.0, 10.0]},
        traces=[
            {"name": "loop_magnitude", "unit": "dimensionless", "values": [10.0, 1.0, 0.1]},
            {"name": "loop_phase", "unit": "rad", "values": [-1.6, -2.2, -2.9]},
        ],
    )
    base.update(copy.deepcopy(overrides))
    return base


def encode(record: Any) -> bytes:
    """``record`` as the bytes of a record file."""
    return json.dumps(record).encode()
