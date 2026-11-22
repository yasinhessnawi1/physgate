"""A variable that is no well-formed name is a malformed answer; a marked law meets its vectors.

A term's variable is a name (``tilt``, ``previous.s``, ``line.x``). A text that is an expression
(a product, a function, a comparison) is ``nonlinear`` and a name outside the closed list is
``out_of_scope``: both are terms the scorer cannot take, marked in the law and refused by name at
the end. Any other text that is not a well-formed name (the scorer's own marker text among them,
empty, with a space, not ASCII, a number, in capitals, a ``null``) is a malformed answer, the
ordinary fail in an answer and a refusal by name in a law file: the marker is no text, and no text
can spell it.

A law file with a marked term is held to its vectors on every line that holds none: a fault there
is the vector refusal, the lines the marks leave unpinned are named in the record, and only a law
with nothing else wrong ends in the scope refusal.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole import answer as answer_module
from physgate.evaluation.whole import law as law_module

fuzz: Any = importlib.import_module(
    "test_no_law_in_an_answer_or_a_file_escapes_as_anything_but_a_refusal"
)
helpers: Any = importlib.import_module(
    "test_a_recorded_design_s_law_is_exported_when_it_reproduces_its_own_vectors"
)

#: The text the scorer used to mark a term with: now just one more text that is no name.
THE_OLD_MARKER = "outside the scorer's scope"
#: Texts that are no well-formed name and no expression: a malformed answer, never marked.
ILL_FORMED = [
    THE_OLD_MARKER,
    "",
    " ",
    "tilt rate",
    "tilt ",
    "tilt\n",
    "zé",
    "tilt·rate",
    "тilt",
    "5",
    "1.5",
    "Tilt",
    "previous.",
    "line.",
    "line.x.y",
]
WITH_ANOTHER = ["none", "a_term_out_of_scope"]


def _answer_with(of: Any, *, another: str = "none") -> bytes:
    controller = fuzz._controller()
    command = next(x for x in controller["lines"] if x["name"] == "command")
    command["terms"].append({"sign": 1, "number": 0, "of": of})
    if another == "a_term_out_of_scope":
        command["terms"].append({"sign": 1, "number": 1, "of": "tilt*tilt_rate"})
    document = {
        "form": "whole_run",
        "version": 3,
        "controller": controller,
        "parameters": copy.deepcopy(fuzz.SETTINGS),
    }
    return json.dumps(document).encode()


@pytest.mark.parametrize("another", WITH_ANOTHER)
@pytest.mark.parametrize("of", ILL_FORMED)
def test_a_variable_that_is_no_name_is_a_malformed_answer_with_or_without_another_marked_term(
    of: str, another: str
) -> None:
    raw = _answer_with(of, another=another)
    for parse in (answer_module.parse_answer, answer_module.parse_answer_scoped):
        with pytest.raises(TaskFormatError) as caught:
            parse(raw)
        assert not isinstance(caught.value, answer_module.OutsideScope), (
            of,
            "marked, not malformed",
        )


@pytest.mark.parametrize("of", [None, 5, 1.5, True, ["tilt"], {"a": 1}])
def test_a_variable_written_as_something_other_than_text_is_a_malformed_answer(of: Any) -> None:
    for another in WITH_ANOTHER:
        raw = _answer_with(of, another=another)
        for parse in (answer_module.parse_answer, answer_module.parse_answer_scoped):
            with pytest.raises(TaskFormatError) as caught:
                parse(raw)
            assert not isinstance(caught.value, answer_module.OutsideScope)


def test_a_null_variable_in_the_analysed_law_is_refused_beside_a_marked_term_in_the_primary() -> (
    None
):
    """No text can spell the marker: a ``null`` at the place another law's marked term holds."""
    document = json.loads(_answer_with("tilt*tilt_rate"))
    document["analysed_controller"] = copy.deepcopy(document["controller"])
    twin = next(x for x in document["analysed_controller"]["lines"] if x["name"] == "command")
    twin["terms"][-1]["of"] = None  # the very place the primary's marked term holds
    for parse in (answer_module.parse_answer, answer_module.parse_answer_scoped):
        with pytest.raises(TaskFormatError) as caught:
            parse(json.dumps(document).encode())
        assert not isinstance(caught.value, answer_module.OutsideScope), "the null, not the scope"


def test_an_expression_is_still_a_term_the_scorer_cannot_take_by_name() -> None:
    for of, code in (("tilt*tilt_rate", "nonlinear"), ("accelerometer_tilt", "out_of_scope")):
        with pytest.raises(answer_module.OutsideScope) as caught:
            answer_module.parse_answer(_answer_with(of))
        assert caught.value.name == code


@pytest.mark.parametrize("of", ILL_FORMED)
def test_a_law_file_with_a_variable_that_is_no_name_is_refused_as_malformed(of: str) -> None:
    document = copy.deepcopy(helpers._file())
    next(x for x in document["lines"] if x["name"] == "command")["terms"][0]["of"] = of
    with pytest.raises(law_module.LawRefused) as caught:
        law_module.parse_file(json.dumps(document).encode())
    assert caught.value.code == "malformed", (of, caught.value)
    with pytest.raises(law_module.LawRefused) as again:
        law_module.parse_file(json.dumps(document).encode(), defer_scope=True)
    assert again.value.code == "malformed"


@pytest.mark.parametrize("of", ILL_FORMED)
def test_the_export_refuses_a_variable_that_is_no_name_by_name_and_writes_nothing(
    tmp_path: Path, of: str
) -> None:
    document = copy.deepcopy(helpers._file())
    next(x for x in document["lines"] if x["name"] == "command")["terms"][0]["of"] = of
    record = helpers._refused(tmp_path, "malformed", law=helpers._bytes(document))
    assert record.law_detail


def test_the_marker_text_beside_a_marked_term_in_a_law_file_is_still_malformed(
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(helpers._file())
    command = next(x for x in document["lines"] if x["name"] == "command")
    command["terms"][0]["of"] = THE_OLD_MARKER
    command["terms"].append({"sign": 1, "number": 0, "of": "tilt*tilt_rate"})
    helpers._refused(tmp_path, "malformed", law=helpers._bytes(document))


# ── a law file with a marked term is held to its vectors on every line that holds none ──


def _command(document: dict[str, Any]) -> dict[str, Any]:
    line: dict[str, Any] = next(x for x in document["lines"] if x["name"] == "command")
    return line


def _with_a_marked_scratch_line(of: str = "accelerometer_tilt") -> dict[str, Any]:
    document: dict[str, Any] = copy.deepcopy(helpers._file())
    document["lines"].insert(
        0, {"name": "scratch", "unit": "rad", "terms": [{"sign": 1, "coefficients": [], "of": of}]}
    )
    return document


MARKS = ["accelerometer_tilt", "tilt*tilt_rate", "abs(tilt)"]


@pytest.mark.parametrize("of", MARKS)
def test_a_flipped_sign_beside_a_marked_term_in_another_line_is_the_vector_refusal(
    tmp_path: Path, of: str
) -> None:
    document = _with_a_marked_scratch_line(of)
    _command(document)["terms"][4]["sign"] = 1  # k_rate, flipped
    record = helpers._refused(tmp_path, "vector_not_reproduced", law=helpers._bytes(document))
    assert "vector" in record.law_detail


@pytest.mark.parametrize("of", MARKS)
def test_too_few_rows_beside_a_marked_term_is_the_vector_refusal(tmp_path: Path, of: str) -> None:
    document = _with_a_marked_scratch_line(of)
    kept, rows = [], 0
    for vector in document["vectors"]:
        if rows + len(vector["rows"]) > 9:
            break
        kept.append(vector)
        rows += len(vector["rows"])
    document["vectors"] = kept
    record = helpers._refused(tmp_path, "vectors_too_few", law=helpers._bytes(document))
    assert "9 rows" in record.law_detail


@pytest.mark.parametrize("of", MARKS)
def test_a_term_the_rows_do_not_exercise_beside_a_marked_term_is_the_vector_refusal(
    tmp_path: Path, of: str
) -> None:
    document = _with_a_marked_scratch_line(of)
    _command(document)["terms"].append({"sign": -1, "coefficients": ["k_true"], "of": "tilt"})
    document["coefficients"]["k_true"] = "k_true"
    record = helpers._refused(
        tmp_path,
        "vectors_do_not_exercise",
        law=helpers._bytes(document),
        coefficients={**helpers.COEFFICIENTS, "k_true": (1.0, "1/rad")},
    )
    assert "tilt" in record.law_detail


@pytest.mark.parametrize("of", MARKS)
def test_a_marked_term_alone_ends_in_the_scope_refusal_and_the_record_names_the_unpinned_line(
    tmp_path: Path, of: str
) -> None:
    code = "out_of_scope" if of == "accelerometer_tilt" else "nonlinear"
    record = helpers._refused(tmp_path, code, law=helpers._bytes(_with_a_marked_scratch_line(of)))
    assert record.law_unpinned_lines == ("scratch",)


def test_a_marked_term_in_a_line_the_command_reads_leaves_the_state_the_rows_name_pinned(
    tmp_path: Path,
) -> None:
    """The command reads ``w_hat``: the command is not judged, the leaky estimate still is."""
    document = copy.deepcopy(helpers._file())
    w_hat = next(x for x in document["lines"] if x["name"] == "w_hat")
    w_hat["terms"][0]["of"] = "accelerometer_tilt"
    clean = helpers._refused(tmp_path, "out_of_scope", law=helpers._bytes(document))
    assert "w_hat" in clean.law_unpinned_lines
    assert "command" in clean.law_unpinned_lines
    assert "theta_now" not in clean.law_unpinned_lines  # the rows name theta_hat: judged
    other = tmp_path / "flipped"
    other.mkdir()
    flipped = copy.deepcopy(document)
    theta_now = next(x for x in flipped["lines"] if x["name"] == "theta_now")
    theta_now["terms"][1]["sign"] = -1  # the tilt rate into the estimate, flipped
    helpers._refused(other, "vector_not_reproduced", law=helpers._bytes(flipped))


def test_a_law_with_no_marked_term_has_no_unpinned_line(tmp_path: Path) -> None:
    record, _, _, _ = helpers._export(tmp_path)
    assert record.status == "exported"
    assert record.law_unpinned_lines == ()
    assert (
        law_module.unpinned(
            law_module.parse_file(helpers._LAW.read_bytes()),
            law_module.parse_file(helpers._LAW.read_bytes()).vectors,
        )
        == ()
    )


def test_a_named_state_whose_next_value_holds_a_marked_term_is_not_compared(
    tmp_path: Path,
) -> None:
    """The rows name ``theta_hat``; its line holds the marked term, so it cannot be reproduced."""
    document = copy.deepcopy(helpers._file())
    theta_now = next(x for x in document["lines"] if x["name"] == "theta_now")
    theta_now["terms"][1]["of"] = "accelerometer_tilt"  # the tilt rate into the estimate
    record = helpers._refused(tmp_path, "out_of_scope", law=helpers._bytes(document))
    assert "theta_now" in record.law_unpinned_lines
    assert "command" in record.law_unpinned_lines


def test_a_state_only_a_marked_term_reads_is_not_refused_as_read_by_no_term(
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(helpers._file())
    w_hat = next(x for x in document["lines"] if x["name"] == "w_hat")
    assert w_hat["terms"][1]["of"] == "previous.p_prev"
    w_hat["terms"][1]["of"] = "accelerometer_tilt"
    record = helpers._refused(tmp_path, "out_of_scope", law=helpers._bytes(document))
    assert "w_hat" in record.law_unpinned_lines


def test_a_law_that_lost_a_term_is_the_vector_refusal_and_leaves_no_line_unpinned(
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(helpers._file())
    w_hat = next(x for x in document["lines"] if x["name"] == "w_hat")
    del w_hat["terms"][1]  # nothing reads p_prev now
    record = helpers._refused(tmp_path, "vector_not_reproduced", law=helpers._bytes(document))
    assert record.law_unpinned_lines == ()


# ── the schema holds a variable to a name before anything else reads it ──


def _body_reading(of: str) -> Any:
    """The recorded law's body with its command's first term reading ``of``, made unchecked."""
    body = law_module.parse_file(helpers._LAW.read_bytes())
    command = next(x for x in body.lines if x.name == "command")
    term = command.terms[0].model_copy(update={"of": of})
    line = command.model_copy(update={"terms": (term, *command.terms[1:])})
    lines = tuple(line if x.name == "command" else x for x in body.lines)
    return body.model_copy(update={"lines": lines})


UNITS = {n: u for n, (_, u) in helpers.COEFFICIENTS.items()}


@pytest.mark.parametrize("of", ["tilt rate", "", "zé", "Tilt", "5", "previous."])
def test_a_variable_that_is_no_name_is_refused_as_malformed_by_the_unit_check_too(of: str) -> None:
    with pytest.raises(law_module.LawRefused) as caught:
        law_module.check(_body_reading(of), UNITS)
    assert caught.value.code == "malformed"


@pytest.mark.parametrize("of", ["tilt*tilt_rate", "abs(tilt)", "tilt+wheel_angle", "tilt<0"])
def test_an_expression_is_refused_as_nonlinear_by_the_unit_check(of: str) -> None:
    with pytest.raises(law_module.LawRefused) as caught:
        law_module.check(_body_reading(of), UNITS)
    assert caught.value.code == "nonlinear"
