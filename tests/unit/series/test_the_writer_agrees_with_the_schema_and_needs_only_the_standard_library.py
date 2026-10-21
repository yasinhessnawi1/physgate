"""The writer refuses what the schema refuses, writes what it admits, and runs on Python 3.9 alone.

The writer is a convenience and the schema is the authority, so two validators exist. They
are held together here: on every case below, generated and hand-written, the writer refuses
exactly when the schema does, except for three questions the writer cannot ask without the
unit registry, which are listed and asserted as the schema's alone.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import random
import struct
from collections.abc import Callable
from typing import Any

import pytest

import physgate.series.writer as writer
from physgate import unit_spelling
from physgate.series import record as schema
from physgate.series.exceptions import RecordRefusedError
from physgate.series.record import parse_record
from physgate.series.writer import SeriesWriterError, build

PRODUCER: dict[str, object] = {
    "script": {"path": "modules/control/sim.py", "sha256": "0" * 64},
    "loaded": [],
}

Args = dict[str, Any]


def _base() -> Args:
    return {
        "record_id": "step_nominal",
        "title": "Fixture, not a simulation result",
        "axis": "time",
        "x": ("time", "s", [0.0, 0.01, 0.02]),
        "traces": [("position", "m", [0.0, 0.02, 0.05]), ("tilt", "rad", [0.0, -0.01, 0.0])],
        "inputs": {"seed": (7, "dimensionless")},
        "group": "step",
    }


def _as_record(args: Args) -> dict[str, Any]:
    """The record ``args`` describe, spelt without any check the writer makes."""

    def column(triple: Any) -> Any:
        if not isinstance(triple, tuple | list) or len(triple) != 3:
            return triple
        name, unit, values = triple
        return {"name": name, "unit": unit, "values": list(values)}

    inputs = args["inputs"] or {}
    return {
        "format": schema.FORMAT,
        "id": args["record_id"],
        "title": args["title"],
        "group": args["group"],
        "axis": args["axis"],
        "x": column(args["x"]),
        "traces": [column(t) for t in args["traces"]],
        "inputs": {k: {"value": v[0], "unit": v[1]} for k, v in inputs.items()},
        "producer": PRODUCER,
    }


def _writer_says(args: Args) -> bytes | None:
    try:
        return build(
            args["record_id"],
            title=args["title"],
            axis=args["axis"],
            x=args["x"],
            traces=args["traces"],
            inputs=args["inputs"],
            group=args["group"],
            producer=PRODUCER,
        )
    except SeriesWriterError:
        return None


def _schema_says(args: Args) -> bool:
    try:
        parse_record(json.dumps(_as_record(args), allow_nan=True).encode())
    except RecordRefusedError:
        return False
    return True


def _with(change: Callable[[Args], None]) -> Args:
    args = copy.deepcopy(_base())
    change(args)
    return args


def _sample(value: Any) -> Callable[[Args], None]:
    def change(args: Args) -> None:
        args["traces"][0][2][1] = value

    return change


CASES: dict[str, Callable[[Args], None]] = {
    "well formed": lambda a: None,
    "nan sample": _sample(math.nan),
    "infinite sample": _sample(math.inf),
    "boolean sample": _sample(True),
    "string sample": _sample("0.02"),
    "integer sample": _sample(1),
    "huge integer sample": _sample(10**400),
    "x repeats": lambda a: a.update(x=("time", "s", [0.0, 0.0, 0.02])),
    "x decreases": lambda a: a.update(x=("time", "s", [0.0, 0.02, 0.01])),
    "short trace": lambda a: a["traces"].__setitem__(0, ("position", "m", [0.0, 0.1])),
    "two traces one name": lambda a: a["traces"].__setitem__(1, ("position", "rad", [0, 0, 0])),
    "no traces": lambda a: a.update(traces=[]),
    "too many traces": lambda a: a.update(
        traces=[(f"t{n}", "m", [0.0, 0.0, 0.0]) for n in range(schema.MAX_TRACES + 1)]
    ),
    "bad id": lambda a: a.update(record_id="Step"),
    "bad group": lambda a: a.update(group="Step-1"),
    "bad trace name": lambda a: a["traces"].__setitem__(0, ("Pos", "m", [0, 0, 0])),
    "empty unit": lambda a: a["traces"].__setitem__(0, ("position", " ", [0, 0, 0])),
    "arithmetic in a unit": lambda a: a["traces"].__setitem__(0, ("position", "1000*m", [0, 0, 0])),
    "no samples": lambda a: a.update(x=("time", "s", []), traces=[("p", "m", [])]),
    "bad axis": lambda a: a.update(axis="space"),
    "empty title": lambda a: a.update(title=""),
    "long title": lambda a: a.update(title="t" * (schema.MAX_TITLE + 1)),
    "zero frequency": lambda a: a.update(axis="frequency", x=("w", "rad/s", [0.0, 1.0, 2.0])),
    "frequency axis": lambda a: a.update(axis="frequency", x=("w", "rad/s", [0.1, 1.0, 2.0])),
    "huge integer input": lambda a: a.update(inputs={"seed": (10**400, "dimensionless")}),
    "64-bit input": lambda a: a.update(inputs={"seed": (2**63 - 1, "dimensionless")}),
    "boolean input": lambda a: a.update(inputs={"seed": (True, "dimensionless")}),
    "nan input": lambda a: a.update(inputs={"seed": (math.nan, "dimensionless")}),
    "bad input name": lambda a: a.update(inputs={"Seed": (7, "dimensionless")}),
    "input without unit": lambda a: a.update(inputs={"seed": (7, "")}),
    "too many inputs": lambda a: a.update(
        inputs={f"i{n}": (n, "m") for n in range(schema.MAX_INPUTS + 1)}
    ),
    "no inputs": lambda a: a.update(inputs=None),
}

#: What only the unit registry can answer, so only the schema asks it.
SCHEMA_ALONE: dict[str, Callable[[Args], None]] = {
    "a unit the registry does not know": lambda a: a["traces"].__setitem__(
        0, ("position", "furlong_bogus", [0, 0, 0])
    ),
    "a logarithmic unit": lambda a: a["traces"].__setitem__(0, ("position", "dB", [0, 0, 0])),
    "a time axis not in time": lambda a: a.update(x=("time", "m", [0.0, 0.01, 0.02])),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_writer_refuses_exactly_what_the_schema_refuses(case: str) -> None:
    args = _with(CASES[case])
    written = _writer_says(args)
    assert (written is not None) == _schema_says(args), case
    if written is not None:
        parse_record(written)


@pytest.mark.parametrize("case", sorted(SCHEMA_ALONE))
def test_what_only_the_registry_can_answer_is_left_to_the_schema(case: str) -> None:
    args = _with(SCHEMA_ALONE[case])
    assert _writer_says(args) is not None
    assert not _schema_says(args)


def test_generated_records_are_written_and_read_back_exactly() -> None:
    rng = random.Random(16102026)
    for _ in range(200):
        n = rng.randint(1, 300)
        times = sorted({rng.uniform(0, 10) for _ in range(n)})
        traces = [
            (f"t{k}", rng.choice(["m", "rad", "V", "m/s", "dimensionless"]),
             [rng.choice([rng.uniform(-1e3, 1e3), rng.randint(-5, 5), 0.0]) for _ in times])
            for k in range(rng.randint(1, 5))
        ]  # fmt: skip
        args = copy.deepcopy(_base())
        args.update(x=("time", "s", times), traces=traces)
        written = _writer_says(args)
        assert written is not None
        record = parse_record(written)
        for trace, (_, _, values) in zip(record.traces, traces, strict=True):
            assert [struct.pack("<d", v) for v in trace.values] == [
                struct.pack("<d", float(v)) for v in values
            ]


def test_the_writer_s_constants_are_the_schema_s() -> None:
    for name in (
        "FORMAT",
        "MAX_SAMPLES",
        "MAX_TRACES",
        "MAX_FILE_BYTES",
        "MAX_RECORDS_PER_SESSION",
        "MAX_SESSION_BYTES",
        "MAX_INPUTS",
        "MAX_LOADED",
        "MAX_TITLE",
        "MAX_INPUT_INTEGER",
        "NAME_PATTERN",
    ):
        assert getattr(writer, name) == getattr(schema, name), name
    assert unit_spelling.PATTERN == writer.UNIT_GRAMMAR_PATTERN
    assert schema.UNIT_GRAMMAR is unit_spelling.UNIT_SPELLING


ALLOWED_IMPORTS = {
    "__future__",
    "contextlib",
    "hashlib",
    "json",
    "math",
    "os",
    "re",
    "stat",
    "sys",
    "sysconfig",
}


def test_the_writer_imports_only_the_standard_library_it_names() -> None:
    tree = ast.parse(writer.__loader__.get_source(writer.__name__) or "")  # type: ignore[union-attr]
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported, "the fence saw no import at all"
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS


def test_the_writer_parses_as_python_3_9() -> None:
    source = writer.__loader__.get_source(writer.__name__) or ""  # type: ignore[union-attr]
    assert source
    ast.parse(source, feature_version=(3, 9))
    assert "strict=" not in source  # zip(..., strict=...) arrived in 3.10
