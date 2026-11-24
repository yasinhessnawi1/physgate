"""A reader with only the block can follow it: each rule it lists is met as it says.

For every rule the block lists as refused, an answer built to break exactly that rule (the
committed example with one edit) is refused on reading, by the name the block gives where it
gives one. For every rule it lists as not judged, the answer is read as a law the scorer cannot
take, by the name the block gives. A fault of the answer beats a term not judged. Reading is the
laptop's half; ``tests/scoring`` holds the scorer's, with the same cases.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from answer_form_cases import Case, cases, example, precedence, stated_and_refused

import physgate.evaluation.whole.form as form
from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole.answer import OutsideScope, parse_answer, parse_answer_scoped

RULES = {r.key: r for r in (*form.REFUSED, *form.NOT_JUDGED)}
ALL = [(key, case) for key, group in cases().items() for case in group]
IDS = [f"{key}:{case.label}" for key, case in ALL]


def _read(case: Case) -> Exception | None:
    try:
        parse_answer_scoped(case.data)
    except TaskFormatError as exc:
        return exc
    return None


def test_the_example_itself_is_read_without_a_refusal_and_without_a_term_out_of_scope() -> None:
    answer, outside = parse_answer_scoped(form.EXAMPLE_PATH.read_bytes())
    assert outside is None
    assert answer.version == 3


@pytest.mark.parametrize(("key", "case"), ALL, ids=IDS)
def test_an_answer_built_to_break_one_rule_is_read_as_the_block_says(key: str, case: Case) -> None:
    assert case.changed, f"{case.label}: the edit found its text in the example not exactly once"
    rule = RULES[key]
    refusal = _read(case)
    if case.parse == "parses":
        assert refusal is None
    elif case.parse == "outside":
        assert isinstance(refusal, OutsideScope), refusal
        assert refusal.name == rule.name
    else:
        assert isinstance(refusal, TaskFormatError) and not isinstance(refusal, OutsideScope)
        if rule.name is not None:
            assert rule.name in str(refusal), (rule.name, str(refusal))
    assert case.outcome == ("unscored" if case.parse == "outside" else "fail")


def _refused_saying(case: Case) -> str:
    assert case.changed, f"{case.label}: the edit found its text in the example not exactly once"
    refusal = _read(case)
    assert isinstance(refusal, TaskFormatError) and not isinstance(refusal, OutsideScope), refusal
    said = str(refusal)
    for words in case.said:
        assert words in said, (words, said)
    return said


def test_a_sign_written_true_is_refused_as_a_sign_that_is_no_number() -> None:
    _refused_saying(stated_and_refused()["sign_true"])


def test_two_states_marked_as_holding_the_applied_command_are_refused_and_both_are_named() -> None:
    _refused_saying(stated_and_refused()["applied_twice"])


def test_a_key_written_twice_is_refused_by_name_at_the_top_of_the_answer_and_inside_it() -> None:
    _refused_saying(stated_and_refused()["key_twice"])
    _refused_saying(stated_and_refused()["key_twice_inside"])


def test_a_key_written_twice_in_a_version_2_answer_is_refused_too() -> None:
    text = b'{"form": "whole_run", "version": 2, "version": 2, "controller": {}, "parameters": {}}'
    with pytest.raises(TaskFormatError, match="key_written_twice"):
        parse_answer(text)


def test_a_fault_of_the_answer_beats_a_term_that_is_not_judged() -> None:
    for case in precedence():
        refusal = _read(case)
        assert isinstance(refusal, TaskFormatError) and not isinstance(refusal, OutsideScope)


def test_a_rule_broken_in_two_places_is_still_one_refusal_of_the_answer() -> None:
    doc = example()
    doc["parameters"]["update_rate"]["unit"] = "1/s"
    doc["controller"]["command"] = "ghost"
    with pytest.raises(TaskFormatError):
        parse_answer(json.dumps(doc).encode())


# ── what the block says is allowed is allowed ──────────────────────────────────────────────────


def _edit(change: Any) -> bytes:
    doc = example()
    change(doc)
    return json.dumps(doc).encode()


def test_a_coefficient_of_0_switches_a_term_off_and_is_allowed() -> None:
    parse_answer(_edit(lambda d: d["controller"]["coefficients"]["k_wheel"].update(value=0)))


def test_the_term_s_number_is_optional_and_a_stated_1_is_the_same_law() -> None:
    def state(d: dict[str, Any]) -> None:
        for term in d["controller"]["lines"][1]["terms"]:
            term["number"] = 1

    assert parse_answer(_edit(state)).controller == parse_answer(_edit(lambda d: None)).controller


def test_a_unit_in_the_law_is_any_writing_of_the_unit_with_the_same_symbols() -> None:
    for spelling in ("rad**-1", "1/(rad)", "s**0/rad"):
        parse_answer(
            _edit(lambda d, u=spelling: d["controller"]["coefficients"]["k_angle"].update(unit=u))
        )


def test_a_name_of_a_letter_and_31_more_characters_is_allowed() -> None:
    name = "c" + "a" * 31

    def edit(d: dict[str, Any]) -> None:
        d["controller"]["lines"][1]["name"] = name
        d["controller"]["command"] = name

    parse_answer(_edit(edit))


def test_a_state_that_does_not_leak_is_allowed_to_be_written() -> None:
    parse_answer(_edit(lambda d: d["controller"]["coefficients"]["leak"].update(value=1)))


def test_the_period_is_a_coefficient_every_term_may_use_without_declaring_it() -> None:
    doc = example()
    used = [
        t
        for line in doc["controller"]["lines"]
        for t in line["terms"]
        if t["coefficients"] == ["period"]
    ]
    assert used and "period" not in doc["controller"]["coefficients"]
    parse_answer(json.dumps(doc).encode())
