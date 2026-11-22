"""An eigenvalue of exactly 1 or of exactly -1 is decided exactly, never by a rounded float.

The stability rule compares a floating-point eigenvalue with ``1 - 1e-12``. For a mode the law's
own numbers hold at exactly 1 that the set-aside rule does not set aside, the float can land
below that line (the fifth review's pair of unread states ``0.9, 0.1`` fed by the wheel angle
came back at ``1 - 2.5e-12``), so a law the project scores unstable scored stable, differently
at different plant points. The exact arithmetic that finds the held modes now decides: an
eigenvalue of exactly 1 not set aside, or of exactly -1 (never set aside), is unstable at every
plant point and every gain, whatever the floats say. Any other point on or within ``1e-12`` of
the unit circle stays a floating-point verdict, and a law whose only eigenvalue at 1 is a mode
that is properly set aside scores as it did, digit for digit.
"""

from __future__ import annotations

import importlib
import random
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
scope: Any = importlib.import_module("test_a_law_s_scope_flags_and_held_modes_reach_the_score")

RADIUS = 0.04
FEED_UNIT = {"wheel_angle": "1/rad", "wheel_speed": "s/rad", "tilt": "1/rad", "tilt_rate": "s/rad"}


def _points() -> list[dict[str, float]]:
    plant = helpers._plant()
    return [nominal(plant), *corners(plant, LOOP_INPUTS)]


POINTS = _points()
assert len(POINTS) == 1 + 2**4


def _coupled(
    rows: list[list[float]], feeds: list[float], fed: str, *, unit_of_state: str = "1"
) -> dict[str, Any]:
    """Unread memory states ``s_i' = sum_j rows[i][j] s_j + feeds[i] * <fed>`` and the good gains.

    The command holds the good gains with the wheel-angle gain and reads no memory.
    """
    n = len(rows)
    coefficients = dict(helpers._good_coefficients(RADIUS))
    memory = [{"name": f"s{i}", "unit": unit_of_state, "next": f"f{i}"} for i in range(n)]
    lines = []
    for i in range(n):
        terms = []
        for j in range(n):
            if rows[i][j] != 0:
                coefficients[f"a{i}{j}"] = helpers._m(rows[i][j], "1")
                terms.append({"sign": 1, "coefficients": [f"a{i}{j}"], "of": f"previous.s{j}"})
        coefficients[f"k{i}"] = helpers._m(feeds[i], FEED_UNIT[fed])
        terms.append({"sign": 1, "coefficients": [f"k{i}"], "of": fed})
        lines.append({"name": f"f{i}", "unit": unit_of_state, "terms": terms})
    wheel = {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}
    built: dict[str, Any] = helpers._law(
        [*helpers._no_travel_terms(), wheel], coefficients, memory, lines
    )
    return built


def _reviewer() -> dict[str, Any]:
    """The fifth review's law: two unread states, each 0.9 of itself and 0.1 of the other."""
    return _coupled([[0.9, 0.1], [0.1, 0.9]], [-1.625, -2.867], "wheel_angle")


def _stable_at(controller: dict[str, Any], values: dict[str, float]) -> bool:
    loop = helpers._loop_of(controller, values)
    return loop_module.stable(loop_module.system(values, loop), 1.0)


def _circle(controller: dict[str, Any]) -> Any:
    """The law's exact count of eigenvalues at 1 (not set aside) and at -1."""
    law_module = importlib.import_module("physgate.evaluation.whole.law")
    answer = helpers.parse_answer(helpers._answer(controller, 3))
    law = answer.controller
    values = {name: float(m.value) for name, m in law.coefficients.items()}
    return law_module.unit_circle(law, values, period=float(law.period.value), written=law.written)


def _not_set_aside(controller: dict[str, Any]) -> bool:
    """Whether the existing set-aside rule sets nothing aside for ``controller``."""
    law_module = importlib.import_module("physgate.evaluation.whole.law")
    answer = helpers.parse_answer(helpers._answer(controller, 3))
    law = answer.controller
    values = {name: float(m.value) for name, m in law.coefficients.items()}
    held = law_module.held_modes(law, values, period=float(law.period.value), written=law.written)
    return bool(held == ())


# ── the reviewer's law ──


def test_the_reviewer_s_law_is_unstable_at_every_plant_point() -> None:
    law = helpers._loop_of(_reviewer(), POINTS[0]).law
    ones = np.ones(2)
    assert np.array_equal(np.array(law.a) @ ones, ones), "its rows sum to exactly 1"
    assert not any(law.c), "the command reads no memory"
    stable = [_stable_at(_reviewer(), values) for values in POINTS]
    assert not any(stable), f"stable at {sum(stable)} of {len(POINTS)} plant points"
    for values in POINTS:
        margins = loop_module.margins(values, helpers._loop_of(_reviewer(), values))
        assert not margins.stable


def test_the_reviewer_s_law_is_a_fail_with_the_exact_reason_named_in_the_record(
    tmp_path: Path,
) -> None:
    record = scope._record(tmp_path, _reviewer())
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail", rows["pm"]
    assert "unstable" in rows["pm"]["reason"]
    assert "exactly 1" in rows["pm"]["reason"], rows["pm"]["reason"]
    assert record["unit_circle"] == {
        "at_one_not_set_aside": 1,
        "algebraic_at_one": 1,
        "set_aside": 0,
        "at_minus_one": 0,
    }
    assert record["outcome"] == "fail"


# ── the family the reviewer built to probe it ──


def _family(count: int) -> list[tuple[dict[str, Any], list[list[float]]]]:
    """Unread states coupled to each other with row sums of 1, fed by the wheel angle or speed.

    Each row is a tenths composition of 1 over the states (``a`` of itself, the rest of the
    next), so the rows sum to exactly 1 as written; a fixed seed.
    """
    rng = random.Random(158)
    out = []
    for _ in range(count):
        n = rng.choice([1, 2, 2, 3])
        rows = []
        for i in range(n):
            tenths = rng.randrange(0, 11)
            row = [0.0] * n
            if n == 1 or tenths == 10:
                row[i] = 1.0
            else:
                row[i] = tenths / 10
                row[(i + 1) % n] = (10 - tenths) / 10
            rows.append(row)
        fed = rng.choice(["wheel_angle", "wheel_speed"])
        feeds = [round(rng.uniform(-4.0, 4.0), 3) or 1.0 for _ in range(n)]
        out.append((_coupled(rows, feeds, fed), rows))
    return out


def test_the_family_of_unread_coupled_states_gets_no_stable_verdict_off_the_set_aside_kernel() -> (
    None
):
    judged = 0
    wrong = []
    for controller, _rows in _family(300):
        if not _not_set_aside(controller):
            continue
        judged += 1
        for values in POINTS:
            if _stable_at(controller, values):
                wrong.append((controller["coefficients"]["k0"], values["wheel_radius"]))
    assert judged >= 250, f"only {judged} of 300 laws leave the kernel not set aside"
    assert not wrong, (
        f"{len(wrong)} stable verdicts at an eigenvalue of exactly 1, e.g. {wrong[:3]}"
    )


def test_the_family_is_all_exact_eigenvalues_at_one_and_the_scorer_counts_them() -> None:
    for controller, _rows in _family(300):
        circle = _circle(controller)
        if _not_set_aside(controller):
            assert circle.at_one >= 1
        else:
            assert circle.at_one == 0


# ── an eigenvalue of exactly -1 ──


def _minus_one_pair() -> dict[str, Any]:
    return _coupled([[-0.9, -0.1], [-0.1, -0.9]], [0.3, 0.7], "wheel_angle")


def test_a_coupled_pair_at_exactly_minus_one_is_unstable_at_every_plant_point() -> None:
    assert not any(_stable_at(_minus_one_pair(), values) for values in POINTS)


def test_a_coupled_pair_at_exactly_minus_one_is_a_fail_with_the_exact_reason_named(
    tmp_path: Path,
) -> None:
    record = scope._record(tmp_path, _minus_one_pair())
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail", rows["pm"]
    assert "exactly -1" in rows["pm"]["reason"], rows["pm"]["reason"]
    assert record["unit_circle"] == {
        "at_one_not_set_aside": 0,
        "algebraic_at_one": 0,
        "set_aside": 0,
        "at_minus_one": 1,
    }


def test_a_three_state_ring_at_exactly_minus_one_is_unstable_and_counted_once() -> None:
    ring = _coupled(
        [[-0.5, -0.5, 0.0], [0.0, -0.5, -0.5], [-0.5, 0.0, -0.5]], [0.3, 0.7, 0.2], "tilt"
    )
    assert _circle(ring).at_minus_one == 1
    assert not any(_stable_at(ring, values) for values in POINTS)


# ── what stays as it was ──


def _same_as_before(controller: dict[str, Any], expected: list[tuple[Any, ...]]) -> None:
    for values, old in zip(POINTS, expected, strict=True):
        margins = loop_module.margins(values, helpers._si(controller, values["wheel_radius"], 3))
        now = (
            margins.stable,
            margins.phase_margin,
            margins.crossed,
            margins.upward,
            margins.downward,
        )
        # "as before" is the stored number to a relative 1e-9: another machine's BLAS moves the
        # phase margin by about 1e-13 degrees, a thousandth of a part in a million of the number
        assert (now[0], now[2]) == (old[0], old[2]), (values["wheel_radius"], now, old)
        for found, stored in ((now[1], old[1]), (now[3], old[3]), (now[4], old[4])):
            assert found == pytest.approx(stored, rel=1e-9, abs=0.0), (values["wheel_radius"], now)


RECORDED = [
    (True, 50.64325855119688, True, 5.165949448515451, 0.42624834978424053),
    (True, 64.83554249537303, True, 3.07287823684535, 0.4600005048365688),
    (True, 62.47989044207998, True, 2.7494173701980906, 0.4115793991225444),
    (True, 39.707498671851795, True, 8.244889868489757, 0.46016058725530334),
    (True, 38.30688062319285, True, 7.377006725482183, 0.41172263076037974),
    (True, 57.67462609091348, True, 4.002351997938345, 0.4462436516788688),
    (True, 58.606771413107566, True, 3.581051788135831, 0.399270635769176),
    (True, 29.91310161983361, True, 7.867214578463172, 0.4464256363789072),
    (True, 28.58407916231556, True, 7.039086724940568, 0.39943346418502307),
    (True, 63.66192195475489, True, 2.9486620803145267, 0.46277537015282694),
    (True, 60.820182693918355, True, 2.638276598549521, 0.4140621731088672),
    (True, 42.77282892174557, True, 7.841460284972343, 0.4629404846919805),
    (True, 41.67606076766063, True, 7.016043413862889, 0.41420990741460073),
    (True, 60.215413839716575, True, 3.8430145083244183, 0.44718653689146437),
    (True, 60.99346332304896, True, 3.438486663800237, 0.4001142696707478),
    (True, 33.48293114433574, True, 7.586158487631581, 0.44736997302464665),
    (True, 32.4652930519066, True, 6.787615485888281, 0.4002783969734357),
]
LEAK_FREE = [
    (True, 13.381983962054562, True, 3.066684219142708, 0.30869928209483233),
    (True, 14.969187441061592, True, 2.608880496255083, 0.1604374497615764),
    (True, 13.5011915884607, True, 2.3342614956020276, 0.14354929717540946),
    (True, 9.915820335824861, True, 3.1238214719504174, 0.2459183117500012),
    (True, 9.377719333612362, True, 2.7949981595090754, 0.2200321737021922),
    (True, 18.30109325214798, True, 3.569599077576327, 0.4058424598825187),
    (True, 17.507000839436415, True, 3.1938518067044903, 0.36312220099890513),
    (True, 10.513565411061904, True, 3.9954980924007004, 0.5617381805359801),
    (True, 10.808493207574088, True, 3.5749193463381213, 0.502607845517226),
    (True, 14.24060289284509, True, 2.4989707078192254, 0.1463929052521316),
    (True, 12.754636973584184, True, 2.235921158624591, 0.13098312569314216),
    (True, 9.274949381059201, True, 2.8552749194820337, 0.21987673179072395),
    (True, 8.647544892268144, True, 2.5547196651612536, 0.19673181268269938),
    (True, 17.73295697087471, True, 3.4074075146126686, 0.3731792966673884),
    (True, 16.84557579035979, True, 3.0487330398217325, 0.3338972654864948),
    (True, 10.538543019116275, True, 3.699317584841343, 0.5093074662874529),
    (True, 10.583390641066558, True, 3.3099157342738263, 0.4556961541111576),
]
INERT_ONE = [
    (True, 68.22897626211918, True, 4.06669309013652, 0.4536952826178145),
    (True, 56.8524591306132, True, 2.379268584819813, 0.4774676795649935),
    (True, 51.01141540002453, True, 2.1288192591468524, 0.4272079236296447),
    (True, 62.958812425584426, True, 7.0702568615783745, 0.47747890035047924),
    (True, 61.916428230499065, True, 6.326019294363561, 0.4272179632798119),
    (True, 69.83881489590198, True, 3.1408103460351433, 0.48028412067067994),
    (True, 65.17766572603648, True, 2.8101987294022397, 0.42972789750300144),
    (True, 59.07547164743727, True, 7.362958560720923, 0.48031887275637164),
    (True, 58.94360088640025, True, 6.587910288215713, 0.4297589914744143),
    (True, 54.90679012400591, True, 2.2918346736293236, 0.4774137859920134),
    (True, 48.93521452832337, True, 2.0505889175904595, 0.42715970331646286),
    (True, 64.29764542558925, True, 6.428664990911723, 0.4774236285558107),
    (True, 63.119226307575104, True, 5.751963413735023, 0.4271685098209143),
    (True, 68.15155431987264, True, 2.992954935073918, 0.4801658028383377),
    (True, 63.199719042444485, True, 2.677907047550373, 0.42962203417931205),
    (True, 61.56209418668476, True, 6.728452821782641, 0.4801965297909909),
    (True, 61.24153726410407, True, 6.02019462731511, 0.42964952671590034),
]


def test_the_recorded_design_s_law_scores_as_before_to_a_relative_1e_9() -> None:
    _same_as_before(helpers._recorded_controller(), RECORDED)
    assert RECORDED[0][1] == pytest.approx(50.64, abs=0.01), "the number the first look printed"


def test_a_mode_held_at_one_and_set_aside_scores_as_before_to_a_relative_1e_9() -> None:
    leak_free = helpers._as_law(
        helpers._si(helpers._incremental(None), POINTS[0]["wheel_radius"]),
        POINTS[0]["wheel_radius"],
    )
    _same_as_before(leak_free, LEAK_FREE)
    inert = helpers._with_inert_state(helpers._stable_law(RADIUS), 1.0)
    _same_as_before(inert, INERT_ONE)
    for controller in (leak_free, inert, helpers._recorded_controller()):
        circle = _circle(controller)
        assert (circle.at_one, circle.at_minus_one) == (0, 0)


@pytest.mark.parametrize("pole", [0.999999999, 0.99999999, -0.999999999])
def test_an_eigenvalue_genuinely_inside_by_1e_9_is_still_judged_by_the_float_rule(
    pole: float,
) -> None:
    """Not exactly 1: ``1 - 1e-9`` is inside the unit circle by far more than 1e-12."""
    controller = helpers._with_inert_state(helpers._stable_law(RADIUS), pole)
    assert (_circle(controller).at_one, _circle(controller).at_minus_one) == (0, 0)
    assert all(_stable_at(controller, values) for values in POINTS)


@pytest.mark.parametrize("pole", [0.9999999999999, 1.0000000000001, -0.9999999999999])
def test_an_eigenvalue_within_1e_12_of_the_circle_but_not_on_it_is_judged_in_floating_point(
    pole: float,
) -> None:
    """Within 1e-12 of 1: no exact decision is made, the float rule calls it unstable."""
    controller = helpers._with_inert_state(helpers._stable_law(RADIUS), pole)
    assert (_circle(controller).at_one, _circle(controller).at_minus_one) == (0, 0)
    assert not any(_stable_at(controller, values) for values in POINTS)
