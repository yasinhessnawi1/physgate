"""Reading a quantity off a sealed record, by the extractor its reference names.

The arithmetic is the series writer's own (:func:`physgate.series.writer.extract`), the very
functions a role's script calls from the run's copy of that file, so the value a role reports
and the value it is checked against are computed by one implementation. This module maps a
record and a reference onto those functions, holding units strictly: a loop's frequency
response is read only with its angular frequency in ``rad/s`` (or ``Hz``, converted by an
explicit factor of two pi, never by the unit registry, which would convert one to the other
as if they were equal), its magnitude as a plain ratio, and its phase in ``rad`` (or ``deg``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from physgate.series import writer
from physgate.series.exceptions import SeriesError
from physgate.series.record import Column, Record
from physgate.state.schema import TIME_EXTRACTORS, SeriesRef

#: The traces a loop's frequency response is recorded in.
MAGNITUDE_TRACE = "loop_magnitude"
PHASE_TRACE = "loop_phase"
#: The units each axis of a frequency response may carry, and the factor into the one read.
FREQUENCY_FACTORS = {"rad/s": 1.0, "Hz": 2 * math.pi}
MAGNITUDE_UNITS = frozenset({"dimensionless", "1"})
PHASE_FACTORS = {"rad": 1.0, "radian": 1.0, "deg": math.pi / 180, "degree": math.pi / 180}
#: The unit of the value each frequency extractor reads.
FREQUENCY_UNITS = {
    "phase_margin": "rad",
    "gain_crossover_frequency": "rad/s",
    "delay_margin": "s",
    "gain_margin_upper": "dimensionless",
    "gain_margin_lower": "dimensionless",
    "stability_margin": "dimensionless",
    "sensitivity_peak": "dimensionless",
    "complementary_sensitivity_peak": "dimensionless",
}


class ExtractionError(SeriesError):
    """The value a reference names cannot be read off the record it names."""


@dataclass(frozen=True)
class Extracted:
    """A value read off a record, with its unit."""

    value: float
    unit: str


def _trace(record: Record, name: str) -> Column:
    for trace in record.traces:
        if trace.name == name:
            return trace
    msg = f"the record {record.id} has no trace {name!r}"
    raise ExtractionError(msg, record=record.id, trace=name)


def read_off(record: Record, reference: SeriesRef) -> Extracted:
    """The value ``reference`` reads off ``record``, with its unit.

    Raises:
        ExtractionError: the record is not the kind the extractor reads, a trace it needs is
            missing or in another unit, or what it reads is not on the record's grid.
    """
    try:
        if reference.extract in TIME_EXTRACTORS:
            assert reference.trace is not None  # the reference's own validation holds this
            trace = _trace(record, reference.trace)
            value = writer.extract(reference.extract, values=list(trace.values))
            return Extracted(value=value, unit=trace.unit)
        if record.axis != "frequency":
            msg = (
                f"{reference.extract} reads a frequency response, and {record.id} is a "
                f"{record.axis} record"
            )
            raise ExtractionError(msg, record=record.id)
        magnitude, phase = _trace(record, MAGNITUDE_TRACE), _trace(record, PHASE_TRACE)
        x_factor = FREQUENCY_FACTORS.get(record.x.unit)
        p_factor = PHASE_FACTORS.get(phase.unit)
        if x_factor is None or magnitude.unit not in MAGNITUDE_UNITS or p_factor is None:
            msg = (
                f"{reference.extract} reads angular frequency in rad/s or Hz, the magnitude as a "
                f"ratio and the phase in rad or deg; {record.id} gives {record.x.unit}, "
                f"{magnitude.unit} and {phase.unit}"
            )
            raise ExtractionError(msg, record=record.id)
        value = writer.extract(
            reference.extract,
            omega=[w * x_factor for w in record.x.values],
            magnitude=list(magnitude.values),
            phase=[p * p_factor for p in phase.values],
        )
        return Extracted(value=value, unit=FREQUENCY_UNITS[reference.extract])
    except writer.SeriesWriterError as exc:
        raise ExtractionError(str(exc), record=record.id) from None
