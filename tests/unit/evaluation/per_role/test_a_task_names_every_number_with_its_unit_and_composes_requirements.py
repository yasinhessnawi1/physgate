from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, external_task, own_task, write_task_dir

from physgate.evaluation.per_role.answer import LtiTf, read_lti_tf
from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.task import canonical_json, load_task, parse_task, task_bytes


def _parse(task: dict[str, Any]) -> None:
    parse_task(json.dumps(task).encode())


def test_a_valid_own_task_and_a_valid_external_task_parse() -> None:
    assert parse_task(json.dumps(own_task()).encode()).id == "control.pendulum_01"
    assert parse_task(json.dumps(external_task()).encode()).tier == "external"


@pytest.mark.parametrize("value", [2.0, 2], ids=["float", "int"])
def test_a_bare_number_where_a_measure_belongs_is_refused(value: object) -> None:
    with pytest.raises(TaskFormatError):
        _parse(own_task(inputs=[value]))


@pytest.mark.parametrize("value", ["2.0", True, None], ids=["string", "boolean", "null"])
def test_a_value_that_is_not_a_number_is_refused_even_with_its_unit(value: object) -> None:
    with pytest.raises(TaskFormatError):
        _parse(own_task(inputs=[{"name": "plant_gain", "value": value, "unit": "1"}]))


@pytest.mark.parametrize("unit", ["", "10**10**10*m", "km⁹⁹", "m (metres)"])
def test_an_empty_or_unbounded_unit_is_refused(unit: str) -> None:
    with pytest.raises(TaskFormatError):
        _parse(own_task(inputs=[{"name": "plant_gain", "value": 2.0, "unit": unit}]))


def test_nan_and_infinity_are_not_numbers_here() -> None:
    for raw in (b"NaN", b"Infinity"):
        text = json.dumps(own_task()).replace('"value": 2.0', '"value": ' + raw.decode())
        with pytest.raises(TaskFormatError):
            parse_task(text.encode())


def test_a_bound_is_a_measure_never_a_bare_number() -> None:
    specs = own_task()["specs"]
    specs[0]["bound"] = 0
    with pytest.raises(TaskFormatError):
        _parse(own_task(specs=specs))


def test_an_interval_is_two_measures_in_one_unit_lower_first() -> None:
    specs = own_task()["specs"]
    specs[1]["bound"] = [{"value": 2.0, "unit": "s"}, {"value": 0.1, "unit": "s"}]
    with pytest.raises(TaskFormatError, match="upper end first"):
        _parse(own_task(specs=specs))
    specs[1]["bound"] = [{"value": 0.1, "unit": "s"}, {"value": 2.0, "unit": "ms"}]
    with pytest.raises(TaskFormatError, match="two units"):
        _parse(own_task(specs=specs))
    specs[1]["bound"] = {"value": 2.0, "unit": "s"}
    with pytest.raises(TaskFormatError, match="interval"):
        _parse(own_task(specs=specs))


def test_an_own_task_that_tests_one_requirement_alone_is_refused() -> None:
    specs = own_task()["specs"]
    for spec in specs:
        spec["composes"] = ["recover_tilt"]
    with pytest.raises(TaskFormatError, match="composes at least two"):
        _parse(own_task(specs=specs))


def test_a_published_task_is_taken_as_published_even_with_one_requirement() -> None:
    assert parse_task(json.dumps(external_task()).encode()).specs[0].composes == ("as_posed",)


def test_a_held_out_task_carries_a_canary() -> None:
    with pytest.raises(TaskFormatError, match="canary"):
        _parse(own_task(tier="held_out"))
    _parse(own_task(tier="held_out", canary="0123456789abcdef0123456789abcdef"))


def test_a_task_is_external_exactly_when_it_comes_from_a_benchmark() -> None:
    with pytest.raises(TaskFormatError, match="external exactly"):
        _parse(own_task(tier="external"))
    with pytest.raises(TaskFormatError, match="external exactly"):
        _parse(external_task(tier="visible"))


def test_an_external_task_names_the_commit_and_the_bytes_it_came_from() -> None:
    source = external_task()["source"]
    source["upstream_sha"] = "main"
    with pytest.raises(TaskFormatError):
        _parse(external_task(source=source))


def test_a_task_with_no_headline_spec_decides_nothing_and_is_refused() -> None:
    specs = own_task()["specs"]
    for spec in specs:
        spec["counts"] = "secondary"
    with pytest.raises(TaskFormatError, match="no headline"):
        _parse(own_task(specs=specs))


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(TaskFormatError):
        _parse(own_task(solution="leaked"))


def test_the_same_task_serialises_to_the_same_bytes_whatever_its_key_order() -> None:
    task = own_task()
    reordered = dict(reversed(list(task.items())))
    first = task_bytes(parse_task(json.dumps(task).encode()))
    second = task_bytes(parse_task(json.dumps(reordered, indent=3).encode()))
    assert first == second
    assert task_bytes(parse_task(first)) == first


def test_canonical_bytes_do_not_depend_on_the_order_keys_were_written_in() -> None:
    first = canonical_json({"b": 1.0, "a": [0.1, {"d": 2, "c": 3}]})
    second = canonical_json({"a": [0.1, {"c": 3, "d": 2}], "b": 1.0})
    assert first == second == b'{"a":[0.1,{"c":3,"d":2}],"b":1.0}\n'
    with pytest.raises(ValueError):
        canonical_json({"a": float("nan")})


def test_a_task_directory_loads_with_one_good_and_its_bad_references(tmp_path: Path) -> None:
    root = write_task_dir(
        tmp_path / "t",
        own_task(),
        {"good": (controller(), None), "bad_slow": (controller(), "settling")},
    )
    loaded = load_task(root)
    assert [(ref.name, ref.fails) for ref in loaded.references] == [
        ("bad_slow", "settling"),
        ("good", None),
    ]


@pytest.mark.parametrize(
    "references",
    [
        {"good": (controller(), None)},
        {"bad_slow": (controller(), "settling")},
        {"good": (controller(), None), "bad_slow": (controller(), "no_such_spec")},
    ],
    ids=["no bad", "no good", "bad names an unknown spec"],
)
def test_a_task_directory_without_its_references_is_refused(
    tmp_path: Path, references: dict[str, tuple[dict[str, Any], str | None]]
) -> None:
    root = write_task_dir(tmp_path / "t", own_task(), references)
    with pytest.raises(TaskFormatError):
        load_task(root)


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_controller_answer_reads_back_its_coefficients(tmp_path: Path) -> None:
    answer = read_lti_tf(_write(tmp_path / "a.json", controller()))
    assert isinstance(answer, LtiTf)
    assert (answer.num_values(), answer.den_values()) == ([1.0, 1.0], [1.0, 0.0])


@pytest.mark.parametrize(
    "change",
    [
        {"gain": 2.0},
        {"num": [1.0, 1.0]},
        {"num": [{"value": 1.0, "unit": "1"}, {"value": 1.0, "unit": "1"}]},
        {
            "num": [
                {"value": 1.0, "unit": "s**2"},
                {"value": 1.0, "unit": "s"},
                {"value": 1.0, "unit": "1"},
            ]
        },
        {"den": [{"value": 0.0, "unit": "s"}, {"value": 1.0, "unit": "1"}]},
        {"den": [{"value": 1.0, "unit": "1"}] * 12, "num": [{"value": 1.0, "unit": "1"}]},
        {"form": "state_feedback"},
    ],
    ids=[
        "bare gain",
        "bare coefficients",
        "unit not its power",
        "improper",
        "leading zero",
        "order above ten",
        "other form",
    ],
)
def test_a_controller_answer_off_its_schema_is_refused(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    with pytest.raises(TaskFormatError):
        read_lti_tf(_write(tmp_path / "a.json", controller(**change)))


def test_a_missing_or_linked_answer_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TaskFormatError, match="no answer"):
        read_lti_tf(tmp_path / "absent.json")
    target = _write(tmp_path / "real.json", controller())
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(TaskFormatError, match="no answer"):
        read_lti_tf(tmp_path / "link.json")
