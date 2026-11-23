"""The example the block quotes is an answer that parses, that names only fields the block tells.

It shows the form, so it must be a valid answer of the form, made of fields the block names. It
must not be a design to copy: every gain is the placeholder 1, the leak is a round 0.8, and every
setting and the command limit differ from each number a requirement of the kit names (so copying
the example meets none of them by accident). Whether it scores without a refusal is the scoring
row's, which needs the evaluation environment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from answer_form_cases import example
from pydantic import BaseModel

import physgate.evaluation.whole.answer as answer_module
import physgate.evaluation.whole.form as form
import physgate.evaluation.whole.law as law_module
from physgate.evaluation.whole.answer import WholeRunV3, parse_answer

BLOCK = form.render_answer_form()
BEFORE_EXAMPLE = BLOCK.split("AN EXAMPLE OF THE FORM ONLY")[0]
RECORDED = Path(__file__).with_name("recorded_law") / "law.json"
#: The numbers the kit's requirements name, as this row states them, apart from the module.
REQUIREMENT_NUMBERS = {99, 100, 101, 208, 1000, 1322, 1323, 1324, 19800, 20000, 20200, 400, 0.75}


def _parsed() -> WholeRunV3:
    answer = parse_answer(form.EXAMPLE_PATH.read_bytes())
    assert isinstance(answer, WholeRunV3)
    return answer


def _walk(value: Any) -> list[BaseModel]:
    """Every model instance reachable in ``value``."""
    found: list[BaseModel] = []
    if isinstance(value, BaseModel):
        found.append(value)
        for name in type(value).model_fields:
            found.extend(_walk(getattr(value, name)))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_walk(item))
    elif isinstance(value, tuple | list):
        for item in value:
            found.extend(_walk(item))
    return found


def test_the_example_is_an_answer_of_version_3_within_the_size_limit() -> None:
    raw = form.EXAMPLE_PATH.read_bytes()
    assert len(raw) < answer_module.MAX_ANSWER_BYTES // 20
    answer = _parsed()
    assert answer.controller.structure == "sampled_law"
    assert json.loads(raw) == example()


def test_every_field_the_example_writes_is_one_the_block_names() -> None:
    models = _walk(_parsed())
    assert {type(m).__name__ for m in models} >= {
        "WholeRunV3",
        "ParametersV3",
        "SampledLaw",
        "Memory",
        "Line",
        "Term",
        "Measure",
    }
    for model in models:
        for field in model.model_fields_set:
            key = f"{type(model).__name__}.{field}"
            owner = next(
                m.__name__
                for m in type(model).__mro__
                if field in getattr(m, "model_fields", {}) and m.__name__ != "BaseModel"
            )
            assert key not in form.NOT_TOLD and f"{owner}.{field}" not in form.NOT_TOLD, key
            assert re.search(rf'(?<![A-Za-z0-9_])"?{field}"?(?![A-Za-z0-9_])', BEFORE_EXAMPLE), (
                f"{key} is not named in the block"
            )


def test_the_example_writes_none_of_the_fields_a_designer_is_not_told() -> None:
    text = form.EXAMPLE_PATH.read_text()
    for key in form.NOT_TOLD:
        if key.split(".")[0] in {"WholeRunV3", "ParametersV3", "SampledLaw"} and ":" not in key:
            assert f'"{key.split(".", 1)[1]}"' not in text, key


def test_the_example_is_no_design_to_copy() -> None:
    doc = example()
    gains = {n: m for n, m in doc["controller"]["coefficients"].items() if n.startswith("k_")}
    assert gains and all(m["value"] == 1 for m in gains.values())
    assert doc["controller"]["coefficients"]["leak"]["value"] == 0.8
    named = [m["value"] for m in doc["parameters"].values()]
    named.append(doc["controller"]["command_limit"]["value"])
    assert REQUIREMENT_NUMBERS.isdisjoint(named), sorted(REQUIREMENT_NUMBERS & set(named))
    for value in named:
        assert len(re.sub(r"[.-]|0+$", "", str(value)).strip("0")) <= 3, value
    assert "not a design, not advice and not a starting point" in " ".join(BLOCK.split())


def test_the_example_is_not_a_recorded_design_s_law() -> None:
    recorded = json.loads(RECORDED.read_text())
    assert json.dumps(recorded, sort_keys=True) != json.dumps(example(), sort_keys=True)


def test_the_example_s_settings_and_timing_are_inside_the_ranges_the_block_tells() -> None:
    answer = _parsed()
    for name, (unit, bound_name) in answer_module.SETTINGS.items():
        measure = getattr(answer.parameters, name)
        if measure is None:
            continue
        assert answer_module.setting_problem(name, measure.value, measure.unit) is None, name
        assert measure.unit == unit
        assert answer_module.FIELD_BOUNDS[bound_name].low <= measure.value
    controller = answer.controller
    assert isinstance(controller, answer_module.SampledLaw)
    assert controller.period.value == 1 / answer.parameters.update_rate.value
    assert float(controller.sensor_delay.value) + float(controller.compute_delay.value) < float(
        controller.period.value
    )
    assert law_module.PERIOD in {
        f for line in controller.lines for t in line.terms for f in t.coefficients
    }
