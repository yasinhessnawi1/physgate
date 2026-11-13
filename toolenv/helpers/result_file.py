"""What a design helper may answer, and the one way an answer is written to a file.

A helper answers with numbers and files: every number a value with its unit, in SI, and every
file by its name, size and sha256. It never says whether a number is good. Whether a mass, a
clearance or a stress is acceptable is decided by the physics gate and read by a reviewer, and a
helper that said so would be a second gate that nothing protects and nothing counts.

So a result has a closed set of fields for its kind, holds no truth value anywhere, and no field
named as a judgement; :func:`checked` refuses anything else, and :func:`write` writes only what
it accepted. Nothing here compares a result with a limit, and no function takes one.

This file runs on the tool environment's interpreter, needs the standard library only, and
imports nothing of the harness.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from typing import Any

#: The version of the result layout. A reader that meets another number does not guess.
SCHEMA = 1
#: The most a result file may hold.
MAX_RESULT_BYTES = 1 << 20
#: How deep a result may nest.
MAX_DEPTH = 8

#: The fields of each kind of result: exactly these, no more and no fewer.
FIELDS: dict[str, frozenset[str]] = {
    "geometry": frozenset(
        {"schema", "kind", "part", "geometry_hash", "values", "inputs", "exports", "libraries"}
    ),
    "pair": frozenset({"schema", "kind", "parts", "placed_geometry_hashes", "values", "libraries"}),
    "load_case": frozenset(
        {"schema", "kind", "case", "model", "formulas", "assumptions", "inputs", "values"}
    ),
    "reference_measurement": frozenset(
        {
            "schema",
            "kind",
            "subject",
            "reference",
            "method",
            "inputs",
            "assumptions",
            "values",
            "libraries",
        }
    ),
}

#: Field names that state a judgement. None may appear anywhere in a result.
JUDGEMENT_WORDS = frozenset(
    {
        "acceptable",
        "accepted",
        "clean",
        "compliant",
        "conforms",
        "fail",
        "failed",
        "fails",
        "invalid",
        "ok",
        "okay",
        "pass",
        "passed",
        "passes",
        "rejected",
        "safe",
        "unsafe",
        "valid",
        "verdict",
        "violation",
        "violations",
        "within_limit",
        "within_limits",
    }
)


class HelperRefusedError(Exception):
    """A helper was given, or was about to answer, something it does not accept."""


def quantity(value: Any, unit: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401 - a number or a list of them
    """A value with its unit. A value that is not a finite number is refused, never written."""
    _finite(value, "a value")
    if not unit:
        raise HelperRefusedError("a value has a unit; an empty one is not a unit")
    return {"value": value, "unit": unit, **more}


def _finite(value: Any, where: str) -> None:  # noqa: ANN401 - a number or nested lists of them
    if isinstance(value, list):
        for item in value:
            _finite(item, where)
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HelperRefusedError(f"{where} is not a number")
    if not math.isfinite(value):
        raise HelperRefusedError(f"{where} is not finite")


def _walk(found: Any, where: str, depth: int) -> None:  # noqa: ANN401 - any part of a result
    if depth > MAX_DEPTH:
        raise HelperRefusedError(f"{where} nests too deep")
    if isinstance(found, bool):
        # A truth value is how a judgement is spelt, whatever its field is called.
        raise HelperRefusedError(f"{where} is a truth value; a result holds numbers and text")
    if isinstance(found, Mapping):
        for name, inner in found.items():
            if not isinstance(name, str):
                raise HelperRefusedError(f"{where} has a field whose name is not text")
            if name.lower() in JUDGEMENT_WORDS:
                raise HelperRefusedError(
                    f"{where} has the field {name!r}, which states a judgement"
                )
            _walk(inner, f"{where}.{name}", depth + 1)
    elif isinstance(found, (list, tuple)):
        for index, inner in enumerate(found):
            _walk(inner, f"{where}[{index}]", depth + 1)
    elif isinstance(found, float):
        if not math.isfinite(found):
            raise HelperRefusedError(f"{where} is not finite")
    elif found is not None and not isinstance(found, (int, str)):
        raise HelperRefusedError(f"{where} is a {type(found).__name__}, which a result cannot hold")


def checked(result: Mapping[str, Any]) -> dict[str, Any]:
    """``result`` as a plain dictionary, if it is a result a helper may answer.

    Raises:
        HelperRefusedError: its kind is unknown, its fields are not exactly its kind's, its
            layout version is another, or it holds a truth value, a judgement's name, a number
            that is not finite, or anything that is not a number, text, a list or an object.
    """
    kind = result.get("kind")
    if not isinstance(kind, str) or kind not in FIELDS:
        raise HelperRefusedError(f"a result of kind {kind!r} is not one a helper answers")
    if set(result) != FIELDS[kind]:
        extra, missing = sorted(set(result) - FIELDS[kind]), sorted(FIELDS[kind] - set(result))
        raise HelperRefusedError(
            f"a {kind} result has exactly its own fields: not {extra}, and with {missing}"
        )
    if result["schema"] != SCHEMA:
        raise HelperRefusedError(f"a result is written at layout version {SCHEMA}")
    _walk(result, kind, 0)
    return dict(result)


def render(result: Mapping[str, Any]) -> str:
    """The text of a result file: the checked result, fields sorted, ending in one line feed."""
    text = json.dumps(checked(result), sort_keys=True, indent=2, allow_nan=False) + "\n"
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        raise HelperRefusedError(f"a result file holds at most {MAX_RESULT_BYTES} bytes")
    return text


def write(path: str | os.PathLike[str], result: Mapping[str, Any]) -> str:
    """Write ``result`` to ``path`` (a name ending ``.result.json``); return the path written.

    Raises:
        HelperRefusedError: as :func:`checked`, or the name does not end ``.result.json``.
    """
    name = os.fspath(path)
    if not name.endswith(".result.json"):
        raise HelperRefusedError("a result file is named <something>.result.json")
    text = render(result)
    with open(name, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return name
