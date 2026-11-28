"""The values check counts, for each tier, what a version's tasks leave a session without.

``physgate tiers values-check`` reads a version's tiers and prints counts only: tasks whose brief
writes a name of the scorer's with no value, from the brief alone and from what a session is
given now; tasks whose brief calls a value given with none; the values the scorer takes by
default, and the briefs that name one. Its counts are checked here on a version made of fixture
tasks of each kind a visible control task is of (a plant in free symbols, with a numerator the
brief writes or does not; a plant in numbers with a gain symbol no input gives, one of them with
an actuator limit the brief calls given and states only in the inputs; a plant in numbers alone;
symbols with their values beside them), three of each, so the version's totals are three times
each kind's whatever tier the split sends a task to. It names no task and writes nothing.

A task whose issued text holds a number of its passing reference is counted again by where that
number lies: a value under one of the scorer's names (a plant coefficient equal to a controller's),
only a digit of the text's own names, units or powers (``plant_den_2``, ``s**2``, ``s^2``), or the
value of an input the scorer does not read; and by how many of the reference's numbers it holds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PER_ROLE_TESTS = Path(__file__).resolve().parent / "per_role"
if str(PER_ROLE_TESTS) not in sys.path:
    sys.path.insert(0, str(PER_ROLE_TESTS))

from task_fixtures import controller, own_task, write_task_dir  # noqa: E402

from physgate.cli import main  # noqa: E402
from physgate.evaluation.tiers.issued_check import value_counts  # noqa: E402
from physgate.evaluation.tiers.store import write_version  # noqa: E402
from physgate.evaluation.tiers.task import canonical_json  # noqa: E402


def _m(name: str, value: float, unit: str) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": unit}


def _second(num: float, d1: float, d2: float, *, gain: bool = True) -> list[dict[str, Any]]:
    given = [_m("plant_num_0", num, "1"), _m("plant_den_0", 1.0, "s**2")]
    given += [_m("plant_den_1", d1, "s"), _m("plant_den_2", d2, "1")]
    return [*given, _m("plant_gain", 1.0, "1")] if gain else given


PEAK = {
    "name": "effort",
    "metric": "actuator_peak",
    "op": "<=",
    "bound": {"value": 2.5, "unit": "V"},
    "composes": ["respect_actuator"],
}
#: Each kind: its brief (``{n}`` marks the copy), its inputs, and whether it bounds the peak.
KINDS: list[tuple[str, list[dict[str, Any]], bool]] = [
    # Free symbols; the brief writes no numerator symbol.
    (
        "Case {n}. Hold the arm: G(s) = 1 / (s^2 + plant_den_1 s + plant_den_2).",
        _second(1, 2, 3),
        False,
    ),
    # Free symbols, every one an input's name.
    (
        "Case {n}. Hold the tank: G(s) = plant_num_0 / (s^2 + plant_den_1 s + plant_den_2).",
        _second(2, 3, 4),
        False,
    ),
    # Free symbols, a pole at the origin.
    (
        "Case {n}. Point the dish: G(s) = plant_num_0 / (s^2 + plant_den_1 s).",
        _second(5, 2, 0),
        False,
    ),
    # Numbers, a gain symbol no input gives, and an actuator limit stated only in the inputs.
    (
        "Case {n}. Drive the motor: G(s) = plant_gain * 2 / (s^2 + 3 s + 1), with plant_num_0 = 2 "
        "and plant_den_1 = 3. Its command must stay within the given limit.",
        [*_second(2, 3, 1, gain=False), _m("actuator_limit", 2.5, "V")],
        True,
    ),
    # Numbers and a gain symbol no input gives.
    (
        "Case {n}. Turn the valve: G(s) = plant_gain * 4 / (s^2 + 2 s + 5).",
        _second(4, 2, 5, gain=False),
        False,
    ),
    # Free symbols, the numerator a literal.
    (
        "Case {n}. Level the deck: G(s) = 5 / (s^2 + plant_den_1 s + plant_den_2).",
        _second(5, 1, 2),
        False,
    ),
    # Numbers alone.
    ("Case {n}. Hold the speed: G(s) = 3 / (s^2 + 4 s + 3).", _second(3, 4, 3), False),
    # Symbols with their values beside them.
    (
        "Case {n}. Balance the beam: G(s) = plant_num_0 / (s^2 + plant_den_1 s + plant_den_2), "
        "where plant_num_0 = 1, plant_den_1 = 0.5 and plant_den_2 = -2 (a linearisation).",
        _second(1, 0.5, -2),
        False,
    ),
]
#: What one copy of the kinds counts, summed over the tiers.
ONE_COPY: dict[str, Any] = {
    "tasks": 8,
    "not_issuable": 0,
    "names_no_input": 1,
    "symbol_without_value": {"brief": 6, "issued": 0},
    "given_without_value": {"brief": 1, "issued": 0},
    "relies_on_default": {"plant_gain": 2, "plant_delay": 8, "reference_step": 1},
    "brief_names_a_defaulted_value": {"plant_gain": 2, "plant_delay": 0, "reference_step": 0},
    "issued_leaks": 0,
    "issued_leak_unchecked": 0,
    "issued_leaks_by_kind": {
        "scorer_named_values_only": 0,
        "names_units_or_powers_only": 0,
        "scorer_named_values_and_names_units_or_powers": 0,
        "unread_input_or_brief": 0,
    },
    "issued_leaks_all_reference_numbers": 0,
    "issued_leaks_matched_of_total": [],
}
#: A passing reference as a search finds one: a controller whose numbers no plant repeats.
GOOD = controller(
    gain={"value": 37.25, "unit": "1"},
    num=[{"value": 1.0, "unit": "s"}, {"value": 0.8125, "unit": "1"}],
    den=[{"value": 1.0, "unit": "s"}, {"value": 0.0, "unit": "1"}],
)


def _store(
    root: Path,
    kinds: list[tuple[str, list[dict[str, Any]], bool]] = KINDS,
    good: dict[str, Any] = GOOD,
) -> tuple[Path, str]:
    store = root.resolve() / "store"
    pool = store / "control" / "withheld" / "pool"
    n = 0
    for copy in range(24 // len(kinds)):
        for brief, inputs, peak in kinds:
            # ``{a}`` marks the copy by a letter, for a brief that must hold no digit of its own.
            text = brief.format(n=n, a=chr(ord("a") + n))
            fields = own_task(id=f"control.zqkind{n:02d}", brief=text, inputs=inputs)
            if peak:
                fields["specs"] = [*fields["specs"], PEAK]
            write_task_dir(
                pool / str(fields["id"]),
                fields,
                {"good": (good, None), "bad_slow": (controller(), "settling")},
            )
            n += 1
        del copy
    manifest, _ = write_version(
        store / "control",
        sorted(p for p in pool.iterdir() if p.is_dir()),
        role="control",
        seed=5,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": []}),
        retire=pool,
        generated="2026-11-27",
    )
    return store, manifest.version


def _summed(tiers: dict[str, Any]) -> dict[str, Any]:
    def add(a: Any, b: Any) -> Any:  # noqa: ANN401
        return {k: add(a[k], b[k]) for k in a} if isinstance(a, dict) else a + b

    total: dict[str, Any] = {}
    for counts in tiers.values():
        total = counts if not total else add(total, counts)
    return total


def _times(counts: Any, k: int) -> Any:  # noqa: ANN401
    return (
        {key: _times(v, k) for key, v in counts.items()} if isinstance(counts, dict) else counts * k
    )


def test_each_kind_of_task_is_counted_as_its_brief_and_its_issued_text_leave_it(
    tmp_path: Path,
) -> None:
    store, version = _store(tmp_path)
    counted = value_counts(store, "control", version)
    assert set(counted["tiers"]) == {"visible", "validation", "held_out"}
    assert all(c["tasks"] == 8 for c in counted["tiers"].values())
    assert _summed(counted["tiers"]) == _times(ONE_COPY, 3)


@pytest.mark.parametrize(
    ("kind", "brief", "issued"),
    [(0, 1, 0), (3, 1, 0), (6, 0, 0), (7, 0, 0)],
)
def test_a_name_the_brief_gives_a_value_beside_or_the_issued_text_gives_is_not_counted(
    tmp_path: Path, kind: int, brief: int, issued: int
) -> None:
    store, version = _store(tmp_path, [KINDS[kind]])
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert total["symbol_without_value"] == {"brief": 24 * brief, "issued": 24 * issued}


def test_a_name_neither_text_gives_a_value_is_counted_in_both(tmp_path: Path) -> None:
    # The brief names a reference step, which the scorer reads only for a peak bound: the issued
    # text gives it no value either, since no session's answer is judged against it.
    brief = (
        "Case {n}. Hold the arm: G(s) = 1 / (s^2 + plant_den_1 s + plant_den_2), "
        "from reference_step."
    )
    store, version = _store(tmp_path, [(brief, _second(1, 2, 3), False)])
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert total["symbol_without_value"] == {"brief": 24, "issued": 24}


def test_a_task_the_scorer_cannot_read_is_counted_as_not_issuable(tmp_path: Path) -> None:
    brief, inputs, _ = KINDS[3]
    store, version = _store(tmp_path, [(brief, inputs[:-1], True)])
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert total["not_issuable"] == 24
    assert total["symbol_without_value"] == {"brief": 24, "issued": 0}


@pytest.mark.parametrize(("coefficient", "leaks"), [(0.8125, 24), (0.8126, 0)])
def test_a_task_whose_values_repeat_its_passing_reference_s_numbers_is_counted_as_leaking(
    tmp_path: Path, coefficient: float, leaks: int
) -> None:
    """The brief states no number of the reference; the value a session is now given does."""
    brief = "Case {n}. Hold the arm: G(s) = 1 / (s^2 + plant_den_1 s + plant_den_2)."
    store, version = _store(tmp_path, [(brief, _second(1, coefficient, 3), False)])
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert (total["issued_leaks"], total["issued_leak_unchecked"]) == (leaks, 0)


def _reference(gain: float, zero: float) -> dict[str, Any]:
    """A passing reference ``gain * (s + zero) / s``: two numbers other than 0, 1 and -1."""
    return controller(
        gain={"value": gain, "unit": "1"},
        num=[{"value": 1.0, "unit": "s"}, {"value": zero, "unit": "1"}],
        den=[{"value": 1.0, "unit": "s"}, {"value": 0.0, "unit": "1"}],
    )


#: A brief that holds no digit: every number a session reads is in the issued block.
IN_WORDS = "Case {a}. Hold the arm: its plant is the one the values below make."
SYMBOLS = "Case {n}. Hold the arm: G(s) = 1 / (s^2 + plant_den_1 s + plant_den_2)."
KIND_NAMES = (
    "scorer_named_values_only",
    "names_units_or_powers_only",
    "scorer_named_values_and_names_units_or_powers",
    "unread_input_or_brief",
)


@pytest.mark.parametrize(
    ("brief", "inputs", "good", "kind", "pair"),
    [
        # A zero the reference places on a plant coefficient: the plant's own number.
        pytest.param(SYMBOLS, _second(1, 0.8125, 3), GOOD, 0, (1, 2), id="plant_coincidence"),
        # A gain of 2 on a second-order plant: only the digit of plant_den_2, s**2 and s^2.
        pytest.param(
            IN_WORDS, _second(1.5, 0.75, 3.5), _reference(2.0, 0.8126), 1, (1, 2), id="power"
        ),
        # Both numbers held, neither a give-away: a plant coefficient and a power's digit.
        pytest.param(
            IN_WORDS, _second(1.5, 0.75, 3.5), _reference(2.0, 0.75), 2, (2, 2), id="both"
        ),
        # The reference itself, written as inputs the scorer does not read: a give-away.
        pytest.param(
            SYMBOLS,
            [*_second(1, 2, 3), _m("suggested_gain", 37.25, "1"), _m("suggested_zero", 0.8125, "1")],
            GOOD,
            3,
            (2, 2),
            id="full_give_away",
        ),
    ],
)
def test_a_leaking_task_is_counted_by_where_its_reference_s_numbers_lie_and_how_many(
    tmp_path: Path,
    brief: str,
    inputs: list[dict[str, Any]],
    good: dict[str, Any],
    kind: int,
    pair: tuple[int, int],
) -> None:
    store, version = _store(tmp_path, [(brief, inputs, False)], good)
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert total["issued_leaks"] == 24
    assert total["issued_leaks_by_kind"] == {
        name: 24 if index == kind else 0 for index, name in enumerate(KIND_NAMES)
    }
    assert total["issued_leaks_all_reference_numbers"] == (24 if pair[0] == pair[1] else 0)
    assert sorted(total["issued_leaks_matched_of_total"]) == [list(pair)] * 24


def test_a_default_the_issued_text_says_is_never_counted_as_a_leak(tmp_path: Path) -> None:
    """Every default is 0 or 1, which the leak rule never reads as a number of the answer."""
    brief, inputs, peak = KINDS[3]
    good = controller(
        gain={"value": 1.0, "unit": "1"},
        num=[{"value": 1.0, "unit": "s"}, {"value": 1.0, "unit": "1"}],
        den=[{"value": 1.0, "unit": "s"}, {"value": 0.0, "unit": "1"}],
    )
    store, version = _store(tmp_path, [(brief, inputs, peak)], good)
    total = _summed(value_counts(store, "control", version)["tiers"])
    assert total["relies_on_default"] == {"plant_gain": 24, "plant_delay": 24, "reference_step": 24}
    assert total["issued_leaks"] == 0
    assert total["issued_leaks_by_kind"] == dict.fromkeys(KIND_NAMES, 0)
    assert total["issued_leaks_matched_of_total"] == []


def test_each_tier_s_leaks_are_its_kinds_and_its_pairs(tmp_path: Path) -> None:
    """Over a version of every kind, each tier counts each leaking task once, in one kind."""
    # The reference is 2 * (s + 0.8126) / s throughout; each plant is second order.
    kinds = [
        (IN_WORDS, _second(1.5, 0.8126, 3.5), False),
        (IN_WORDS, _second(1.5, 0.75, 3.5), False),
        (IN_WORDS, _second(1.5, 0.5, 3.5), False),
        (IN_WORDS, [*_second(1.5, 0.5, 3.5), _m("suggested_zero", 0.8126, "1")], False),
    ]
    store, version = _store(tmp_path, kinds, _reference(2.0, 0.8126))
    tiers = value_counts(store, "control", version)["tiers"]
    for counts in tiers.values():
        pairs = counts["issued_leaks_matched_of_total"]
        assert sum(counts["issued_leaks_by_kind"].values()) == counts["issued_leaks"] == len(pairs)
        assert pairs == sorted(pairs)
        assert counts["issued_leaks_all_reference_numbers"] == sum(m == t for m, t in pairs)
    total = _summed(tiers)
    assert total["issued_leaks"] == 24
    assert total["issued_leaks_by_kind"] == {
        "scorer_named_values_only": 0,
        "names_units_or_powers_only": 12,
        "scorer_named_values_and_names_units_or_powers": 6,
        "unread_input_or_brief": 6,
    }
    assert sorted(total["issued_leaks_matched_of_total"]) == [[1, 2]] * 12 + [[2, 2]] * 12


def _files(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_command_prints_counts_alone_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, version = _store(tmp_path)
    before = _files(store)
    args = ["tiers", "values-check", "--store", str(store), "--role", "control"]
    assert main([*args, "--version", version]) == 0
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    said = json.loads(printed[0])
    assert _summed(said["tiers"]) == _times(ONE_COPY, 3)
    assert "zqkind" not in printed[0] and "Case" not in printed[0] and "G(s)" not in printed[0]
    assert _files(store) == before


def test_a_version_the_role_does_not_hold_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _ = _store(tmp_path)
    args = ["tiers", "values-check", "--store", str(store), "--role", "control"]
    assert main([*args, "--version", "0" * 64]) == 1
    said = json.loads(capsys.readouterr().out)
    assert said["refused_because"] == "version_unknown"
