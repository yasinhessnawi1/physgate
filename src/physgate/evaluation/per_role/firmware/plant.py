"""The simulated plant a firmware task's scenarios run: deterministic, stepped, one rule.

Each plant variable is an integrator of its own: on every step of ``dt`` it moves by the
sum of the rates of the actuator states that drive it, less a leak towards its resting
value, and is clamped to its range. The firmware sees it as the sensor of the same name in
capitals, sent as a whole number. Identical inputs give identical trajectories, so a trace
is reproducible from the actuator lines alone.

A scenario's parameters name, per variable ``v``:

- ``v_rate_<ACTUATOR>_<STATE>``: the rate (per second, in ``v``'s unit) while that actuator
  is in that state; any number of them;
- ``v_leak`` (``1/s``) and ``v_rest``: the pull back towards rest;
- ``v_min`` and ``v_max``: the range.

and its ``initial`` gives each variable's start. Every one is a measure with its unit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from physgate.evaluation.per_role.base import NamedMeasure
from physgate.evaluation.per_role.exceptions import TaskFormatError

_RATE = re.compile(
    r"^(?P<var>[a-z][a-z0-9]*)_rate_(?P<act>[a-z][a-z0-9_]*?)_(?P<state>[a-z][a-z0-9]*)$"
)


class Plant:
    """A plant built from a scenario's parameters and initial values."""

    def __init__(self, params: tuple[NamedMeasure, ...], initial: tuple[NamedMeasure, ...]) -> None:
        """Read every variable's range, rest, leak and rates.

        Raises:
            TaskFormatError: a variable lacks a part, or a part's unit disagrees.
        """
        by_name = {p.name: p for p in params}
        self.values: dict[str, float] = {m.name: float(m.value) for m in initial}
        self.units: dict[str, str] = {m.name: m.unit for m in initial}
        self._rates: dict[str, list[tuple[str, str, float]]] = {v: [] for v in self.values}
        self._range: dict[str, tuple[float, float]] = {}
        self._leak: dict[str, tuple[float, float]] = {}
        for name, measure in by_name.items():
            rate = _RATE.match(name)
            if rate is None:
                continue
            var = rate["var"]
            if var not in self.values:
                msg = f"the rate {name!r} drives {var!r}, which has no initial value"
                raise TaskFormatError(msg, param=name)
            if measure.unit != f"{self.units[var]}/s":
                msg = f"the rate {name!r} is in {measure.unit!r}; it is in {self.units[var]}/s"
                raise TaskFormatError(msg, param=name)
            self._rates[var].append(
                (rate["act"].upper(), rate["state"].upper(), float(measure.value))
            )
        for var, unit in self.units.items():
            try:
                low, high = by_name[f"{var}_min"], by_name[f"{var}_max"]
                leak, rest = by_name[f"{var}_leak"], by_name[f"{var}_rest"]
            except KeyError as exc:
                msg = f"the plant variable {var!r} lacks {exc.args[0]!r}"
                raise TaskFormatError(msg, variable=var) from exc
            for part in (low, high, rest):
                if part.unit != unit:
                    msg = f"{part.name!r} is in {part.unit!r}, not {var!r}'s {unit!r}"
                    raise TaskFormatError(msg, variable=var)
            if leak.unit != "1/s" or float(low.value) > float(high.value):
                msg = f"the plant variable {var!r} has a leak not in 1/s or an empty range"
                raise TaskFormatError(msg, variable=var)
            self._range[var] = (float(low.value), float(high.value))
            self._leak[var] = (float(leak.value), float(rest.value))

    def step(self, dt_s: float, actuators: Mapping[str, str]) -> None:
        """Advance every variable by ``dt_s`` seconds under the actuators' current states."""
        for var, value in self.values.items():
            drive = sum(
                rate for act, state, rate in self._rates[var] if actuators.get(act) == state
            )
            leak, rest = self._leak[var]
            moved = value + dt_s * (drive - leak * (value - rest))
            low, high = self._range[var]
            self.values[var] = min(max(moved, low), high)

    def frames(self) -> list[str]:
        """The sensor frames the plant sends now, one per variable, as whole numbers."""
        return [f"SENSE {var.upper()} {round(value)}" for var, value in sorted(self.values.items())]
