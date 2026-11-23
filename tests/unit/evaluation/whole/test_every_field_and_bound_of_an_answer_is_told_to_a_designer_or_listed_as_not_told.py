"""Every field and every bound of the answer is told in the block, or listed as not told, with why.

The universe is enumerated from the schema itself: every field of the answer's models, every size
limit the models put on a field, every upper-case numeric constant of the answer and law modules,
every entry of the bounds table and of the signal list. Each is either read in the block (its
words or its value found there) or named in ``NOT_TOLD`` with a reason. A new field, a new bound
or a new constant fails here until someone decides which; a stale entry in the list fails too.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from answer_form_cases import block, cases

import physgate.evaluation.whole.answer as answer_module
import physgate.evaluation.whole.form as form
import physgate.evaluation.whole.law as law_module
from physgate.evaluation.tiers.base import Measure
from physgate.unit_spelling import MAX_LENGTH as UNIT_MAX_LENGTH

MODELS: tuple[Any, ...] = (
    answer_module.WholeRunV3,
    answer_module.ParametersV3,
    answer_module.SampledLaw,
    law_module.Memory,
    law_module.Line,
    law_module.Term,
    Measure,
)


def _before_example() -> str:
    return block().split("AN EXAMPLE OF THE FORM ONLY")[0]


def _one_line() -> str:
    return " ".join(_before_example().split())


def _fields() -> list[str]:
    return [f"{m.__name__}.{f}" for m in MODELS for f in m.model_fields]


def _limits() -> dict[str, int]:
    found: dict[str, int] = {}
    for model in MODELS:
        for name, info in model.model_fields.items():
            for meta in info.metadata:
                for kind in ("max_length", "min_length"):
                    if getattr(meta, kind, None) is not None:
                        found[f"{model.__name__}.{name}:{kind}"] = getattr(meta, kind)
    return found


def _constants() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for label, module in (("answer", answer_module), ("law", law_module)):
        for name, value in vars(module).items():
            numeric = isinstance(value, int | float) and not isinstance(value, bool)
            if re.fullmatch(r"[A-Z][A-Z_0-9]*", name) and numeric:
                found[f"{label}.{name}"] = value
    found["answer.UNDERFLOWS"] = answer_module.UNDERFLOWS
    found["answer.OVERFLOWS"] = answer_module.OVERFLOWS
    found["answer.NOT_A_NUMBER"] = answer_module.NOT_A_NUMBER
    found["unit_spelling.MAX_LENGTH"] = UNIT_MAX_LENGTH
    return found


def _n(value: float) -> str:
    text: str = form._n(value)  # noqa: SLF001
    return text


# What a designer is told, as this test states it apart from the module: each told key, and the
# words (read with the value it holds) that must be found in the block.
TOLD_FIELDS = {
    "WholeRunV3.form",
    "WholeRunV3.version",
    "WholeRunV3.controller",
    "WholeRunV3.parameters",
    "ParametersV3.update_rate",
    "ParametersV3.output_data_rate",
    "ParametersV3.gyro_full_scale",
    "ParametersV3.pwm_frequency",
    "ParametersV3.pwm_full_scale",
    "ParametersV3.encoder_counts_per_wheel_revolution",
    "SampledLaw.structure",
    "SampledLaw.period",
    "SampledLaw.command_limit",
    "SampledLaw.sensor_delay",
    "SampledLaw.compute_delay",
    "SampledLaw.coefficients",
    "SampledLaw.memory",
    "SampledLaw.lines",
    "SampledLaw.command",
    "Memory.name",
    "Memory.unit",
    "Memory.next",
    "Memory.applied",
    "Line.name",
    "Line.unit",
    "Line.terms",
    "Term.sign",
    "Term.number",
    "Term.coefficients",
    "Term.per",
    "Term.of",
    "Measure.value",
    "Measure.unit",
}
TOLD_LIMITS: dict[str, Callable[[int], str]] = {
    "SampledLaw.coefficients:max_length": lambda n: f"At most {n}.",
    "SampledLaw.memory:max_length": lambda n: f"at most {n} states",
    "SampledLaw.lines:min_length": lambda n: f"list of {n} to",
    "SampledLaw.lines:max_length": lambda n: f"to {n} lines",
    "Line.terms:min_length": lambda n: f"with {n} to",
    "Line.terms:max_length": lambda n: f"to {n} terms",
    "Term.coefficients:max_length": lambda n: f"(optional, at most {n})",
    "Term.per:max_length": lambda n: f"(optional, at most {n})",
    "Line.unit:max_length": lambda n: f"is at most {n} characters",
    "Memory.unit:max_length": lambda n: f"is at most {n} characters",
}
TOLD_CONSTANTS: dict[str, Callable[[Any], str]] = {
    "answer.MAX_ANSWER_BYTES": lambda v: f"at most {_n(v)} bytes",
    "answer.MAX_DELAY_SECONDS": lambda v: f"to {_n(v)}.",
    "answer.MAX_DELAY_SAMPLES": lambda v: f"at most {_n(v)} periods",
    "answer.LAW_MAGNITUDE": lambda v: f"at most {_n(v)}",
    "law.MAX_MEMORY": lambda v: f"at most {_n(v)} states",
    "law.MAX_LINES": lambda v: f"to {_n(v)} lines",
    "law.MAX_TERMS": lambda v: f"to {_n(v)} terms",
    "law.MAX_COEFFICIENTS": lambda v: f"At most {_n(v)}.",
    "law.MAX_FACTORS": lambda v: f"at most {_n(v)})",
    "answer.UNDERFLOWS": lambda v: f"({v})",
    "answer.OVERFLOWS": lambda v: f"({v})",
}
TOLD_BOUNDS = {"period", "command_limit", "sensor_delay", "compute_delay"} | {
    bound
    for name, (_, bound) in answer_module.SETTINGS.items()
    if f"ParametersV3.{name}" in TOLD_FIELDS
}
NOT_A_FIELD_OF_THE_ANSWER = {"scenario.MAX_WORK"}


def test_every_field_is_told_or_listed_as_not_told() -> None:
    universe = set(_fields())
    assert universe >= TOLD_FIELDS, sorted(TOLD_FIELDS - universe)
    placed = TOLD_FIELDS | set(form.NOT_TOLD)
    assert sorted(universe - placed) == [], "a field of the answer is placed nowhere"
    assert TOLD_FIELDS & set(form.NOT_TOLD) == set()


def test_each_told_field_is_named_in_the_block_and_each_not_told_one_is_not() -> None:
    for key in sorted(TOLD_FIELDS):
        name = key.split(".", 1)[1]
        assert re.search(rf'(?<![A-Za-z0-9_])"?{name}"?(?![A-Za-z0-9_])', _before_example()), key
    for key in sorted(k for k in form.NOT_TOLD if k.split(".")[0] in {m.__name__ for m in MODELS}):
        if ":" in key:
            continue
        name = key.split(".", 1)[1]
        assert re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", block()) is None, key


def test_every_size_limit_a_model_puts_on_a_field_is_told_or_listed() -> None:
    limits = _limits()
    assert set(TOLD_LIMITS) <= set(limits), sorted(set(TOLD_LIMITS) - set(limits))
    placed = set(TOLD_LIMITS) | set(form.NOT_TOLD)
    assert sorted(set(limits) - placed) == [], "a limit on a field is placed nowhere"
    assert set(TOLD_LIMITS) & set(form.NOT_TOLD) == set()
    for key, said in TOLD_LIMITS.items():
        value = limits[key]
        if key.endswith("unit:max_length"):
            value = min(limits["Line.unit:max_length"], limits["Memory.unit:max_length"])
        assert said(value) in _one_line(), key


def test_every_constant_that_bounds_an_answer_is_told_or_listed() -> None:
    constants = _constants()
    assert set(TOLD_CONSTANTS) <= set(constants), sorted(set(TOLD_CONSTANTS) - set(constants))
    placed = set(TOLD_CONSTANTS) | set(form.NOT_TOLD)
    assert sorted(set(constants) - placed) == [], (
        "a constant that bounds an answer is placed nowhere"
    )
    assert set(TOLD_CONSTANTS) & set(form.NOT_TOLD) == set()
    for key, said in TOLD_CONSTANTS.items():
        assert said(constants[key]) in _one_line(), key


def test_the_bounds_table_and_the_signal_list_are_told_or_listed() -> None:
    bounds = answer_module.FIELD_BOUNDS
    assert set(bounds) >= TOLD_BOUNDS
    not_told = {k.split(".", 1)[1] for k in form.NOT_TOLD if k.startswith("FIELD_BOUNDS.")}
    assert sorted(set(bounds) - TOLD_BOUNDS - not_told) == [], "a bound is placed nowhere"
    assert TOLD_BOUNDS & not_told == set()
    for key in sorted(TOLD_BOUNDS):
        assert form._range(bounds[key]) in _before_example(), key  # noqa: SLF001
    for name, unit in law_module.SIGNALS.items():
        line = next(
            ln for ln in _before_example().splitlines() if ln.strip().startswith(name + " ")
        )
        assert unit in line
    assert list(form.SIGNAL_MEANINGS) == list(law_module.SIGNALS)


def test_every_not_told_entry_is_of_something_the_schema_has_and_gives_its_reason() -> None:
    known = (
        set(_fields())
        | set(_limits())
        | set(_constants())
        | {f"FIELD_BOUNDS.{k}" for k in answer_module.FIELD_BOUNDS}
        | NOT_A_FIELD_OF_THE_ANSWER
    )
    assert sorted(set(form.NOT_TOLD) - known) == [], "an entry of NOT_TOLD names nothing"
    for key, reason in form.NOT_TOLD.items():
        assert len(reason.split()) >= 5, f"{key}: no reason"


def test_every_refusal_name_the_scorer_gives_a_law_s_number_is_told_or_listed() -> None:
    assert "answer.NOT_A_NUMBER" in form.NOT_TOLD
    assert answer_module.NOT_A_NUMBER not in block()


# ── the rules the block lists, and a case for each ──────────────────────────────────────────────


def test_each_rule_the_block_lists_is_printed_and_has_cases_and_no_case_is_for_no_rule() -> None:
    rules = (*form.REFUSED, *form.NOT_JUDGED)
    keys = [r.key for r in rules]
    assert len(keys) == len(set(keys))
    assert sorted(cases()) == sorted(keys), "a rule without a case, or a case without a rule"
    for rule in rules:
        assert all(cases()[rule.key]), rule.key
        if rule.name is not None:
            assert f"({rule.name})" in _one_line(), rule.key
    assert set(form_names()) == {r.name for r in rules if r.name}


def form_names() -> list[str]:
    return [r.name for r in (*form.REFUSED, *form.NOT_JUDGED) if r.name]


@pytest.mark.parametrize("rule", [r.key for r in (*form.REFUSED, *form.NOT_JUDGED)])
def test_a_rule_s_words_are_in_the_block(rule: str) -> None:
    both = {r.key: r for r in (*form.REFUSED, *form.NOT_JUDGED)}
    text = both[rule].text.split("$")[0].strip()
    assert text in _one_line() or text.split(" (")[0] in _one_line(), rule
