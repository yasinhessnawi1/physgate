"""A term the scorer cannot take is marked, whatever its weight, and nothing is taken out.

A term that no linear law over the closed list can be (not one variable, or a signal outside the
list) is found wherever it stands, in a line the command reads or not, of weight zero or not. Its
variable is marked, so every other check still runs on the whole law; no term, line or memory
state is removed, and the order and place of every term is what was written.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

_LAW = "physgate.evaluation.whole.law"


def _law() -> Any:
    return importlib.import_module(_LAW)


def _term(of: str, *coefficients: str, number: float | None = None, **more: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"sign": 1, "coefficients": list(coefficients), "of": of, **more}
    if number is not None:
        out["number"] = number
    return out


def _doc(
    lines: list[tuple[str, list[dict[str, Any]]]], memory: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "memory": memory or [],
        "lines": [
            *({"name": n, "unit": "1", "terms": t} for n, t in lines),
            {"name": "command", "unit": "1", "terms": [_term("tilt", "g")]},
        ],
        "command": "command",
    }


def _where(marked: Any) -> list[str]:
    return [f"{o.line}:{o.index}" for o in marked.outside]


def test_a_document_with_nothing_out_of_scope_is_returned_as_it_is() -> None:
    document = _doc([("a", [_term("tilt")])])
    marked = _law().mark(document)
    assert marked.body is document
    assert marked.outside == ()


@pytest.mark.parametrize("of", ["accelerometer_tilt", "tilt*tilt_rate", "abs(tilt)", "line.a+tilt"])
def test_a_term_out_of_scope_in_a_line_nothing_reads_is_found_and_the_line_stays(of: str) -> None:
    marked = _law().mark(_doc([("unread", [_term(of), _term("tilt")])]))
    assert _where(marked) == ["unread:0"]
    assert [x["name"] for x in marked.body["lines"]] == ["unread", "command"]
    assert [t["of"] for t in marked.body["lines"][0]["terms"]] == [None, "tilt"]


@pytest.mark.parametrize("number", [0.0, 5e-324, 1e-9, 3.0])
def test_a_term_is_found_whatever_its_weight(number: float) -> None:
    marked = _law().mark(_doc([("a", [_term("tilt*tilt_rate", number=number)])]))
    assert _where(marked) == ["a:0"]
    assert marked.body["lines"][0]["terms"][0]["number"] == number


def test_a_zero_coefficient_does_not_hide_a_term() -> None:
    marked = _law().mark(_doc([("a", [_term("accelerometer_tilt", "zero")])]))
    assert _where(marked) == ["a:0"]


def test_a_term_in_a_line_the_command_reads_is_found_and_its_variable_is_marked() -> None:
    document = _doc([("a", [_term("accelerometer_tilt")])])
    document["lines"][-1]["terms"].append(_term("line.a", "g"))
    marked = _law().mark(document)
    assert _where(marked) == ["a:0"]
    assert marked.body["lines"][0]["terms"][0]["of"] is None


def test_a_term_with_an_extra_key_is_nonlinear_and_keeps_every_key_it_was_written_with() -> None:
    document = _doc([("a", [_term("tilt", extra="sin")])])
    marked = _law().mark(document)
    assert [o.code for o in marked.outside] == ["nonlinear"]
    assert set(marked.body["lines"][0]["terms"][0]) == {"sign", "coefficients", "of", "extra"}
    assert marked.body["lines"][0]["terms"][0]["extra"] == "sin"


def test_every_term_of_every_line_is_found_in_the_order_written() -> None:
    document = _doc(
        [
            ("a", [_term("tilt"), _term("accelerometer_tilt"), _term("tilt*tilt_rate")]),
            ("b", [_term("abs(tilt)")]),
        ]
    )
    document["lines"][-1]["terms"].append(_term("sin(tilt)", "g"))
    marked = _law().mark(document)
    assert _where(marked) == ["a:1", "a:2", "b:0", "command:1"]
    assert [len(x["terms"]) for x in marked.body["lines"]] == [3, 1, 2]


def test_a_line_that_is_not_a_line_is_left_for_the_schema_to_refuse() -> None:
    marked = _law().mark({"lines": [3, {"name": 4, "terms": []}, {"name": "x", "terms": "no"}]})
    assert marked.outside == ()


def test_a_law_file_with_an_out_of_scope_line_nothing_reads_is_refused_by_name() -> None:
    law = _law()
    fixture = Path(__file__).resolve().parent / "recorded_law"
    document = json.loads((fixture / "law.json").read_text())
    document["lines"].insert(0, {"name": "x", "unit": "1", "terms": [_term("accelerometer_tilt")]})
    with pytest.raises(law.LawRefused) as caught:
        law.parse_file(json.dumps(document).encode())
    assert caught.value.code == "out_of_scope"
    deferred = law.parse_file(json.dumps(document).encode(), defer_scope=True)
    assert [o.line for o in deferred.outside] == ["x"]
    assert [line.name for line in deferred.lines][0] == "x"  # the line is still there


def test_a_zero_weight_term_of_the_file_is_found_all_the_same() -> None:
    law = _law()
    fixture = Path(__file__).resolve().parent / "recorded_law"
    document = json.loads((fixture / "law.json").read_text())
    document["lines"][-1]["terms"].append(_term("tilt*tilt_rate", number=0.0))
    with pytest.raises(law.LawRefused) as caught:
        law.parse_file(json.dumps(document).encode())
    assert caught.value.code == "nonlinear"
