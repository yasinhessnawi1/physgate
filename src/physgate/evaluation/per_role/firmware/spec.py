"""A firmware task's closed loop: its line protocol, its scenarios and its probes.

The firmware under test talks to a simulated plant over one serial line, in
newline-delimited ASCII: the plant sends ``SENSE <SENSOR> <integer>`` frames (and, where a
scenario injects one, ``FAULT SENSOR_TIMEOUT`` or a malformed line); the firmware answers
with ``ACT <ACTUATOR> <STATE>`` lines. A scenario fixes the plant, its parameters and
start, the time step, how often frames are sent, how long it runs and which faults are
injected when. A probe turns one scenario's recorded trace into one number, which a
headline specification of the task bounds:

- ``reaction``: milliseconds from a fault's start to the first ``ACT`` that sets an actuator
  to a state (a window spec: neither too early nor too late);
- ``off_state``: the number of times an actuator is in a state it must not be in during a
  window of the run (bounded by zero);
- ``exclusive``: the number of instants two actuator states hold at once (bounded by zero);
- ``plant_peak``: the largest value a plant variable reaches (bounded above).

Every time is a measure in ``ms``; every plant number is a measure in its own unit.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.evaluation.per_role.base import Identifier, Measure, NamedMeasure

#: A sensor or actuator name, and an actuator state, as they appear on the line.
LineWord = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")]
#: A malformed line a scenario sends: printable ASCII, no newline.
LineText = Annotated[str, StringConstraints(pattern=r"^[ -~]{1,80}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


def _ms(measure: Measure, what: str) -> Measure:
    if measure.unit != "ms" or measure.value < 0:
        msg = f"{what} is a non-negative time in ms"
        raise ValueError(msg)
    return measure


class Protocol(_Frozen):
    """The words the line carries: the plant's sensors, and each actuator's states."""

    sensors: tuple[LineWord, ...] = Field(min_length=1)
    actuators: dict[LineWord, tuple[LineWord, ...]] = Field(min_length=1)


class Fault(_Frozen):
    """One injected fault: frames stop for a while, a malformed line, or a fault frame."""

    name: Identifier
    kind: Literal["silence", "malformed", "fault_frame"]
    at: Measure
    length: Measure | None = None
    line: LineText | None = None

    @model_validator(mode="after")
    def _complete(self) -> Fault:
        _ms(self.at, f"the fault {self.name!r}'s start")
        if (self.kind == "silence") != (self.length is not None):
            msg = f"the fault {self.name!r}: a silence, and only a silence, has a length"
            raise ValueError(msg)
        if self.length is not None:
            _ms(self.length, f"the fault {self.name!r}'s length")
        if (self.kind == "malformed") != (self.line is not None):
            msg = f"the fault {self.name!r}: a malformed fault, and only one, names its line"
            raise ValueError(msg)
        return self


class Scenario(_Frozen):
    """One closed-loop run: plant, start, step, frame period, length and faults."""

    name: Identifier
    plant: Identifier
    params: tuple[NamedMeasure, ...] = ()
    initial: tuple[NamedMeasure, ...] = ()
    tick: Measure
    frame_period: Measure
    duration: Measure
    faults: tuple[Fault, ...] = ()

    @model_validator(mode="after")
    def _timed(self) -> Scenario:
        for what, measure in (("tick", self.tick), ("frame period", self.frame_period)):
            _ms(measure, f"the scenario {self.name!r}'s {what}")
            if measure.value <= 0:
                msg = f"the scenario {self.name!r}'s {what} is positive"
                raise ValueError(msg)
        _ms(self.duration, f"the scenario {self.name!r}'s duration")
        if len({f.name for f in self.faults}) != len(self.faults):
            msg = f"the scenario {self.name!r} names a fault twice"
            raise ValueError(msg)
        return self


class Probe(_Frozen):
    """One number read off one scenario's trace, by name, for a spec to bound."""

    name: Identifier
    scenario: Identifier
    kind: Literal["reaction", "off_state", "exclusive", "plant_peak"]
    fault: Identifier | None = None
    actuator: LineWord | None = None
    state: LineWord | None = None
    other_actuator: LineWord | None = None
    other_state: LineWord | None = None
    window: tuple[Measure, Measure] | None = None
    variable: Identifier | None = None

    @model_validator(mode="after")
    def _complete(self) -> Probe:
        needs = {
            "reaction": ("fault", "actuator", "state"),
            "off_state": ("actuator", "state", "window"),
            "exclusive": ("actuator", "state", "other_actuator", "other_state"),
            "plant_peak": ("variable",),
        }[self.kind]
        fields = ("fault", "actuator", "state", "other_actuator", "other_state", "window")
        given = {f for f in (*fields, "variable") if getattr(self, f) is not None}
        if given != set(needs):
            msg = f"the probe {self.name!r} ({self.kind}) takes exactly {sorted(needs)}"
            raise ValueError(msg)
        if self.window is not None:
            low, high = (_ms(m, f"the probe {self.name!r}'s window") for m in self.window)
            if low.value > high.value:
                msg = f"the probe {self.name!r}'s window ends before it starts"
                raise ValueError(msg)
        return self


#: The unit each probe kind's number is in; a spec bounding a probe uses it.
PROBE_UNITS = {"reaction": "ms", "off_state": "1", "exclusive": "1"}


class FirmwareSpec(_Frozen):
    """A firmware task's protocol, scenarios and probes, each referring to the others by name."""

    protocol: Protocol
    scenarios: tuple[Scenario, ...] = Field(min_length=1)
    probes: tuple[Probe, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> FirmwareSpec:
        scenarios = {s.name: s for s in self.scenarios}
        if len(scenarios) != len(self.scenarios) or len({p.name for p in self.probes}) != len(
            self.probes
        ):
            msg = "a scenario or a probe is named twice"
            raise ValueError(msg)
        for probe in self.probes:
            scenario = scenarios.get(probe.scenario)
            if scenario is None:
                msg = f"the probe {probe.name!r} names no scenario of the task"
                raise ValueError(msg)
            if probe.fault is not None and probe.fault not in {f.name for f in scenario.faults}:
                msg = f"the probe {probe.name!r} names no fault of its scenario"
                raise ValueError(msg)
            for actuator, state in (
                (probe.actuator, probe.state),
                (probe.other_actuator, probe.other_state),
            ):
                if actuator is not None and state not in self.protocol.actuators.get(actuator, ()):
                    msg = f"the probe {probe.name!r} names {actuator} {state}, not on the line"
                    raise ValueError(msg)
        return self
