"""The metrics each scorer computes, and the unit a bound on each is written in.

Kept apart from the scorers, which need the evaluation's numerical libraries, so that the
task authoring and splitting, which run in the harness's own environment, can name them.
"""

from __future__ import annotations

#: The control scorer's version: part of every task and every score, so a changed rule is
#: a changed version. 1.1.0 added ``actuator_peak``; every 1.0.0 metric is unchanged.
CONTROL_SCORER_VERSION = "1.1.0"

#: The control metric bounded in the unit of the task's own actuator: a controller's output
#: is a torque, a voltage or a force, so its unit is the one the task gives its input
#: ``actuator_limit`` in, and every bound on the metric is written in that unit.
ACTUATOR_PEAK = "actuator_peak"
#: The input that names the actuator's limit, and with it the unit of its output.
ACTUATOR_LIMIT = "actuator_limit"
#: The optional input giving the reference step's amplitude, in the plant output's unit.
REFERENCE_STEP = "reference_step"

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
