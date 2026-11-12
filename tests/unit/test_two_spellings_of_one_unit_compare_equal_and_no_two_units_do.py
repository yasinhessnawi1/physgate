"""Two spellings of one unit compare equal, and two different units never do.

Where the harness asks whether a quantity changed (the interface a sizing pass follows, the
store's refusal of a revision in which nothing differs, the follow-ups sizing's closing pass
owes), a unit is compared in one canonical form: the grammar's own named units, each as written,
sorted, with their integer powers summed and a zero power dropped. So ``1/(rad*s)``, ``1/rad/s``,
``rad**-1*s**-1``, ``s**-1/rad`` and ``1/rad / s`` are one unit, and a revision that changes only
the spelling is no revision: the interface keeps its stored spelling and no follow-up is owed.

The form is the grammar's, never the registry's root units: those reduce ``Hz`` to ``1/s`` and
drop the radian and the count, so ``rad/s`` and ``Hz``, or ``count/s`` and ``1/s``, would compare
equal. A unit whose name differs (``mm`` beside ``m``, ``J`` beside ``N*m``) is another unit to
this comparison; the physical check and the kind check stay pint's. ``m/m`` is ``1``: its powers
sum to nothing.

Each row compares or catches, so a row fails on an assertion before the build.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "orchestrator"))
from test_a_closing_pass_change_owes_a_follow_up_to_each_domain_node_it_reaches import (  # noqa: E402
    BUS,
    DRIVER,
    Journal,
    node,
    owed,
    quantity,
    slice_journal,
)

from physgate.orchestrator.follow import FollowRefusedError, derive  # noqa: E402
from physgate.state.store import (  # noqa: E402
    REJECT_INTERFACE_NOT_FOLLOWED,
    Store,
    followed_payload,
    written_quantity,
)

#: Spellings of one unit each, by group.
EQUAL = [
    [
        "1/(rad*s)", "1/rad/s", "rad**-1*s**-1", "s**-1/rad", "1/(s*rad)", "1/rad / s",
        "rad^-1*s^-1", "1/s/rad",
    ],
    ["m/s/s", "m/s**2", "m*s**-2", "s**-2*m", "m/(s*s)"],
    ["kg*m/s**2", "m*kg/s**2", "kg/s**2*m"],
    ["m/m", "1", "s*s**-1"],
]  # fmt: skip
#: Pairs that are different units, though the registry's root units hold some of them equal.
UNEQUAL = [
    ("rad/s", "Hz"),
    ("rad/s", "1/s"),
    ("N*m", "J"),
    ("count/s", "1/s"),
    ("V/(m*s)", "V*s/m"),
    ("m", "mm"),
    ("rad", "1"),
    ("rad/s", "rad/s**2"),
]


def _same(a: str, b: str) -> bool:
    return written_quantity({"value": 2, "unit": a}) == written_quantity({"value": 2, "unit": b})


@pytest.mark.parametrize(
    ("a", "b"), [(g[0], other) for g in EQUAL for other in g[1:]], ids=lambda u: str(u)
)
def test_every_spelling_of_one_unit_compares_equal(a: str, b: str) -> None:
    assert _same(a, b)
    assert _same(b, a)


@pytest.mark.parametrize(("a", "b"), UNEQUAL, ids=lambda u: str(u))
def test_two_different_units_never_compare_equal(a: str, b: str) -> None:
    assert not _same(a, b)
    assert not _same(b, a)


def test_a_value_written_differently_is_still_another_writing() -> None:
    # The value is compared as written: 2 and 2.0 are two writings, whatever the unit.
    assert written_quantity({"value": 2, "unit": "1/rad/s"}) != written_quantity(
        {"value": 2.0, "unit": "rad**-1*s**-1"}
    )


# --- a revision that changes only the spelling ---------------------------------------------------

IFACE = "balance.controller"
JOINED = "sizing.balance_controller"


def _q(value: float, unit: str, by: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "the plan" if by == "plan" else "sized",
            "written_by": "sizing"}  # fmt: skip


def interface(unit: str, value: float) -> dict[str, Any]:
    return {
        "id": IFACE, "kind": "interface", "domain": "cross", "owner_role": "sizing",
        "quantities": {"angle_gain": _q(value, unit, "plan")},
        "requirements": ["criterion 6"], "constrains": ["control.loop"], "model": None,
        "geometry_hash": "none", "updated": "2026-11-11",
    }  # fmt: skip


def gain(unit: str, value: float) -> dict[str, Any]:
    return {
        "id": JOINED, "kind": "component", "domain": "cross", "owner_role": "sizing",
        "quantities": {"angle_gain": _q(value, unit, "sizing")},
        "requirements": [], "constrains": [IFACE], "model": None,
        "geometry_hash": "none", "updated": "2026-11-11",
    }  # fmt: skip


def derived(held: str, written: str, held_value: float, value: float) -> Any:  # noqa: ANN401
    try:
        return derive(interface(held, held_value), {JOINED: gain(written, value)}, "sizing", 1)
    except FollowRefusedError as exc:
        return f"refused: {exc}"


@pytest.mark.parametrize("written", EQUAL[0][1:])
def test_a_spelling_only_change_derives_no_revision(written: str) -> None:
    assert derived("1/(rad*s)", written, 3.5, 3.5) is None
    assert derived("rad**-1*s**-1", written, 3.5, 3.5) is None


@pytest.mark.parametrize("written", EQUAL[0])
def test_a_new_value_in_another_spelling_keeps_the_stored_spelling(written: str) -> None:
    after = derived("rad**-1*s**-1", written, 2.0, 3.5)
    assert isinstance(after, dict), after
    found = after["quantities"]["angle_gain"]
    assert (found["value"], found["unit"]) == (3.5, "rad**-1*s**-1")


def test_the_store_refuses_a_revision_that_changes_only_the_spelling(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    try:
        for payload in (interface("rad**-1*s**-1", 3.5), gain("s**-1/rad", 3.5)):
            assert store.write_node(payload, "sizing").accepted
        respelt = followed_payload(
            interface("rad**-1*s**-1", 3.5), [gain("s**-1/rad", 3.5)], "sizing", 1
        )
        refused = store.follow_interface(respelt, "sizing", (JOINED,))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


@pytest.mark.parametrize(
    ("before", "after"), [("A", "A"), ("V/(m*s)", "V/m/s"), ("m/s/s", "s**-2*m")]
)
def test_a_closing_pass_that_only_respells_a_unit_owes_no_follow_up(
    before: str, after: str
) -> None:
    journal = Journal()
    opening = node(BUS, "sizing", constrains=[DRIVER])
    opening["quantities"] = {"peak_current": quantity(2.0, before, "sizing")}
    journal.merge("z0", opening)
    journal.merge("s1", node(DRIVER, "electrical", constrains=[BUS]))
    closing = node(BUS, "sizing", constrains=[DRIVER])
    closing["quantities"] = {"peak_current": quantity(2.0, after, "sizing")}
    journal.merge("zc", closing)
    assert owed(journal) == {}


def test_a_closing_pass_that_changes_a_value_still_owes_its_follow_up() -> None:
    assert owed(slice_journal()) == {"s1": [(BUS, DRIVER)]}
