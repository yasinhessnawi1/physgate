"""The exact part of the stability verdict is one definition, on the subspace the law keeps at rest.

With the plant at rest and the command zero the plant stays at rest, so the state that matters is
the wheel angle (the travel, which is kept) and the law's memory, and its update is the law's own
numbers: the wheel angle is the one signal that is not zero at rest with a travel offset (tilt,
tilt rate and wheel speed are zero, the reference is zero in the loop). The rest subspace is the
largest part of that state on which the command stays zero at every update, the unobservable
subspace of the command row and the update, found in rationals on the numbers as written. On it,
an eigenvalue of exactly 1 of algebraic multiplicity above the number of modes the set-aside rule
sets aside, or any eigenvalue of exactly -1, makes the law unstable at every plant point and every
gain, a chain behind a set-aside mode included. Everything else is judged in floating point as
before: laws built to be stable stay stable, and the scores of the laws that were stable do not
move.
"""

from __future__ import annotations

import importlib
import random
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
scope: Any = importlib.import_module("test_a_law_s_scope_flags_and_held_modes_reach_the_score")
exact: Any = importlib.import_module(
    "test_a_mode_at_one_or_minus_one_is_decided_exactly_never_by_a_float"
)

RADIUS = 0.04
FED_UNIT = {"wheel_angle": "1/rad", "tilt": "1/rad", "tilt_rate": "s/rad"}


def _points() -> list[dict[str, float]]:
    plant = helpers._plant()
    return [nominal(plant), *corners(plant, LOOP_INPUTS)]


POINTS = _points()
assert len(POINTS) == 17


def _term(of: str, *coefficients: str) -> dict[str, Any]:
    return {"sign": 1, "coefficients": list(coefficients), "of": of}


def _chained(
    *,
    pair: float | None,
    chain: int,
    feed: float,
    fed: str = "tilt",
    read_by_command: bool = False,
) -> dict[str, Any]:
    """A head, then ``chain`` integrators one behind the other, all of it unread by default.

    The head is one state ``h' = h + feed*<fed>`` (``pair`` None) or the pair ``h' = a h + (1-a) g
    + feed*<fed>``, ``g' = a g + (1-a) h`` (an eigenvalue of exactly 1, the other ``2a - 1``); the
    chain is ``c1' = c1 + h``, ``c2' = c2 + c1``, ... The command holds the good gains and the
    wheel-angle gain, so the wheels return and the head is the kernel the set-aside rule keeps.
    """
    coefficients = dict(helpers._good_coefficients(RADIUS))
    coefficients["feed"] = helpers._m(feed, FED_UNIT[fed])
    memory = [{"name": "h", "unit": "1", "next": "h_now"}]
    lines: list[dict[str, Any]] = []
    if pair is None:
        lines.append(
            {
                "name": "h_now",
                "unit": "1",
                "terms": [_term("previous.h"), _term(fed, "feed")],
            }
        )
    else:
        coefficients["a"] = helpers._m(pair, "1")
        coefficients["b"] = helpers._m(round(1 - pair, 6), "1")
        memory.append({"name": "g", "unit": "1", "next": "g_now"})
        lines.append(
            {
                "name": "h_now",
                "unit": "1",
                "terms": [
                    _term("previous.h", "a"),
                    _term("previous.g", "b"),
                    _term(fed, "feed"),
                ],
            }
        )
        lines.append(
            {
                "name": "g_now",
                "unit": "1",
                "terms": [_term("previous.g", "a"), _term("previous.h", "b")],
            }
        )
    last = "h"
    for i in range(chain):
        name = f"c{i + 1}"
        memory.append({"name": name, "unit": "1", "next": f"{name}_now"})
        source = last
        lines.append(
            {
                "name": f"{name}_now",
                "unit": "1",
                "terms": [_term(f"previous.{name}"), _term(f"previous.{source}")],
            }
        )
        last = name
    terms = [*helpers._no_travel_terms(), _term("wheel_angle", "distance_gain")]
    if read_by_command:
        terms.append(_term(f"previous.{last}", "read"))
        coefficients["read"] = helpers._m(1e-3, "1")
    return helpers._law(terms, coefficients, memory, lines)


def _stable_at(controller: dict[str, Any], values: dict[str, float]) -> bool:
    loop = helpers._loop_of(controller, values)
    return loop_module.stable(loop_module.system(values, loop), 1.0)


def _circle(controller: dict[str, Any]) -> Any:
    return exact._circle(controller)


def _unstable_everywhere(controller: dict[str, Any]) -> None:
    stable = [_stable_at(controller, values) for values in POINTS]
    assert not any(stable), f"stable at {sum(stable)} of {len(POINTS)} plant points"
    for values in POINTS:
        assert not loop_module.margins(values, helpers._loop_of(controller, values)).stable


def _stable_everywhere(controller: dict[str, Any]) -> None:
    stable = [_stable_at(controller, values) for values in POINTS]
    assert all(stable), f"stable at only {sum(stable)} of {len(POINTS)} plant points"


# ── the reviewer's law: the unread pair with 0.9 and 0.1, a state integrating its first state ──


def _three_state(a: float = 0.9, feed: float = 100000.0) -> dict[str, Any]:
    """``u0' = a u0 + (1-a) u1 + feed*tilt``, ``u1' = a u1 + (1-a) u0``, ``v' = v + u0``."""
    return _chained(pair=a, chain=1, feed=feed)


def test_the_reviewer_s_three_state_law_is_unstable_at_all_17_plant_points() -> None:
    _unstable_everywhere(_three_state())


def test_the_reviewer_s_three_state_law_names_the_reason_in_the_record(tmp_path: Path) -> None:
    record = scope._record(tmp_path, _three_state())
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail", rows["pm"]
    assert "exactly 1" in rows["pm"]["reason"], rows["pm"]["reason"]
    assert record["unit_circle"] == {
        "at_one_not_set_aside": 1,
        "algebraic_at_one": 2,
        "set_aside": 1,
        "at_minus_one": 0,
    }
    assert record["outcome"] == "fail"


def test_the_same_law_at_a_coupling_of_0_99_and_a_feed_of_300_is_unstable_everywhere() -> None:
    _unstable_everywhere(_three_state(a=0.99, feed=300.0))


# ── the family: one, two and three integrators behind a set-aside or held head ──


def _family(count: int) -> list[tuple[dict[str, Any], int]]:
    """Laws and the algebraic multiplicity at 1 the construction gives, from a fixed seed."""
    rng = random.Random(158_6)
    out = []
    for _ in range(count):
        pair = rng.choice([None, 0.9, 0.9, 0.99, 0.5])
        chain = rng.choice([1, 1, 2, 3])
        feed = rng.choice([1.0, 300.0, 10000.0, 100000.0, 1000000.0])
        fed = rng.choice(["tilt", "tilt_rate"])
        out.append((_chained(pair=pair, chain=chain, feed=feed, fed=fed), 1 + chain))
    return out


def test_no_stable_verdict_at_any_plant_point_where_a_is_above_the_modes_set_aside() -> None:
    wrong = []
    for controller, multiplicity in _family(90):
        for values in POINTS:
            if _stable_at(controller, values):
                wrong.append((multiplicity, values["wheel_radius"]))
    assert not wrong, (
        f"{len(wrong)} stable verdicts at an eigenvalue of exactly 1, e.g. {wrong[:3]}"
    )
    for controller, multiplicity in _family(90):
        circle = _circle(controller)
        assert circle.algebraic_at_one == multiplicity
        assert circle.set_aside == 1


def test_a_chain_behind_a_head_the_command_reads_is_unstable_too() -> None:
    for chain in (1, 2, 3):
        controller = _chained(pair=None, chain=chain, feed=3.0, read_by_command=True)
        _unstable_everywhere(controller)


# ── a state integrating the wheel angle directly, a chain at -1 ──


def test_a_state_integrating_the_wheel_angle_that_nothing_reads_is_unstable() -> None:
    controller = helpers._stable_law(RADIUS)
    controller["memory"].append({"name": "v", "unit": "1", "next": "v_now"})
    controller["coefficients"]["w"] = helpers._m(1.0, "1/rad")
    controller["lines"].insert(
        0, {"name": "v_now", "unit": "1", "terms": [_term("previous.v"), _term("wheel_angle", "w")]}
    )
    _unstable_everywhere(controller)


def test_a_chain_at_exactly_minus_one_is_unstable_and_counted() -> None:
    controller = helpers._stable_law(RADIUS)
    controller["coefficients"]["m"] = helpers._m(-1.0, "1")
    controller["memory"] += [
        {"name": "z1", "unit": "1", "next": "z1_now"},
        {"name": "z2", "unit": "1", "next": "z2_now"},
    ]
    controller["lines"][0:0] = [
        {"name": "z1_now", "unit": "1", "terms": [_term("previous.z1", "m")]},
        {
            "name": "z2_now",
            "unit": "1",
            "terms": [_term("previous.z2", "m"), _term("previous.z1")],
        },
    ]
    assert _circle(controller).at_minus_one == 1
    _unstable_everywhere(controller)


# ── the fifth review's law and family, as before ──


def test_the_fifth_review_s_law_is_still_unstable_with_its_count_unchanged() -> None:
    _unstable_everywhere(exact._reviewer())
    circle = _circle(exact._reviewer())
    assert (circle.at_one, circle.algebraic_at_one, circle.set_aside) == (1, 1, 0)


# ── laws that are stable by construction stay stable: a false unstable is a wrong score too ──


def test_chained_eigenvalues_at_one_minus_a_millionth_are_stable() -> None:
    controller = helpers._stable_law(RADIUS)
    controller["coefficients"]["p"] = helpers._m(0.999999, "1")
    controller["coefficients"]["feed"] = helpers._m(3.0, "1/rad")
    controller["memory"] += [{"name": f"c{i}", "unit": "1", "next": f"c{i}_now"} for i in (1, 2, 3)]
    controller["lines"][0:0] = [
        {
            "name": "c1_now",
            "unit": "1",
            "terms": [_term("previous.c1", "p"), _term("tilt", "feed")],
        },
        {"name": "c2_now", "unit": "1", "terms": [_term("previous.c2", "p"), _term("previous.c1")]},
        {"name": "c3_now", "unit": "1", "terms": [_term("previous.c3", "p"), _term("previous.c2")]},
    ]
    circle = _circle(controller)
    assert (circle.at_one, circle.algebraic_at_one, circle.set_aside) == (0, 0, 0)
    _stable_everywhere(controller)


def test_a_held_mode_properly_set_aside_with_nothing_behind_it_stays_stable() -> None:
    for pair in (None, 0.9):
        controller = _chained(pair=pair, chain=0, feed=300.0)
        circle = _circle(controller)
        assert (circle.at_one, circle.algebraic_at_one, circle.set_aside) == (0, 1, 1)
        _stable_everywhere(controller)


def test_two_independent_set_aside_modes_stay_stable() -> None:
    controller = helpers._stable_law(RADIUS)
    controller["coefficients"]["f1"] = helpers._m(2.0, "1/rad")
    controller["coefficients"]["f2"] = helpers._m(5.0, "s/rad")
    controller["memory"] += [
        {"name": "h1", "unit": "1", "next": "h1_now"},
        {"name": "h2", "unit": "1", "next": "h2_now"},
    ]
    controller["lines"][0:0] = [
        {"name": "h1_now", "unit": "1", "terms": [_term("previous.h1"), _term("tilt", "f1")]},
        {"name": "h2_now", "unit": "1", "terms": [_term("previous.h2"), _term("tilt_rate", "f2")]},
    ]
    circle = _circle(controller)
    assert (circle.at_one, circle.algebraic_at_one, circle.set_aside) == (0, 2, 2)
    _stable_everywhere(controller)


@pytest.mark.parametrize("pole", [1.0, 0.999999])
def test_an_inert_state_at_one_is_set_aside_and_its_margins_equal_the_earlier_ones(
    pole: float,
) -> None:
    controller = helpers._with_inert_state(helpers._stable_law(RADIUS), pole)
    circle = _circle(controller)
    assert circle.at_one == 0
    _stable_everywhere(controller)
