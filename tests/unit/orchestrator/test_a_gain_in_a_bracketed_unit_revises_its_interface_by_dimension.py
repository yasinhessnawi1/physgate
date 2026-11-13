"""A gain written in ``1/(rad*s)`` revises its interface, judged by dimension and not by spelling.

In a full run, sizing's opening pass wrote ``angle_gain`` in ``1/(rad*s)`` on a node joined to the
interface ``balance.controller``, and the change check refused the revision because the grammar
refused the bracket. The clause the interface keeps is that its quantities keep their kinds: a
unit of the interface's root units (pint's dimension and the power of the radian). So a gain in
``1/(rad*s)`` revises an interface held in any spelling of that unit, an interface of another kind
refuses it, and the refusal of a unit the grammar does not take names the spelling it does. Two
spellings of one unit compare equal: where only the spelling differs nothing is derived, and the
store refuses a revision that differs from the interface in spelling alone. A revision keeps the
interface's own spelling where the unit is one, and otherwise carries the product the grammar
reads the joined node's bracket as.

Each row catches a refusal and compares it, so a row fails on an assertion before the build.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_sizing_interface_follows_sizing_s_joined_node_at_its_opening_pass import (  # noqa: E402
    checked,
    store_of,
)

from physgate.orchestrator.follow import FollowRefusedError, derive  # noqa: E402
from physgate.state.store import (  # noqa: E402
    REJECT_INTERFACE_NOT_FOLLOWED,
    Store,
    followed_payload,
)

IFACE = "balance.controller"
JOINED = "sizing.balance_controller"


def _quantity(value: float, unit: str, by: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "the plan" if by == "plan" else "sized",
            "written_by": "sizing"}  # fmt: skip


def interface(unit: str, value: float = 2.0) -> dict[str, Any]:
    return {
        "id": IFACE, "kind": "interface", "domain": "cross", "owner_role": "sizing",
        "quantities": {"angle_gain": _quantity(value, unit, "plan")},
        "requirements": ["criterion 6"], "constrains": ["control.loop"], "model": None,
        "geometry_hash": "none", "updated": "2026-11-11",
    }  # fmt: skip


def gain(unit: str, value: float = 3.5) -> dict[str, Any]:
    return {
        "id": JOINED, "kind": "component", "domain": "cross", "owner_role": "sizing",
        "quantities": {"angle_gain": _quantity(value, unit, "sizing")},
        "requirements": [], "constrains": [IFACE], "model": None,
        "geometry_hash": "none", "updated": "2026-11-11",
    }  # fmt: skip


def derived(held: str, written: str, *, held_value: float = 2.0, value: float = 3.5) -> Any:  # noqa: ANN401
    """The derivation, or the refusal's words."""
    try:
        return derive(interface(held, held_value), {JOINED: gain(written, value)}, "sizing", 1)
    except FollowRefusedError as exc:
        return f"refused: {exc}"


@pytest.mark.parametrize(
    ("held", "kept"),
    [("rad**-1*s**-1", "rad**-1*s**-1"), ("1/rad/s", "1/rad/s"), ("1/(rad*s)", "1/(rad*s)"),
     ("s**-1/rad", "s**-1/rad"), ("Hz/rad", "1/rad/s")],
)  # fmt: skip
def test_a_gain_in_1_over_rad_s_revises_an_interface_of_that_dimension(
    held: str, kept: str
) -> None:
    # The interface's own spelling where the unit is one; Hz/rad is another unit by name, of the
    # same kind, so the revision carries the product the joined node's bracket is read as.
    after = derived(held, "1/(rad*s)")
    assert isinstance(after, dict), after
    found = after["quantities"]["angle_gain"]
    assert (found["value"], found["unit"]) == (3.5, kept)
    assert found["source"] == f"followed from {JOINED} at attempt 1"


@pytest.mark.parametrize("held", ["1/s", "rad/s", "V/(m*s)", "1/rad"])
def test_an_interface_of_another_kind_refuses_the_gain(held: str) -> None:
    said = derived(held, "1/(rad*s)")
    assert isinstance(said, str) and said.startswith("refused: "), said
    assert "angle_gain" in said and "the interface keeps its quantities' kinds" in said
    assert "not in the root units" in said


def test_a_gain_the_grammar_refuses_is_refused_naming_the_spelling_it_takes() -> None:
    said = derived("rad**-1*s**-1", "1/(rad*(s))")
    assert isinstance(said, str) and said.startswith("refused: "), said
    assert "write it as 1/rad/s" in said


@pytest.mark.parametrize(
    ("held", "written"),
    [("1/rad/s", "1/(rad*s)"), ("1/(rad*s)", "1/rad/s"), ("1/(rad*s)", "1/( rad*s )")],
)
def test_where_only_the_spelling_differs_nothing_is_derived(held: str, written: str) -> None:
    assert derived(held, written, held_value=3.5, value=3.5) is None


def test_the_store_refuses_a_revision_that_differs_in_spelling_alone(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = Store(root)
    try:
        for payload in (interface("1/(rad*s)", 3.5), gain("1/rad/s", 3.5)):
            assert store.write_node(payload, "sizing").accepted
        respelt = followed_payload(interface("1/(rad*s)", 3.5), [gain("1/rad/s", 3.5)], "sizing", 1)
        refused = store.follow_interface(respelt, "sizing", (JOINED,))
        assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED
    finally:
        store.close()


def test_the_store_writes_the_revision_in_the_product_the_bracket_is_read_as(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    store = Store(root)
    try:
        for payload in (interface("1/rad/s"), gain("1/(rad*s)")):
            assert store.write_node(payload, "sizing").accepted
        after = followed_payload(interface("1/rad/s"), [gain("1/(rad*s)")], "sizing", 1)
        assert after["quantities"]["angle_gain"]["unit"] == "1/rad/s"
        assert store.follow_interface(after, "sizing", (JOINED,)).accepted
    finally:
        store.close()


# --- an interface stored in the bracket form at decomposition --------------------------------
# A full run's third sizing attempt wrote 1/rad/s and was still refused: the decomposition had
# stored the interface's unit as 1/(rad*s), which the grammar then refused. The decomposition
# writes an interface's units as the plan gives them, so the change check must match a stored
# bracket form, comparing both sides in the unit's canonical form; the revision keeps the
# interface's own spelling of the unit.

_SPELLINGS = ["1/rad/s", "rad**-1*s**-1"]


@pytest.mark.parametrize("written", _SPELLINGS)
def test_an_interface_stored_as_1_over_rad_s_in_brackets_takes_a_revision_in_its_product(
    tmp_path: Path, written: str
) -> None:
    after = derived("1/(rad*s)", written)
    assert isinstance(after, dict), after
    assert (
        after["quantities"]["angle_gain"]["value"],
        after["quantities"]["angle_gain"]["unit"],
    ) == (
        3.5,
        "1/(rad*s)",
    )
    store = Store(tmp_path / "store")
    try:
        for payload in (interface("1/(rad*s)"), gain(written)):
            assert store.write_node(payload, "sizing").accepted
        followed = followed_payload(interface("1/(rad*s)"), [gain(written)], "sizing", 1)
        assert followed == after
        assert store.follow_interface(followed, "sizing", (JOINED,)).accepted
    finally:
        store.close()


@pytest.mark.parametrize("written", _SPELLINGS)
def test_the_change_check_follows_an_interface_stored_in_brackets(
    tmp_path: Path, written: str
) -> None:
    store = store_of(tmp_path / "store", interface("1/(rad*s)"))
    check = checked(tmp_path, store, gain(written))
    assert check.refused_by is None, check.reason
    followed: tuple[Any, ...] = getattr(check, "followed", ())
    (entry,) = followed
    found = entry.after["quantities"]["angle_gain"]
    assert (found["value"], found["unit"]) == (3.5, "1/(rad*s)")


def test_where_the_stored_bracket_form_and_its_product_are_one_value_nothing_is_derived() -> None:
    assert derived("1/(rad*s)", "1/rad/s", held_value=3.5, value=3.5) is None


def test_a_negative_power_spelling_of_one_value_derives_nothing() -> None:
    # rad**-1*s**-1 is another spelling of 1/(rad*s): a change of spelling alone is no revision.
    assert derived("1/(rad*s)", "rad**-1*s**-1", held_value=3.5, value=3.5) is None
