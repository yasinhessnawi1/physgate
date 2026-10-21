"""Write one simulation run's output as a series record, from a role session's own script.

This file is copied, byte for byte, into every run at ``.physgate/lib/series_writer.py``,
where a role session's scripts import it. It runs on the session's interpreter, which may
be as old as Python 3.9 and has only the standard library: nothing here imports anything
else, and a test holds it to that.

**It is a convenience, not the authority.** When the session ends, the orchestrator reads
every record from the session's outbox and validates it against the record schema; that
check decides. This file only spares a role the refusal: it writes the format exactly, and
refuses early what the schema would refuse, except that whether a unit is one the physics
gate's registry knows is the schema's question alone.

**What it records about the code.** The record names the script that ran (the program's
``__main__``) and every file of code the process had loaded from outside the interpreter's
own installation, each with the digest of its bytes now. The interpreter's own site hook
(``sitecustomize`` loaded from its standard library, which Ubuntu links to ``/etc``) is part
of that installation and is not named. Paths inside the worktree are written relative to it;
anything else is written as it is, absolute, and the orchestrator refuses a record whose
code ran from anywhere but the module and the interpreter's own installation. Write the
record after the simulation, from the script that ran it.

Use, from a script under the module directory::

    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
        here = os.path.dirname(here)
    sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
    import series_writer

    series_writer.record(
        "step_nominal",
        title="Position step, nominal case",
        axis="time",
        x=("time", "s", times),
        traces=[("position", "m", xs), ("tilt", "rad", thetas)],
        inputs={"seed": (7, "dimensionless"), "step": (0.1, "m")},
        group="step",
    )

The record lands in ``.physgate/series/<id>.json``. Each id is written once: a second record
under an id already used, from this command or an earlier one, is refused, and the script
records the run under a new id. Nothing in the outbox is read back.

**The extractors.** A quantity read off a record is checked against the record by the
functions at the end of this file, the very ones the orchestrator runs, so a role computes the
value it reports exactly as the check will: ``series_writer.extract("phase_margin", omega=ws,
magnitude=mags, phase=phases)`` on a loop's frequency response (angular frequency in rad/s,
magnitude as a ratio, phase in rad), or ``series_writer.extract("max_abs", values=thetas)`` on a
time trace. Report what this returns on the samples you recorded: a value computed another
way, or on a finer grid than the one recorded, can differ by more than three significant
figures, and is then refused.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import stat
import sys
import sysconfig

#: The format marker, the bounds and the name and unit spellings: the record schema's own,
#: held equal to it by a test.
FORMAT = "series.v1"
MAX_SAMPLES = 100_000
MAX_TRACES = 32
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_RECORDS_PER_SESSION = 256
MAX_SESSION_BYTES = 64 * 1024 * 1024
MAX_INPUTS = 64
MAX_LOADED = 256
MAX_TITLE = 200
MAX_INPUT_INTEGER = 2**63 - 1
NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_UNIT_FACTOR = r"[A-Za-z_\u00b5\u03bc\u03a9]+(?:(?:\*\*|\^)-?[0-9]{1,2})?"
UNIT_GRAMMAR_PATTERN = rf"(?:1|{_UNIT_FACTOR})(?:[ ]*[*/][ ]*{_UNIT_FACTOR})*"

#: Where records go, relative to the worktree.
OUTBOX = os.path.join(".physgate", "series")

_NAME = re.compile(NAME_PATTERN)
_UNIT = re.compile(UNIT_GRAMMAR_PATTERN)


class SeriesWriterError(ValueError):
    """The record cannot be written as given; the message says why."""


def worktree() -> str:
    """The worktree this writer serves: two levels above ``.physgate/lib``.

    Raises:
        SeriesWriterError: this file is not at ``.physgate/lib/series_writer.py``.
    """
    here = os.path.dirname(os.path.realpath(__file__))
    lib, physgate_dir = os.path.basename(here), os.path.basename(os.path.dirname(here))
    if lib != "lib" or physgate_dir != ".physgate":
        msg = "the series writer runs from .physgate/lib in a worktree, and this copy does not"
        raise SeriesWriterError(msg)
    return os.path.dirname(os.path.dirname(here))


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        msg = f"{what} {value!r} is not a lower-case name of letters, digits and underscores"
        raise SeriesWriterError(msg)
    return value


def _unit(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        msg = f"{what} has no unit; every axis carries one"
        raise SeriesWriterError(msg)
    if not _UNIT.fullmatch(value):
        msg = (
            f"{what} has the unit {value!r}, which is not a product of named units with small "
            "integer powers (for example m, rad/s, kg*m/s**2)"
        )
        raise SeriesWriterError(msg)
    return value


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{what} is not a number"
        raise SeriesWriterError(msg)
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number):
        msg = f"{what} is not a finite number"
        raise SeriesWriterError(msg)
    return number


def _column(column: object, what: str) -> dict[str, object]:
    if not isinstance(column, (tuple, list)) or len(column) != 3:
        msg = f"{what} is a (name, unit, values) triple"
        raise SeriesWriterError(msg)
    name, unit, values = column
    _name(name, f"{what}'s name")
    _unit(unit, what)
    if isinstance(values, (str, bytes)) or not hasattr(values, "__len__"):
        msg = f"{what}'s values are a sequence of numbers"
        raise SeriesWriterError(msg)
    if not 1 <= len(values) <= MAX_SAMPLES:
        msg = f"{what} holds between 1 and {MAX_SAMPLES} samples"
        raise SeriesWriterError(msg)
    numbers = [_number(v, f"{what}'s sample {n}") for n, v in enumerate(values)]
    return {"name": name, "unit": unit, "values": numbers}


def _input(name: object, given: object) -> dict[str, object]:
    _name(name, "an input")
    if not isinstance(given, (tuple, list)) or len(given) != 2:
        msg = f"the input {name!r} is a (value, unit) pair"
        raise SeriesWriterError(msg)
    value, unit = given
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"the input {name!r} is not a number"
        raise SeriesWriterError(msg)
    if isinstance(value, int) and abs(value) > MAX_INPUT_INTEGER:
        msg = f"the input {name!r} is an integer larger than {MAX_INPUT_INTEGER}"
        raise SeriesWriterError(msg)
    if isinstance(value, float):
        _number(value, f"the input {name!r}")
    return {"value": value, "unit": _unit(unit, f"the input {name!r}")}


def build(
    record_id: str,
    *,
    title: str,
    axis: str,
    x: object,
    traces: object,
    inputs: object,
    group: object,
    producer: dict[str, object],
) -> bytes:
    """The bytes of a record, or the reason it cannot be one. Pure: it writes nothing.

    Raises:
        SeriesWriterError: an argument is not one the record format admits.
    """
    _name(record_id, "the record id")
    if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
        msg = f"a title is between 1 and {MAX_TITLE} characters"
        raise SeriesWriterError(msg)
    if axis not in ("time", "frequency"):
        msg = "the axis is 'time' or 'frequency'"
        raise SeriesWriterError(msg)
    if group is not None:
        _name(group, "the group")
    x_column = _column(x, "the x axis")
    x_values: list[float] = x_column["values"]  # type: ignore[assignment]
    for n in range(1, len(x_values)):
        if x_values[n] <= x_values[n - 1]:
            msg = "the x axis does not strictly increase"
            raise SeriesWriterError(msg)
    if axis == "frequency" and x_values[0] <= 0:
        msg = "a frequency axis holds only positive frequencies"
        raise SeriesWriterError(msg)
    if isinstance(traces, (str, bytes)) or not isinstance(traces, (tuple, list)):
        msg = "the traces are a list of (name, unit, values) triples"
        raise SeriesWriterError(msg)
    if not 1 <= len(traces) <= MAX_TRACES:
        msg = f"a record holds between 1 and {MAX_TRACES} traces"
        raise SeriesWriterError(msg)
    columns = [_column(trace, f"the trace {n}") for n, trace in enumerate(traces)]
    names = [c["name"] for c in columns]
    if len(set(names)) != len(names):
        msg = "two traces share a name"
        raise SeriesWriterError(msg)
    for column in columns:
        if len(column["values"]) != len(x_values):  # type: ignore[arg-type]
            msg = f"the trace {column['name']!r} does not have one value per x"
            raise SeriesWriterError(msg)
    given = {} if inputs is None else inputs
    if not isinstance(given, dict) or len(given) > MAX_INPUTS:
        msg = f"the inputs are a mapping of at most {MAX_INPUTS} (value, unit) pairs"
        raise SeriesWriterError(msg)
    record: dict[str, object] = {
        "format": FORMAT,
        "id": record_id,
        "title": title,
        "group": group,
        "axis": axis,
        "x": x_column,
        "traces": columns,
        "inputs": {name: _input(name, pair) for name, pair in given.items()},
        "producer": producer,
    }
    data = json.dumps(record, allow_nan=False, ensure_ascii=True).encode("ascii")
    if len(data) > MAX_FILE_BYTES:
        msg = f"the record is {len(data)} bytes; a record holds at most {MAX_FILE_BYTES}"
        raise SeriesWriterError(msg)
    return data


def _interpreter_roots() -> list[str]:
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    paths = sysconfig.get_paths()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        if key in paths:
            roots.add(paths[key])
    return sorted({os.path.realpath(root) for root in roots if root})


def _standard_library() -> set[str]:
    """The interpreter's standard-library directories, as its paths spell them and as they are."""
    paths = sysconfig.get_paths()
    found = {paths[key] for key in ("stdlib", "platstdlib") if paths.get(key)}
    return {spelling for d in found for spelling in (os.path.abspath(d), os.path.realpath(d))}


def _own_site_hook(name: str, found: str, standard_library: set[str]) -> bool:
    """Whether ``found`` is the interpreter's own site hook, loaded from its standard library.

    A distribution may keep that file outside the installation and link it in: Debian and
    Ubuntu link ``<stdlib>/sitecustomize.py`` to ``/etc/python3.X/sitecustomize.py``, which
    then runs in every process. It is judged by the place it was loaded from, not by where
    the link leads; the same module found anywhere else is named like any other code.
    """
    return name == "sitecustomize" and os.path.dirname(os.path.abspath(found)) in standard_library


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _code_file(path: str, base: str) -> dict[str, str]:
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    shown = os.path.relpath(path, base).replace(os.sep, "/") if _under(path, base) else path
    return {"path": shown, "sha256": digest}


def producer(base: str) -> dict[str, object]:
    """The code that is producing a record now: the running script, and what it loaded.

    Raises:
        SeriesWriterError: there is no script (an interactive session or ``-c``), or more
            files of code are loaded than a record may name.
    """
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    if not main:
        msg = "a record is written from a script file, and this process runs none"
        raise SeriesWriterError(msg)
    script = os.path.realpath(main)
    roots = _interpreter_roots()
    standard_library = _standard_library()
    loaded = set()
    for name, module in list(sys.modules.items()):
        found = getattr(module, "__file__", None)
        if not isinstance(found, str) or _own_site_hook(name, found, standard_library):
            continue
        path = os.path.realpath(found)
        if path == script or any(_under(path, root) for root in roots):
            continue
        if os.path.isfile(path):
            loaded.add(path)
    if len(loaded) > MAX_LOADED:
        msg = f"the process loaded {len(loaded)} files of code; a record names at most {MAX_LOADED}"
        raise SeriesWriterError(msg)
    return {
        "script": _code_file(script, base),
        "loaded": [_code_file(path, base) for path in sorted(loaded)],
    }


#: How a record is opened: made new, in the outbox itself, never through a link. A name already
#: there is never written through, whoever put it there.
_CREATE = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _write_all(fd: int, data: bytes) -> None:
    """Write ``data`` to ``fd`` and sync it, then close it."""
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _make_outbox(outbox: str) -> None:
    """Make the outbox if it is missing, without reading it.

    ``os.makedirs`` with ``exist_ok`` looks at a directory that already exists, and the
    outbox may not be looked at: an existing one is taken as found, and the write into it
    says whether it is a directory.
    """
    os.makedirs(os.path.dirname(outbox), exist_ok=True)
    with contextlib.suppress(FileExistsError):
        os.mkdir(outbox)


def _taken(record_id: str) -> SeriesWriterError:
    return SeriesWriterError(
        f"the record {record_id!r} is already in the outbox, and a record is never written "
        "over: record this run under a new id"
    )


def _open_new(final: str, record_id: str) -> int:
    """Make the record's file, new and empty, in the outbox; return it open for writing.

    Raises:
        SeriesWriterError: something is already at its name, or the file made there has a
            second name somewhere (another name could read what is written into it).
    """
    try:
        fd = os.open(final, _CREATE, 0o644)
    except FileExistsError:
        raise _taken(record_id) from None
    try:
        try:
            made = os.fstat(fd)
        except PermissionError:
            if sys.platform != "darwin":
                raise
            # Seatbelt denies the outbox whole, the metadata of an entry included, even
            # through the descriptor that made it. There nothing can add a name to an entry
            # either: linking one out, or opening it, is refused to every process of the
            # session (measured on Claude Code 2.1.301, from the writing command and from a
            # process that outlived an earlier one).
            return fd
        if not stat.S_ISREG(made.st_mode) or made.st_nlink != 1:
            msg = (
                f"the file made for the record {record_id!r} has {made.st_nlink} names, and "
                "another name could read what is written: nothing was written, and the record "
                "is refused when the session ends; record this run under a new id"
            )
            raise SeriesWriterError(msg)
    except BaseException:
        os.close(fd)
        raise
    return fd


def record(
    record_id: str,
    *,
    title: str,
    axis: str,
    x: object,
    traces: object,
    inputs: object = None,
    group: object = None,
) -> str:
    """Write one record into the worktree's outbox; return its path.

    The outbox is written blind: nothing in it is listed, looked at or read back, because a
    role session's shell may not read it. The record's file is made new in the outbox, empty,
    and checked to have no other name before anything is written into it; only then are the
    bytes written and synced. A record cut short is refused when the session ends. An id is
    written once: a name already in the outbox is never written through or replaced.

    The session's bounds on the count and the bytes of its records
    (:data:`MAX_RECORDS_PER_SESSION`, :data:`MAX_SESSION_BYTES`) are the collector's alone to
    hold, and a record beyond them is set aside there.

    Raises:
        SeriesWriterError: the record is not one the format admits, or its id is taken.
    """
    base = worktree()
    data = build(
        record_id,
        title=title,
        axis=axis,
        x=x,
        traces=traces,
        inputs=inputs,
        group=group,
        producer=producer(base),
    )
    outbox = os.path.join(base, OUTBOX)
    _make_outbox(outbox)
    final = os.path.join(outbox, record_id + ".json")
    _write_all(_open_new(final, record_id), data)
    return final


# ── extractors: reading a quantity off a record's own samples ─────────────────────────────

FREQUENCY_EXTRACTORS = (
    "phase_margin",
    "gain_crossover_frequency",
    "gain_margin_upper",
    "gain_margin_lower",
    "stability_margin",
    "sensitivity_peak",
    "complementary_sensitivity_peak",
    "delay_margin",
)
TIME_EXTRACTORS = ("max", "min", "max_abs", "final")


def _unwrapped(phase: list[float]) -> list[float]:
    out = [phase[0]]
    for value in phase[1:]:
        step = value - out[-1]
        step -= 2 * math.pi * round(step / (2 * math.pi))
        out.append(out[-1] + step)
    return out


def _wrapped(angle: float) -> float:
    """``angle`` in (-pi, pi]."""
    folded = math.fmod(angle + math.pi, 2 * math.pi)
    if folded <= 0:
        folded += 2 * math.pi
    return folded - math.pi


def _gain_crossings(
    omega: list[float], magnitude: list[float], phase: list[float]
) -> list[tuple[float, float]]:
    """Every (angular frequency, phase margin) where the loop's magnitude crosses one.

    Between two samples the crossing is interpolated linearly in log frequency, its place set
    by the log of the magnitude, and the unwrapped phase is interpolated at that place; a
    sample at exactly one is a crossing of its own.
    """
    phases = _unwrapped(phase)
    logs = [math.log(m) for m in magnitude]
    found: list[tuple[float, float]] = []
    for k in range(len(omega)):
        a = logs[k]
        if a == 0:
            found.append((omega[k], _wrapped(math.pi + phases[k])))
            continue
        if k + 1 < len(omega):
            b = logs[k + 1]
            if b != 0 and a * b < 0:
                t = a / (a - b)
                lw = math.log(omega[k]) + t * (math.log(omega[k + 1]) - math.log(omega[k]))
                at = phases[k] + t * (phases[k + 1] - phases[k])
                found.append((math.exp(lw), _wrapped(math.pi + at)))
    return found


def _phase_crossing_gain_margins(magnitude: list[float], phase: list[float]) -> list[float]:
    """Every gain margin: one over the magnitude where the unwrapped phase crosses an odd pi."""
    phases = _unwrapped(phase)
    logs = [math.log(m) for m in magnitude]
    margins: list[float] = []
    for k in range(len(phases) - 1):
        lo, hi = sorted((phases[k], phases[k + 1]))
        first = math.ceil((lo - math.pi) / (2 * math.pi))
        last = math.floor((hi - math.pi) / (2 * math.pi))
        for n in range(first, last + 1):
            target = math.pi + 2 * math.pi * n
            if phases[k + 1] == phases[k]:
                continue
            if target == phases[k + 1] and k + 2 < len(phases):
                continue  # counted at the next segment's start
            t = (target - phases[k]) / (phases[k + 1] - phases[k])
            margins.append(1.0 / math.exp(logs[k] + t * (logs[k + 1] - logs[k])))
    return margins


def _need(found: list[float], what: str) -> list[float]:
    if not found:
        msg = f"the record shows no {what} on its grid, so the value cannot be read off it"
        raise SeriesWriterError(msg)
    return found


def extract(
    name: str,
    *,
    omega: object = None,
    magnitude: object = None,
    phase: object = None,
    values: object = None,
) -> float:
    """The value the extractor ``name`` reads off a record's samples.

    Frequency extractors take ``omega`` (rad/s), ``magnitude`` (a ratio) and ``phase`` (rad);
    time extractors take a trace's ``values``.

    Raises:
        SeriesWriterError: the extractor is not one of the set, its samples are missing or
            not finite, or what it reads is not on the record's grid.
    """
    if name in TIME_EXTRACTORS:
        trace = [_number(v, "a sample") for v in _sequence(values, "values")]
        if name == "max":
            return max(trace)
        if name == "min":
            return min(trace)
        if name == "max_abs":
            return max(abs(v) for v in trace)
        return trace[-1]
    if name not in FREQUENCY_EXTRACTORS:
        msg = f"{name!r} is not an extractor"
        raise SeriesWriterError(msg)
    ws = [_number(v, "a frequency") for v in _sequence(omega, "omega")]
    ms = [_number(v, "a magnitude") for v in _sequence(magnitude, "magnitude")]
    ps = [_number(v, "a phase") for v in _sequence(phase, "phase")]
    if not len(ws) == len(ms) == len(ps):
        msg = "omega, magnitude and phase have one value each per sample"
        raise SeriesWriterError(msg)
    if any(w <= 0 for w in ws) or any(m <= 0 for m in ms):
        msg = "frequencies and magnitudes are positive"
        raise SeriesWriterError(msg)
    if name in ("stability_margin", "sensitivity_peak", "complementary_sensitivity_peak"):
        # Indexed rather than zipped: zip's strict check arrived after Python 3.9.
        distances = [
            math.hypot(1 + ms[k] * math.cos(ps[k]), ms[k] * math.sin(ps[k])) for k in range(len(ms))
        ]
        if name == "stability_margin":
            return min(distances)
        if name == "sensitivity_peak":
            return max(1 / d for d in distances)
        return max(ms[k] / distances[k] for k in range(len(ms)))
    if name in ("gain_margin_upper", "gain_margin_lower"):
        margins = _phase_crossing_gain_margins(ms, ps)
        if name == "gain_margin_upper":
            return min(_need([g for g in margins if g > 1], "phase crossing above unit gain"))
        return max(_need([g for g in margins if g < 1], "phase crossing below unit gain"))
    crossings = _gain_crossings(ws, ms, ps)
    if not crossings:
        _need([], "gain crossover")
    worst = min(crossings, key=lambda c: c[1])
    if name == "phase_margin":
        return worst[1]
    if name == "gain_crossover_frequency":
        return worst[0]
    return min(pm / w for w, pm in crossings)


def _sequence(value: object, what: str) -> list[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or not value:
        msg = f"{what} is a non-empty list of numbers"
        raise SeriesWriterError(msg)
    return list(value)
