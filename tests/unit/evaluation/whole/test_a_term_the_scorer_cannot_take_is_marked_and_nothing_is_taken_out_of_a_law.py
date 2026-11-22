"""Scope is decided on what the law computes, not on what a term spells.

A term that no linear law over the closed list can be (not one variable, or a signal outside the
list) is a ground to refuse a law by name only if it can matter: it has a weight (its number and
the coefficients it multiplies are not 0) and it is in a line the command reaches, through the
lines it reads and the memory states they read. A term that cannot is taken out, and the law is
judged as it would be without it.
"""

from __future__ import annotations

import importlib
import json
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


def _command_reads(document: dict[str, Any], *terms: dict[str, Any]) -> dict[str, Any]:
    document["lines"][-1]["terms"].extend(terms)
    return document


def _names(scoped: Any) -> tuple[list[str], list[str]]:
    return [f"{o.line}:{o.index}" for o in scoped.live], [
        f"{o.line}:{o.index}" for o in scoped.dead
    ]


def test_a_document_with_nothing_out_of_scope_is_returned_as_it_is() -> None:
    document = _doc([("a", [_term("tilt")])])
    scoped = _law().scoped(document)
    assert scoped.body is document
    assert scoped.live == () and scoped.dead == ()


@pytest.mark.parametrize("of", ["accelerometer_tilt", "tilt*tilt_rate", "abs(tilt)", "line.a+tilt"])
def test_an_out_of_scope_term_in_a_line_nothing_reads_is_dead_and_the_line_goes(of: str) -> None:
    scoped = _law().scoped(_doc([("dead", [_term(of)])]))
    assert _names(scoped) == ([], ["dead:0"])
    assert [x["name"] for x in scoped.body["lines"]] == ["command"]


def test_a_term_that_a_live_line_reads_is_live_and_its_variable_is_marked() -> None:
    document = _command_reads(_doc([("a", [_term("accelerometer_tilt")])]), _term("line.a", "g"))
    scoped = _law().scoped(document)
    assert _names(scoped) == (["a:0"], [])
    assert scoped.body["lines"][0]["terms"][0]["of"] == _law().OUTSIDE


def test_a_term_with_an_extra_key_is_nonlinear_and_keeps_only_a_term_s_own_keys_once_marked() -> (
    None
):
    document = _command_reads(
        _doc([("a", [_term("tilt", times="tilt_rate")])]), _term("line.a", "g")
    )
    scoped = _law().scoped(document)
    assert [o.code for o in scoped.live] == ["nonlinear"]
    assert set(scoped.body["lines"][0]["terms"][0]) <= {
        "sign",
        "number",
        "coefficients",
        "per",
        "of",
    }


def test_a_line_read_only_by_a_dead_line_is_dead_too() -> None:
    document = _doc(
        [
            ("deep", [_term("accelerometer_tilt")]),
            ("dead", [_term("line.deep", "g"), _term("tilt_rate")]),
        ]
    )
    scoped = _law().scoped(document)
    assert _names(scoped) == ([], ["deep:0"])
    # "dead" is in scope but its terms name a line that is no more, and nothing reads it: it goes
    assert [x["name"] for x in scoped.body["lines"]] == ["command"]


def test_a_term_of_weight_zero_that_read_an_out_of_scope_line_goes_with_it() -> None:
    document = _command_reads(
        _doc([("a", [_term("accelerometer_tilt")])]), _term("line.a", "g", number=0)
    )
    scoped = _law().scoped(document)
    assert _names(scoped) == ([], ["a:0"])
    assert [x["name"] for x in scoped.body["lines"]] == ["command"]
    assert [t["of"] for t in scoped.body["lines"][0]["terms"]] == ["tilt"]


ZERO = {"k_zero": 0.0, "g": 1.0}


def _zero_reader(lone: bool) -> dict[str, Any]:
    """``mm`` reads ``zz`` with weight 0; ``zz``'s one term is out of scope and weightless."""
    mm = [_term("previous.zz", "k_zero")]
    if not lone:
        mm.append(_term("tilt_rate", "g"))
    document = _doc(
        [("zz_now", [_term("accelerometer_tilt", "k_zero")]), ("mm", mm)],
        [{"name": "zz", "unit": "1", "next": "zz_now"}],
    )
    return _command_reads(document, _term("line.mm", "g"))


def test_a_lone_term_of_weight_zero_that_reads_a_state_taken_out_is_a_line_of_nothing() -> None:
    """The line is 0 at every update: it goes, and so does the term of the command that reads it."""
    law = _law()
    scoped = law.scoped(_zero_reader(lone=True), ZERO)
    assert scoped.live == ()
    assert [x["name"] for x in scoped.body["lines"]] == ["command"]
    assert [t["of"] for t in scoped.body["lines"][0]["terms"]] == ["tilt"]
    assert scoped.body["memory"] == []
    body = law.Body.model_validate_json(
        json.dumps({k: scoped.body[k] for k in ("memory", "lines", "command")})
    )
    assert [line.name for line in body.lines] == ["command"]


def test_a_term_of_weight_zero_that_reads_a_state_taken_out_beside_a_real_term_is_dropped() -> None:
    law = _law()
    scoped = law.scoped(_zero_reader(lone=False), ZERO)
    assert scoped.live == ()
    assert [x["name"] for x in scoped.body["lines"]] == ["mm", "command"]
    assert [t["of"] for t in scoped.body["lines"][0]["terms"]] == ["tilt_rate"]
    law.Body.model_validate_json(
        json.dumps({k: scoped.body[k] for k in ("memory", "lines", "command")})
    )


def test_a_line_of_a_term_reading_what_went_and_a_dead_term_is_a_line_of_nothing_too() -> None:
    law = _law()
    document = _doc(
        [
            ("zz_now", [_term("accelerometer_tilt", "k_zero")]),
            (
                "mm",
                [_term("previous.zz", "k_zero"), _term("tilt*tilt_rate", "k_zero")],
            ),
        ],
        [{"name": "zz", "unit": "1", "next": "zz_now"}],
    )
    _command_reads(document, _term("line.mm", "g"))
    scoped = law.scoped(document, ZERO)
    assert scoped.live == ()
    assert [x["name"] for x in scoped.body["lines"]] == ["command"]
    assert sorted(f"{o.line}:{o.index}" for o in scoped.dead) == ["mm:1", "zz_now:0"]


def test_what_a_line_keeps_of_the_text_is_where_each_term_stood_in_it() -> None:
    law = _law()
    document = _zero_reader(lone=False)
    scoped = law.scoped(document, ZERO)
    assert scoped.origin == {"mm": (1,), "command": (0, 1)}
    untouched = law.scoped(_doc([("a", [_term("tilt"), _term("tilt_rate")])]))
    assert untouched.origin == {"a": (0, 1), "command": (0,)}


def test_a_state_fed_by_a_line_of_nothing_goes_with_it_and_so_does_the_term_that_reads_it() -> None:
    law = _law()
    memory = [
        {"name": "zz", "unit": "1", "next": "zz_now"},
        {"name": "y", "unit": "1", "next": "mm"},
    ]
    document = _doc(
        [
            ("zz_now", [_term("accelerometer_tilt", "k_zero")]),
            ("mm", [_term("previous.zz", "k_zero")]),
        ],
        memory,
    )
    _command_reads(document, _term("previous.y", "g"))
    scoped = law.scoped(document, ZERO)
    assert scoped.live == ()
    assert scoped.body["memory"] == []
    assert [t["of"] for t in scoped.body["lines"][0]["terms"]] == ["tilt"]


def test_a_dead_term_that_is_the_only_one_of_a_line_the_command_reads_is_not_set_aside() -> None:
    # the line is read with a weight, but its one term has weight 0: taking it out leaves nothing
    document = _command_reads(
        _doc([("b", [_term("accelerometer_tilt", number=0)])]), _term("line.b", "g")
    )
    scoped = _law().scoped(document)
    assert _names(scoped) == (["b:0"], [])


def test_a_term_of_weight_zero_by_its_number_or_by_a_coefficient_is_dead() -> None:
    document = _command_reads(
        _doc([("a", [_term("accelerometer_tilt")])]), _term("line.a", "g", number=0)
    )
    document["lines"][0]["terms"].append(_term("tilt_rate"))
    assert _names(_law().scoped(document)) == ([], ["a:0"])
    zero_by_coefficient = _command_reads(
        _doc([("a", [_term("tilt_rate"), _term("accelerometer_tilt", "k_zero")])]),
        _term("line.a", "g"),
    )
    known = {"k_zero": 0.0, "g": 1.0}
    assert _names(_law().scoped(zero_by_coefficient, known)) == ([], ["a:1"])
    # without the numbers a coefficient may be anything: the term can matter
    assert _names(_law().scoped(zero_by_coefficient)) == (["a:1"], [])
    assert _names(_law().scoped(zero_by_coefficient, {"k_zero": 0.5})) == (["a:1"], [])


def test_a_term_in_the_next_value_of_a_state_is_live_only_if_a_live_term_reads_the_state() -> None:
    memory = [{"name": "z", "unit": "1", "next": "z_now"}]
    unread = _doc([("z_now", [_term("accelerometer_tilt")])], memory)
    assert _names(_law().scoped(unread)) == ([], ["z_now:0"])
    assert _law().scoped(unread).body["memory"] == []
    read = _command_reads(
        _doc([("z_now", [_term("accelerometer_tilt")])], memory), _term("previous.z")
    )
    assert _names(_law().scoped(read)) == (["z_now:0"], [])
    # read only through a state that is read
    chained = _doc(
        [
            ("z_now", [_term("previous.y")]),
            ("y_now", [_term("accelerometer_tilt")]),
        ],
        [
            {"name": "z", "unit": "1", "next": "z_now"},
            {"name": "y", "unit": "1", "next": "y_now"},
        ],
    )
    chained = _command_reads(chained, _term("previous.z"))
    assert _names(_law().scoped(chained)) == (["y_now:0"], [])


def test_a_nonlinear_term_that_is_live_keeps_the_lines_it_names_live() -> None:
    document = _doc(
        [
            ("a", [_term("tilt")]),
            ("b", [_term("accelerometer_tilt")]),
        ]
    )
    _command_reads(document, _term("line.a*tilt_rate", "g"))
    scoped = _law().scoped(document)
    assert [o.line for o in scoped.live] == ["command", "b"] or [o.line for o in scoped.live] == [
        "command"
    ]
    assert "a" in [x["name"] for x in scoped.body["lines"]]


def test_scope_raises_for_a_term_that_matters_and_not_for_one_that_cannot() -> None:
    law = _law()
    law.scope(_doc([("dead", [_term("accelerometer_tilt")])]))
    with pytest.raises(law.LawRefused) as caught:
        law.scope(_command_reads(_doc([]), _term("accelerometer_tilt", "g")))
    assert caught.value.code == "out_of_scope"


def test_a_law_file_with_a_dead_out_of_scope_line_is_read_and_a_live_one_is_refused() -> None:
    law = _law()
    fixture = importlib.import_module("pathlib").Path(__file__).resolve().parent / "recorded_law"
    document = json.loads((fixture / "law.json").read_text())
    document["lines"].insert(0, {"name": "x", "unit": "1", "terms": [_term("accelerometer_tilt")]})
    file = law.parse_file(json.dumps(document).encode())
    assert all(line.name != "x" for line in file.lines)
    assert [o.line for o in file.set_aside] == ["x"]
    document["lines"][-1]["terms"][0]["of"] = "accelerometer_tilt"
    with pytest.raises(law.LawRefused) as caught:
        law.parse_file(json.dumps(document).encode())
    assert caught.value.code == "out_of_scope"
    deferred = law.parse_file(json.dumps(document).encode(), defer_scope=True)
    assert [o.line for o in deferred.outside] == ["command"]
