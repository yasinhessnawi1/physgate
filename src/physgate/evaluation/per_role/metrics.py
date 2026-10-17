"""The metrics each scorer computes, and the unit a bound on each is written in.

Kept apart from the scorers, which need the evaluation's numerical libraries, so that the
task authoring and splitting, which run in the harness's own environment, can name them.
"""

from __future__ import annotations

#: The control scorer's metrics.
CONTROL_METRIC_UNITS: dict[str, str] = {
    "max_real_pole": "1/s",
    "phase_margin": "deg",
    "settling_time": "s",
    "steady_state_error": "1",
    "gain_margin_ratio": "1",
    "gain_margin_db": "dB",
    "overshoot": "percent",
}
