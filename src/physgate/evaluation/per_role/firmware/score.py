"""A firmware task's score: a pure function of its scenarios' traces.

Each probe reads one number off one scenario's trace (:mod:`.spec`), and each headline
spec bounds one probe; the same traces always give the same score. A firmware answer is run
three times, each a full set of scenarios, and the three scores must agree: a split is
``flaky`` and counts as a fail, for either arm alike, until the runs can be made
deterministic in virtual time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.firmware.loop import ACT_LINE, Trace
from physgate.evaluation.per_role.firmware.spec import PROBE_UNITS, FirmwareSpec, Probe
from physgate.evaluation.per_role.task import Spec, Task

Verdict = Literal["pass", "fail", "flaky"]
RUNS = 3


def _states(trace: Trace) -> list[tuple[float, str, str]]:
    """Every actuator state the device set, in the order it arrived."""
    found: list[tuple[float, str, str]] = []
    for line in trace.lines:
        if line.direction == "from_device":
            matched = ACT_LINE.match(line.text)
            if matched:
                found.append((line.t_ms, matched[1], matched[2]))
    return found


def _reaction(trace: Trace, probe: Probe, spec: FirmwareSpec) -> float | None:
    scenario = next(s for s in spec.scenarios if s.name == probe.scenario)
    fault = next(f for f in scenario.faults if f.name == probe.fault)
    start = float(fault.at.value)
    for t, actuator, state in _states(trace):
        if t >= start and actuator == probe.actuator and state == probe.state:
            return t - start
    return None


def _state_at(states: list[tuple[float, str, str]], actuator: str, t: float) -> str | None:
    current = None
    for at, name, state in states:
        if at > t:
            break
        if name == actuator:
            current = state
    return current


def _off_state(trace: Trace, probe: Probe) -> float:
    assert probe.window is not None and probe.actuator is not None
    low, high = (float(m.value) for m in probe.window)
    states = _states(trace)
    count = 1 if _state_at(states, probe.actuator, low) == probe.state else 0
    count += sum(
        1
        for t, name, state in states
        if low < t <= high and name == probe.actuator and state == probe.state
    )
    return float(count)


def _exclusive(trace: Trace, probe: Probe) -> float:
    assert probe.actuator is not None and probe.other_actuator is not None
    current: dict[str, str] = {}
    together = False
    count = 0
    for _, name, state in _states(trace):
        current[name] = state
        now = (
            current.get(probe.actuator) == probe.state
            and current.get(probe.other_actuator) == probe.other_state
        )
        if now and not together:
            count += 1
        together = now
    return float(count)


def _peak(trace: Trace, probe: Probe) -> float | None:
    assert probe.variable is not None
    values = [sample[probe.variable] for _, sample in trace.samples if probe.variable in sample]
    return max(values) if values else None


def probe_value(probe: Probe, traces: Mapping[str, Trace], spec: FirmwareSpec) -> float | None:
    """The number ``probe`` reads off its scenario's trace; ``None`` where there is none."""
    trace = traces.get(probe.scenario)
    if trace is None:
        return None
    if probe.kind == "reaction":
        return _reaction(trace, probe, spec)
    if probe.kind == "off_state":
        return _off_state(trace, probe)
    if probe.kind == "exclusive":
        return _exclusive(trace, probe)
    return _peak(trace, probe)


def _held(spec: Spec, value: float | None) -> bool:
    if value is None or math.isnan(value):
        return False
    bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
    limits = [float(b.value) for b in bounds]
    if spec.op == "in":
        return limits[0] <= value <= limits[1]
    return {
        ">=": value >= limits[0],
        "<=": value <= limits[0],
        ">": value > limits[0],
        "<": value < limits[0],
    }[spec.op]


def probe_unit(probe: Probe, spec: FirmwareSpec) -> str:
    """The unit a probe's number is in: its kind's, or for a peak its variable's."""
    if probe.kind != "plant_peak":
        return PROBE_UNITS[probe.kind]
    scenario = next(s for s in spec.scenarios if s.name == probe.scenario)
    return next(m.unit for m in scenario.initial if m.name == probe.variable)


def require_known_probes(task: Task) -> FirmwareSpec:
    """The task's firmware section, refused unless every spec bounds a probe in its unit.

    Raises:
        TaskFormatError: no firmware section, a spec naming no probe, a bound in another
            unit, or a plant whose sensors are not the protocol's.
    """
    if task.firmware is None:
        msg = f"the task {task.id!r} has no firmware section"
        raise TaskFormatError(msg, task=task.id)
    spec = task.firmware
    probes = {p.name: p for p in spec.probes}
    for item in task.specs:
        probe = probes.get(item.metric)
        if probe is None:
            msg = f"the spec {item.name!r} bounds {item.metric!r}, which is no probe of the task"
            raise TaskFormatError(msg, task=task.id)
        unit = probe_unit(probe, spec)
        bounds = item.bound if isinstance(item.bound, tuple) else (item.bound,)
        if any(b.unit != unit for b in bounds):
            msg = f"the spec {item.name!r} bounds {item.metric!r} in another unit than {unit!r}"
            raise TaskFormatError(msg, task=task.id)
    for scenario in spec.scenarios:
        sensors = sorted(m.name.upper() for m in scenario.initial)
        if sensors != sorted(spec.protocol.sensors):
            msg = f"the scenario {scenario.name!r}'s plant does not send the protocol's sensors"
            raise TaskFormatError(msg, task=task.id)
    return spec


def score(task: Task, traces: Mapping[str, Trace]) -> dict[str, Any]:
    """The score of one run's traces against ``task``: each spec's probe value and pass."""
    spec = require_known_probes(task)
    probes = {p.name: p for p in spec.probes}
    rows = []
    for item in task.specs:
        probe = probes[item.metric]
        value = probe_value(probe, traces, spec)
        unit = probe_unit(probe, spec)
        rows.append(
            {
                "name": item.name,
                "metric": item.metric,
                "counts": item.counts,
                "measured": None if value is None else {"value": value, "unit": unit},
                "passed": _held(item, value),
            }
        )
    limits = sorted({t.limit for t in traces.values() if t.limit is not None})
    violations = protocol_violations(spec, traces)
    passed = (
        not limits
        and not violations
        and all(row["passed"] for row in rows if row["counts"] == "headline")
    )
    return {
        "task": task.id,
        "specs": rows,
        "passed": passed,
        "limit": limits,
        "violations": violations,
    }


def protocol_violations(spec: FirmwareSpec, traces: Mapping[str, Trace]) -> list[str]:
    """Every actuator line the device sent that the protocol does not have.

    A line that does not begin ``ACT`` is not an actuator line (a boot banner, a log line)
    and is ignored; one that does must name an actuator and a state of the protocol, or the
    answer has broken the protocol it was given.
    """
    found: list[str] = []
    for name, trace in sorted(traces.items()):
        for line in trace.lines:
            if line.direction != "from_device" or not line.text.startswith("ACT"):
                continue
            matched = ACT_LINE.match(line.text)
            states = spec.protocol.actuators.get(matched[1], ()) if matched else ()
            if matched is None or matched[2] not in states:
                shown = line.text[:60]
                found.append(
                    f"{name}: line {line.seq} is no actuator line of the protocol: {shown!r}"
                )
    return found


def safe_score(task: Task, traces: Mapping[str, Trace]) -> dict[str, Any]:
    """:func:`score`, except that anything going wrong is this answer's recorded fail.

    One answer whose traces break the scorer fails alone; the run goes on scoring the rest.
    """
    try:
        return score(task, traces)
    except Exception as exc:  # noqa: BLE001 - one answer may not take the run down
        return {"task": task.id, "specs": [], "passed": False, "error": repr(exc)[:400]}


def verdict(scores: Sequence[Mapping[str, Any]]) -> Verdict:
    """The answer's verdict from its runs' scores: all pass, all fail, or flaky.

    Raises:
        ValueError: not exactly :data:`RUNS` runs were scored.
    """
    if len(scores) != RUNS:
        msg = f"a firmware answer is scored on {RUNS} runs, not {len(scores)}"
        raise ValueError(msg)
    outcomes = {bool(s["passed"]) for s in scores}
    if outcomes == {True}:
        return "pass"
    if outcomes == {False}:
        return "fail"
    return "flaky"
