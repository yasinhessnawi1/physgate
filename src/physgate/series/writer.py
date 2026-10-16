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
own installation, each with the digest of its bytes now. Paths inside the worktree are
written relative to it; anything else is written as it is, absolute, and the orchestrator
refuses a record whose code ran from outside the module. Write the record after the
simulation, from the script that ran it.

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

The record lands in ``.physgate/series/<id>.json``, written whole or not at all.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
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
_UNIT_FACTOR = r"[A-Za-z_]+(?:(?:\*\*|\^)-?[0-9]{1,2})?"
UNIT_GRAMMAR_PATTERN = rf"^(?:1|{_UNIT_FACTOR})(?:\s*[*/]\s*{_UNIT_FACTOR})*$"

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
    if not isinstance(value, str) or not _NAME.match(value):
        msg = f"{what} {value!r} is not a lower-case name of letters, digits and underscores"
        raise SeriesWriterError(msg)
    return value


def _unit(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        msg = f"{what} has no unit; every axis carries one"
        raise SeriesWriterError(msg)
    if not _UNIT.match(value):
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
    loaded = set()
    for module in list(sys.modules.values()):
        found = getattr(module, "__file__", None)
        if not isinstance(found, str):
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
    """Write one record into the worktree's outbox, whole or not at all; return its path.

    Raises:
        SeriesWriterError: the record is not one the format admits, or the outbox is full.
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
    os.makedirs(outbox, exist_ok=True)
    final = os.path.join(outbox, record_id + ".json")
    others = [
        os.path.join(outbox, name)
        for name in os.listdir(outbox)
        if name.endswith(".json") and not name.startswith(".") and name != record_id + ".json"
    ]
    if len(others) + 1 > MAX_RECORDS_PER_SESSION:
        msg = f"a session leaves at most {MAX_RECORDS_PER_SESSION} records"
        raise SeriesWriterError(msg)
    if sum(os.path.getsize(path) for path in others) + len(data) > MAX_SESSION_BYTES:
        msg = f"a session's records hold at most {MAX_SESSION_BYTES} bytes together"
        raise SeriesWriterError(msg)
    temporary = os.path.join(outbox, f".{record_id}.json.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise
    return final
