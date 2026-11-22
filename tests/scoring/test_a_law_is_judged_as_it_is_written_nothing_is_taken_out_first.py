"""Nothing is taken out of a law before it is judged.

The fourth review's law ``z' = 2 z + 0.0 * tilt * tilt_rate``, a state nothing reads, scored stable
with a 68 degree phase margin when the dead term took the whole line out, its live ``2 z`` with
it. The rule now: a law is judged as written. A term the scorer cannot take (not one variable, or a
signal outside the closed list), of any weight, zero included, in any line, read or not, makes the
law unscored by name, but only after every other check has run on it; any other fault is the
ordinary fail. A term of weight zero on a signal the scorer does take stays in the matrices as a
zero, and an unread line or state of in-scope terms is judged: a state doubling every update is
unstable, and one held at rest follows the rule for a held mode.

The reviewer's independent eigenvalues for the three laws below are those of the memory's own
update matrix, since nothing reads the state and the plant under the good gains is stable: 2 for
the doubling state, 1 for an integrator of the wheel speed, 1 twice (a Jordan block) for the chain.
"""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
scope: Any = importlib.import_module("test_a_law_s_scope_flags_and_held_modes_reach_the_score")

WEIGHTS = [0.0, 5e-324, 1e-9, 3.0]
RADIUS = 0.04


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _record(tmp_path: Path, controller: dict[str, Any], **document: Any) -> dict[str, Any]:
    record: dict[str, Any] = scope._record(tmp_path, controller, **document)
    return record


def _base(memory: list[dict[str, Any]], lines: list[dict[str, Any]], extra: dict[str, Any]) -> Any:
    """The good gains with a wheel-angle gain, and memory nothing reads."""
    wheel = {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}
    return helpers._law(
        [*helpers._no_travel_terms(), wheel],
        {**helpers._good_coefficients(RADIUS), **extra},
        memory,
        lines,
    )


def _doubling() -> tuple[dict[str, Any], list[list[float]]]:
    controller = _base(
        [{"name": "z", "unit": "1", "next": "z_now"}],
        [{"name": "z_now", "unit": "1", "terms": [{"sign": 1, "number": 2, "of": "previous.z"}]}],
        {},
    )
    return controller, [[2.0]]


def _wheel_speed_integrator() -> tuple[dict[str, Any], list[list[float]]]:
    controller = _base(
        [{"name": "z", "unit": "1", "next": "z_now"}],
        [
            {
                "name": "z_now",
                "unit": "1",
                "terms": [
                    {"sign": 1, "of": "previous.z"},
                    {"sign": 1, "coefficients": ["kv"], "of": "wheel_speed"},
                ],
            }
        ],
        {"kv": _m(1.0, "s/rad")},
    )
    return controller, [[1.0]]


def _jordan() -> tuple[dict[str, Any], list[list[float]]]:
    controller = _base(
        [
            {"name": "z1", "unit": "1", "next": "first"},
            {"name": "z2", "unit": "1", "next": "second"},
        ],
        [
            {"name": "first", "unit": "1", "terms": [{"sign": 1, "of": "previous.z1"}]},
            {
                "name": "second",
                "unit": "1",
                "terms": [{"sign": 1, "of": "previous.z2"}, {"sign": 1, "of": "previous.z1"}],
            },
        ],
        {},
    )
    return controller, [[1.0, 0.0], [1.0, 1.0]]


LAWS = {"doubling": _doubling, "wheel_speed_integrator": _wheel_speed_integrator, "jordan": _jordan}


def _with_term(controller: dict[str, Any], line: str, weight: float, of: str) -> dict[str, Any]:
    out = copy.deepcopy(controller)
    target = next(x for x in out["lines"] if x["name"] == line)
    target["terms"].append({"sign": 1, "number": weight, "of": of})
    return out


def _last_unread_line(controller: dict[str, Any]) -> str:
    return str(next(x for x in controller["lines"] if x["name"] != "command")["name"])


@pytest.mark.parametrize("name", sorted(LAWS))
def test_the_reviewer_s_laws_are_unstable_as_his_own_eigenvalues_say(
    tmp_path: Path, name: str
) -> None:
    controller, update = LAWS[name]()
    eigenvalues = np.linalg.eigvals(np.array(update))
    assert max(abs(eigenvalues)) >= 1.0  # his verdict: not stable
    record = _record(tmp_path, controller)
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail", rows["pm"]
    assert "unstable" in rows["pm"]["reason"]
    assert record["outcome"] == "fail"


@pytest.mark.parametrize("weight", WEIGHTS)
@pytest.mark.parametrize("where", ["the_unread_line", "the_command"])
@pytest.mark.parametrize("name", sorted(LAWS))
def test_the_same_laws_with_a_term_the_scorer_cannot_take_are_unscored_by_name_each_time(
    tmp_path: Path, name: str, where: str, weight: float
) -> None:
    controller, _ = LAWS[name]()
    line = "command" if where == "the_command" else _last_unread_line(controller)
    carried = _with_term(controller, line, weight, "tilt*tilt_rate")
    record = _record(tmp_path, carried)
    assert record["refusal"]["name"] == "nonlinear", record
    assert record["outcome"] == "unscored"
    assert record["specs"] == []


@pytest.mark.parametrize("weight", WEIGHTS)
def test_the_fourth_review_s_law_with_its_dead_term_is_unscored_never_stable(
    tmp_path: Path, weight: float
) -> None:
    controller, _ = _doubling()
    carried = _with_term(controller, "z_now", weight, "tilt*tilt_rate")
    record = _record(tmp_path, carried)
    assert record["outcome"] == "unscored"
    assert record["refusal"]["name"] == "nonlinear"
    assert not any(r["verdict"] == "pass" for r in record["specs"])


def _undeclared(controller: dict[str, Any]) -> None:
    command = next(x for x in controller["lines"] if x["name"] == "command")
    command["terms"][0]["coefficients"] = ["not_declared"]


def _unbalanced(controller: dict[str, Any]) -> None:
    controller["coefficients"]["angle_gain"]["unit"] = "1/m"


@pytest.mark.parametrize("weight", WEIGHTS)
@pytest.mark.parametrize("fault", [_undeclared, _unbalanced], ids=["undeclared", "unbalanced"])
@pytest.mark.parametrize("name", sorted(LAWS))
def test_an_invalid_law_with_such_a_term_is_a_fail_each_time(
    tmp_path: Path, name: str, fault: Any, weight: float
) -> None:
    controller, _ = LAWS[name]()
    carried = _with_term(controller, _last_unread_line(controller), weight, "tilt*tilt_rate")
    fault(carried)
    record = _record(tmp_path, carried)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "refusal" not in record


def test_a_valid_law_with_a_zero_weight_term_on_a_signal_the_scorer_takes_scores_as_without(
    tmp_path: Path,
) -> None:
    plain = _record(tmp_path, helpers._recorded_controller())
    controller = helpers._recorded_controller()
    controller["coefficients"]["off"] = _m(0.0, "1/rad")
    command = next(x for x in controller["lines"] if x["name"] == "command")
    command["terms"].append({"sign": 1, "coefficients": ["off"], "of": "tilt"})
    carried = _record(tmp_path, controller)
    assert carried["specs"] == plain["specs"]
    assert carried["outcome"] == plain["outcome"]
    assert {r["name"]: r["verdict"] for r in carried["specs"]}["pm"] == "pass"
    assert "refusal" not in carried


def test_a_zero_weight_term_in_a_line_nothing_reads_stays_and_the_unread_state_is_judged(
    tmp_path: Path,
) -> None:
    controller, _ = _doubling()
    controller["coefficients"]["off"] = _m(0.0, "1")
    line = next(x for x in controller["lines"] if x["name"] == "z_now")
    line["terms"].append({"sign": 1, "coefficients": ["off"], "of": "tilt"})
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert "refusal" not in record


# ── the scorer's own fault is its own outcome ───────────────────────────────────────────────


def test_a_mismatch_of_the_written_numbers_is_a_scorer_fault_apart_from_every_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A constructed mismatch: one term of the law has no number written for it."""
    import dataclasses

    from physgate.evaluation.whole import law as law_module

    real = law_module.written_from

    def one_short(document: Any, *rest: Any, **named: Any) -> Any:
        written = real(document, *rest, **named)
        return dataclasses.replace(written, numbers=dict(list(written.numbers.items())[1:]))

    monkeypatch.setattr(law_module, "written_from", one_short)
    scenario, root = helpers._scenario(tmp_path, copy.deepcopy(helpers.SPECS))
    path = root / "mismatch.json"
    path.write_bytes(helpers._answer(helpers._recorded_controller(), 3))
    record = scenario.record(path)
    assert record["outcome"] == "scorer_fault"
    assert record["outcome"] not in ("pass", "fail", "unscored")
    assert record["refusal"]["name"] == "written_numbers_do_not_match"
    assert record["answer_valid"] is True
    assert record["specs"], "a row for each spec, so a count of the fault can be taken from rows"
    assert {row["verdict"] for row in record["specs"]} == {"scorer_fault"}
    assert scenario.score(path) == "scorer_fault"


# ── the lows ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ["z\U0001f600", "zé", "Z", "z-1", "а"])
def test_a_memory_state_name_that_is_not_plain_ascii_is_a_malformed_name_never_nonlinear(
    tmp_path: Path, state: str
) -> None:
    controller = scope._unstable(helpers._recorded_controller())
    controller["memory"].append({"name": state, "unit": "1", "next": "carried"})
    controller["lines"].insert(
        0, {"name": "carried", "unit": "1", "terms": [{"sign": 1, "of": f"previous.{state}"}]}
    )
    record = _record(tmp_path, controller)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "refusal" not in record
    assert "nonlinear" not in record["reason"]


def test_a_not_a_number_is_refused_under_a_name_that_says_so(tmp_path: Path) -> None:
    text = helpers._answer(helpers._recorded_controller(), 3).decode()
    assert text.count('"value": 0.999') == 1
    scenario, root = helpers._scenario(tmp_path, copy.deepcopy(helpers.SPECS))
    path = root / "nan.json"
    path.write_text(text.replace('"value": 0.999', '"value": NaN'))
    record = scenario.record(path)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "number_is_not_a_number" in record["reason"]
    assert "number_overflows" not in record["reason"]
