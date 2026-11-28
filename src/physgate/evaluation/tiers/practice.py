"""A practice store: one version of control tasks written for practice, never for a measurement.

A shakedown runs both arms end to end on a version in a store of its own, so that every step a
counted trial takes (the refusals of a measured run, the placement beneath a run root, the
canary scans, the held-out exclusions, the baseline round, the report) runs once without
touching a real tier. :func:`build_practice_store` writes that store.

**Its tasks are practice tasks**, written here, and the version says so in its manifest
(:attr:`.manifest.TierSet.practice`), the field every counting reader holds: six control
tasks, one plant family (a second-order plant with one unstable pole, ``1 / (s^2 + a s - b)``,
each task its own ``a`` and ``b``), adapted in kind from a published benchmark's second-order
unstable category, with three specifications composing three requirements. Each is held to the
split's own entry checks before the split: it loads, it composes at least two requirements, its
scorer passes its good reference and fails its bad one on the spec it names, its brief gives no
number of the good reference away, and its directory is named by its id
(:func:`.per_role.validate.sound`). Their content is the builder's own, not an author session's,
and wants a person's look before a shakedown relies on it.

**Two kinds** (:data:`KINDS`). The tasks above are the ``bare`` kind, the default: every value
of the plant and its criteria stands in the brief. The ``shaped`` kind (:data:`SHAPED`) holds six
control tasks shaped like a real control tier's instead: each names a physical system invented
for practice, asks for a continuous controller ``C(s)`` judged on linear criteria of a unit step,
and holds its plant's values in its inputs. Five of its briefs write symbols of the scorer's
whose values only the inputs hold (so every tier holds one, whatever the seed), one plant is
open-loop unstable, one task bounds the controller's peak output by an actuator limit its brief
calls given and states only in the inputs, and one is a plain stable plant in numbers. No task
states a rate limit or asks for firmware, a board or parts. Its ids begin ``control.practice_
shaped_`` and its provenance record names its kind; no brief of either kind says practice.

**The version** is written by the store's own writer (:func:`.store.write_version`) with two
tasks to a tier, split by the seed given: so its held-out tier holds two practice tasks, its
validation tier two and its visible tier two, each protected tier with its canary list, as the
version format requires.

**Its check record** is written in the imported form (``source: imported``, the form the real
version's record has), through the store's own writer (:func:`.checks.write_check`), flagging
no task. No blind check ran on practice tasks: the record's kept session is named
``practice-no-check-session`` and keeps no stream, its answer is the all-yes answer on the
held-out ids' digests, and its spend is unknown. It is a stand-in that lets the round's
check-record path run, and says so in its own fields.

The store is built only into a directory that does not exist, so nothing real is ever beside it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.manifest import TierSet
from physgate.evaluation.tiers.task import canonical_json

#: The plants of the six practice tasks: ``(a, b)`` of ``1 / (s^2 + a s - b)``.
PLANTS = ((0.5, 2.0), (1.0, 3.0), (0.25, 1.5), (0.75, 4.0), (0.4, 2.5), (1.25, 5.0))
#: The good reference of every practice task: a lead controller ``K (s + z) / (s + p)``.
GOOD = (96.0, 1.75, 12.5)
#: The bad reference: the same controller at a gain too low to hold the unstable pole.
BAD = (0.5, 1.75, 12.5)
#: Each tier's count in the practice version.
PER_TIER = 2
#: The seed the practice version is split by, unless another is given.
SEED = 20261124
#: The model the stand-in check record names, as the real check's model is named.
CHECK_MODEL = "claude-sonnet-5"
#: The kept session the stand-in check record names: there was none.
NO_SESSION = "practice-no-check-session"
#: How every practice brief names where its answer goes: the real briefs' words, verbatim
#: (:mod:`.per_role.controleval`), so a shakedown's sessions are told what a measured one is.
ANSWER_SAID = "write the controller to the file `answer.json` in the directory you work in"
#: The kinds of practice version the command writes, the first its default.
KINDS = ("bare", "shaped")
#: The id every shaped practice task's own number follows.
SHAPED_ID = "control.practice_shaped_"


class PracticeError(PerRoleError):
    """The practice store cannot be built, for a reason it names."""


def practice_task(number: int) -> dict[str, Any]:
    """Practice task ``number`` (from 0), as its ``task.json`` holds it."""
    a, b = PLANTS[number]
    # No word of the brief says it is practice: a session told its task is not measured may
    # work less, and a shakedown's wall clocks are what the time rule is set from. The id and the
    # manifest say it, where no session reads.
    brief = (
        f"The plant is G(s) = 1 / (s^2 + {a} s - {b}), with one unstable pole. Design a linear "
        "controller for unity negative feedback around it that makes the closed loop stable, "
        "settles a unit step in under 5 s and overshoots it by under 60 percent. Answer: "
        f"{ANSWER_SAID}, as a transfer function."
    )
    return {
        "id": f"control.practice_{number:02d}",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": brief,
        "inputs": [
            {"name": "plant_num_0", "value": 1.0, "unit": "1"},
            {"name": "plant_den_0", "value": 1.0, "unit": "s**2"},
            {"name": "plant_den_1", "value": a, "unit": "s"},
            {"name": "plant_den_2", "value": -b, "unit": "1"},
        ],
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["hold_the_unstable_pole", "reject_a_disturbance"],
            },
            {
                "name": "settles",
                "metric": "settling_time",
                "op": "<",
                "bound": {"value": 5.0, "unit": "s"},
                "composes": ["hold_the_unstable_pole", "settle_quickly"],
            },
            {
                "name": "overshoot",
                "metric": "overshoot",
                "op": "<",
                "bound": {"value": 60.0, "unit": "percent"},
                "composes": ["settle_quickly"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0", "params": []},
    }


def _controller(gain: float, zero: float, pole: float) -> dict[str, Any]:
    return {
        "form": "lti_tf",
        "gain": {"value": gain, "unit": "1"},
        "num": [{"value": 1.0, "unit": "s"}, {"value": zero, "unit": "1"}],
        "den": [{"value": 1.0, "unit": "s"}, {"value": pole, "unit": "1"}],
    }


def write_practice_task(pool: Path, number: int, *, kind: str = "bare") -> Path:
    """Write practice task ``number`` of ``kind``, with its references, into ``pool``; its place."""
    if kind == "shaped":
        return _write_shaped(pool, number)
    task = practice_task(number)
    directory = pool / str(task["id"])
    good = directory / "references" / "good"
    bad = directory / "references" / "bad_unstable"
    good.mkdir(parents=True)
    bad.mkdir(parents=True)
    (directory / "task.json").write_bytes(canonical_json(task))
    (good / "answer.json").write_bytes(canonical_json(_controller(*GOOD)))
    (bad / "answer.json").write_bytes(canonical_json(_controller(*BAD)))
    (bad / "expect.json").write_bytes(canonical_json({"fails": "stable"}))
    return directory


# The shaped kind: practice tasks shaped like a real control tier's, not like the bare kind's.
#
# A real control task names a physical system, asks for a continuous controller C(s) for unity
# feedback judged on linear criteria of a unit step, and holds its plant's values in its inputs
# list: some briefs write the plant in the scorer's own symbols and give none of their values,
# one plant may be open-loop unstable, a few bound the controller's peak output by an actuator
# limit the brief calls given and states only in the inputs, and none states a rate limit or
# asks for firmware, a board or parts. Each system here is invented for practice. Each task's
# good reference passes the scorer and its bad one fails the spec it names, and no number of the
# good reference stands anywhere in what a session is given (:func:`.issued.issued_text`): not
# in the brief, not among the plant's values, and not as a digit of a name or a power.


@dataclass(frozen=True)
class _Shaped:
    """One shaped practice task: its brief, plant, criteria and its two references."""

    brief: str
    num: tuple[float, ...]
    den: tuple[float, ...]
    #: Further inputs, each ``(name, value, unit)``: a gain the task gives, an actuator limit.
    extra: tuple[tuple[str, float, str], ...]
    #: Each ``(name, metric, op, bound value, bound unit, composes)``.
    specs: tuple[tuple[str, str, str, float, str, tuple[str, ...]], ...]
    #: Each controller ``(gain, numerator, denominator)``, coefficients highest power first.
    good: tuple[float, tuple[float, ...], tuple[float, ...]]
    bad: tuple[float, tuple[float, ...], tuple[float, ...]]
    #: The spec the bad reference is built to fail, and the name of its directory's suffix.
    bad_fails: str
    bad_name: str


_ASK = (
    "Design a continuous-time linear controller C(s) for unity negative feedback around this "
    "plant so that, for a unit step in the reference,"
)
_ANSWER = f" Answer: {ANSWER_SAID}, as a transfer function."

SHAPED = (
    # A plant in the scorer's symbols alone, stable; its values only in the inputs.
    _Shaped(
        brief=(
            "A handheld camera gimbal holds the camera level about its pitch axis: a brushless "
            "motor's command turns the camera, and its pitch angle is fed back. The plant from "
            "motor command to pitch angle is G(s) = plant_num_0 / (plant_den_0 s^2 + "
            f"plant_den_1 s + plant_den_2). {_ASK} the pitch angle settles to within 2 percent "
            "in under 0.8 s, overshoots by under 12 percent, and leaves a steady-state error of "
            "at most 0.02." + _ANSWER
        ),
        num=(0.9,),
        den=(0.025, 0.15, 0.6),
        extra=(),
        specs=(
            ("settles", "settling_time", "<", 0.8, "s", ("hold_level", "follow_a_tilt")),
            ("overshoot", "overshoot", "<", 12.0, "percent", ("hold_level",)),
            ("tracks", "steady_state_error", "<=", 0.02, "1", ("follow_a_tilt",)),
        ),
        good=(14.9, (1.0, 7.4, 30.6), (1.0, 41.0, 0.0)),
        bad=(59.0, (1.0, 7.4, 30.6), (1.0, 41.0, 0.0)),
        bad_fails="overshoot",
        bad_name="bad_overshoot",
    ),
    # An open-loop unstable plant, a linearisation, in the scorer's symbols alone.
    _Shaped(
        brief=(
            "A magnetic levitation rig holds a steel ball at a set height below an "
            "electromagnet, and the ball's height is measured and fed back. Linearised about its "
            "operating height, the plant from coil command to ball height is G(s) = plant_num_0 "
            f"/ (plant_den_0 s^2 + plant_den_1 s + plant_den_2). {_ASK} the closed loop is "
            "stable, the height settles to within 2 percent in under 0.6 s, and the steady-state "
            "error is at most 0.02." + _ANSWER
        ),
        num=(30.0,),
        den=(1.0, 0.0, -400.0),
        extra=(),
        specs=(
            ("stable", "max_real_pole", "<", 0.0, "1/s", ("hold_the_ball",)),
            ("settles", "settling_time", "<", 0.6, "s", ("hold_the_ball", "move_the_ball")),
            ("tracks", "steady_state_error", "<=", 0.02, "1", ("move_the_ball",)),
        ),
        good=(155.0, (1.0, 33.0, 246.0), (1.0, 77.5, 0.0)),
        bad=(7.5, (1.0, 33.0, 246.0), (1.0, 77.5, 0.0)),
        bad_fails="stable",
        bad_name="bad_unstable",
    ),
    # A bound on the controller's peak output by an actuator limit the brief calls given and
    # states only in the inputs; the plant in numbers but for a gain symbol no input gives.
    _Shaped(
        brief=(
            "A ventilation fan's airflow is set through its motor driver, and the airflow is "
            "measured and fed back. The plant from driver command to airflow is G(s) = "
            "plant_gain * 1.6 / (s^2 + 2.2 s + 0.9). The driver's command must stay within the "
            f"actuator limit actuator_limit, which is given. {_ASK} the airflow settles to "
            "within 2 percent in under 4 s, the steady-state error is at most 0.02, and the "
            "largest magnitude of the controller's output over that response stays within "
            "actuator_limit." + _ANSWER
        ),
        num=(1.6,),
        den=(1.0, 2.2, 0.9),
        extra=(("actuator_limit", 6.0, "V"),),
        specs=(
            ("settles", "settling_time", "<", 4.0, "s", ("reach_the_airflow",)),
            (
                "tracks",
                "steady_state_error",
                "<=",
                0.02,
                "1",
                ("reach_the_airflow", "spare_the_driver"),
            ),
            ("effort", "actuator_peak", "<=", 6.0, "V", ("spare_the_driver",)),
        ),
        good=(3.7, (1.0, 2.3, 0.97), (1.0, 3.9, 0.0)),
        bad=(13.0, (1.0, 2.3, 0.97), (1.0, 4.3, 0.0)),
        bad_fails="effort",
        bad_name="bad_effort",
    ),
    # A plain stable plant, written in numbers.
    _Shaped(
        brief=(
            "A solar panel tracker turns its panel about one axis to follow the sun, and the "
            "panel's angle is measured and fed back. The plant from drive command to panel "
            f"angle is G(s) = 0.75 / (s^2 + 1.3 s + 0.42). {_ASK} the angle settles to within "
            "2 percent in under 9 s and overshoots by under 10 percent, with a phase margin of "
            "at least 55 degrees." + _ANSWER
        ),
        num=(0.75,),
        den=(1.0, 1.3, 0.42),
        extra=(),
        specs=(
            ("settles", "settling_time", "<", 9.0, "s", ("follow_the_sun",)),
            ("overshoot", "overshoot", "<", 10.0, "percent", ("follow_the_sun", "ride_out_gusts")),
            ("margin", "phase_margin", ">=", 55.0, "deg", ("ride_out_gusts",)),
        ),
        good=(9.1, (1.0, 1.16, 0.56), (1.0, 5.3, 0.0)),
        bad=(3.4, (1.0, 0.63), (1.0, 0.0)),
        bad_fails="margin",
        bad_name="bad_margin",
    ),
    # A pole at the origin, in the scorer's symbols alone.
    _Shaped(
        brief=(
            "A microscope's motorised sample stage moves the sample along one axis, and the "
            "stage's position is measured and fed back. The plant from drive command to stage "
            f"position is G(s) = plant_num_0 / (s (plant_den_0 s + plant_den_1)). {_ASK} the "
            "position settles to within 2 percent in under 0.9 s and overshoots by under 15 "
            "percent, with a phase margin of at least 50 degrees." + _ANSWER
        ),
        num=(12.5,),
        den=(1.0, 6.4, 0.0),
        extra=(),
        specs=(
            ("settles", "settling_time", "<", 0.9, "s", ("place_the_sample",)),
            ("overshoot", "overshoot", "<", 15.0, "percent", ("place_the_sample",)),
            ("margin", "phase_margin", ">=", 50.0, "deg", ("place_the_sample", "stay_robust")),
        ),
        good=(5.6, (1.0, 5.7), (1.0, 11.8)),
        bad=(23.0, (1.0,), (1.0,)),
        bad_fails="margin",
        bad_name="bad_margin",
    ),
    # A third-order plant with its own gain, in the scorer's symbols alone.
    _Shaped(
        brief=(
            "A greenhouse roof vent is opened by a geared actuator, and the vent's opening is "
            "measured and fed back. The plant from actuator command to vent opening is G(s) = "
            "plant_gain * plant_num_0 / (plant_den_0 s^3 + plant_den_1 s^2 + plant_den_2 s + "
            f"plant_den_3). {_ASK} the opening settles to within 2 percent in under 12 s and the "
            "steady-state error is at most 0.02." + _ANSWER
        ),
        num=(1.2,),
        den=(1.0, 4.5, 5.8, 1.6),
        extra=(("plant_gain", 0.35, "1"),),
        specs=(
            ("settles", "settling_time", "<", 12.0, "s", ("open_in_time",)),
            ("tracks", "steady_state_error", "<=", 0.02, "1", ("open_in_time", "open_as_asked")),
        ),
        good=(17.6, (1.0, 1.57, 0.58), (1.0, 3.7, 0.0)),
        bad=(3.9, (1.0,), (1.0,)),
        bad_fails="tracks",
        bad_name="bad_steady_state",
    ),
)


def _power(degree: int, index: int) -> str:
    power = degree - index
    return "1" if power == 0 else ("s" if power == 1 else f"s**{power}")


def _coefficients(prefix: str, values: tuple[float, ...]) -> list[dict[str, Any]]:
    degree = len(values) - 1
    return [
        {"name": f"{prefix}_{i}", "value": v, "unit": _power(degree, i)}
        for i, v in enumerate(values)
    ]


def _lti(gain: float, num: tuple[float, ...], den: tuple[float, ...]) -> dict[str, Any]:
    def poly(values: tuple[float, ...]) -> list[dict[str, Any]]:
        return [{"value": v, "unit": _power(len(values) - 1, i)} for i, v in enumerate(values)]

    return {
        "form": "lti_tf",
        "gain": {"value": gain, "unit": "1"},
        "num": poly(num),
        "den": poly(den),
    }


def shaped_task(number: int) -> dict[str, Any]:
    """Shaped practice task ``number`` (from 0), as its ``task.json`` holds it."""
    shaped = SHAPED[number]
    inputs = _coefficients("plant_num", shaped.num) + _coefficients("plant_den", shaped.den)
    inputs += [{"name": n, "value": v, "unit": u} for n, v, u in shaped.extra]
    return {
        "id": f"{SHAPED_ID}{number:02d}",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": shaped.brief,
        "inputs": inputs,
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": name,
                "metric": metric,
                "op": op,
                "bound": {"value": value, "unit": unit},
                "composes": list(composes),
            }
            for name, metric, op, value, unit, composes in shaped.specs
        ],
        "scorer": {"id": "control", "version": "1.1.0", "params": []},
    }


def _write_shaped(pool: Path, number: int) -> Path:
    shaped = SHAPED[number]
    task = shaped_task(number)
    directory = pool / str(task["id"])
    good = directory / "references" / "good"
    bad = directory / "references" / shaped.bad_name
    good.mkdir(parents=True)
    bad.mkdir(parents=True)
    (directory / "task.json").write_bytes(canonical_json(task))
    (good / "answer.json").write_bytes(canonical_json(_lti(*shaped.good)))
    (bad / "answer.json").write_bytes(canonical_json(_lti(*shaped.bad)))
    (bad / "expect.json").write_bytes(canonical_json({"fails": shaped.bad_fails}))
    return directory


def build_practice_store(
    store: Path,
    *,
    implementer_model: str,
    seed: int = SEED,
    runtime: str = "practice",
    kind: str = KINDS[0],
) -> TierSet:
    """Build a store at the new directory ``store`` with one practice version; its manifest.

    ``kind`` is which practice tasks it holds (:data:`KINDS`): ``bare``, the plant and its
    criteria all in the brief; or ``shaped``, tasks shaped like a real control tier's
    (:data:`SHAPED`), which the provenance record names. Runs in the evaluation environment:
    each task's scorer is run on its references.

    Raises:
        PracticeError: ``kind`` is not one of :data:`KINDS` (``kind_unknown``), ``store`` exists
            (``store_exists``), or a practice task is not one the split takes
            (``practice_task_refused``, with its counted reasons).
        PerRoleError: the store's writers refuse, each with its own reason.
    """
    from physgate.evaluation.per_role.validate import refusal_reasons, sound
    from physgate.evaluation.tiers.checks import make_check, write_check
    from physgate.evaluation.tiers.store import pool_dir, write_version

    if kind not in KINDS:
        msg = f"a practice version is of one of the kinds {list(KINDS)}"
        raise PracticeError(msg, refused_because="kind_unknown")
    if store.exists() or store.is_symlink():
        msg = "a practice store is built only into a directory that does not exist"
        raise PracticeError(msg, refused_because="store_exists")
    pool = pool_dir(store, "control")
    pool.mkdir(parents=True)
    written = [write_practice_task(pool, n, kind=kind) for n in range(3 * PER_TIER)]
    taken = sound(pool)
    if sorted(taken) != sorted(d.name for d in written):
        reasons = refusal_reasons(pool)
        msg = f"a practice task is not one the split takes: {reasons}"
        raise PracticeError(msg, refused_because="practice_task_refused")
    # The bare kind's record is the one it always wrote; another kind is named in it.
    named = {} if kind == KINDS[0] else {"kind": kind}
    provenance = canonical_json(
        {**named, "practice": True, "written_by": "physgate.tiers.practice"}
    )
    manifest, _ = write_version(
        store / "control",
        written,
        role="control",
        seed=seed,
        model="practice",
        runtime=runtime,
        provenance=provenance,
        retire=pool,
        per_tier=PER_TIER,
        practice=True,
    )
    held = _held_out_digests(store, manifest)
    answer = {
        digest: {"states_every_requirement": True, "unambiguous": True, "answerable_as_asked": True}
        for digest in held
    }
    record = make_check(
        role="control",
        version=manifest.version,
        tier="held_out",
        tier_sha256=manifest.held_out.sha256,
        source="imported",
        checked=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pins={
            "model": CHECK_MODEL,
            "claude_version": runtime,
            "implementer_model": implementer_model,
        },
        kept={"session_id": NO_SESSION, "stream_sha256": None, "bound_by": "answer_keys"},
        session={},
        tasks=len(held),
        all_yes=len(held),
        flagged=[],
        answer_sha256=hashlib.sha256(canonical_json(answer)).hexdigest(),
    )
    write_check(store, "control", record)
    return manifest


def _held_out_digests(store: Path, manifest: TierSet) -> list[str]:
    """The digests of the practice version's held-out ids, as the check would key its answer."""
    from physgate.evaluation.tiers.checks import _held_out_digests as digests

    return sorted(digests(store, "control", manifest.version))


def describe(manifest: TierSet, *, kind: str = KINDS[0]) -> str:
    """The line the command prints: the version and its tiers' counts and digests.

    A kind other than the bare one is named on it; the bare kind's line is the one it always was.
    """
    return json.dumps(
        {
            "version": manifest.version,
            "practice": True,
            **({} if kind == KINDS[0] else {"kind": kind}),
            **{
                tier: {
                    "count": getattr(manifest, tier).count,
                    "sha256": getattr(manifest, tier).sha256,
                }
                for tier in ("visible", "validation", "held_out")
            },
        },
        sort_keys=True,
    )
