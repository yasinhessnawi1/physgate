"""The names a hook refuses proposals by are the catalogue's, held equal by this test.

A hook may not load the gate, so the catalogue's names are spelled again in the state
package. Two lists that drift apart would let a session write a name the gate does not read,
or refuse one it does; this test is what makes the second spelling safe.
"""

from __future__ import annotations

from physgate.gate.catalogue import QUANTITIES, unknown_names
from physgate.state.vocabulary import (
    QUANTITY_NAMES,
    nearest_quantity_names,
    unknown_quantity_names,
)


def test_the_vocabulary_is_the_catalogue_s_names_sorted() -> None:
    assert tuple(sorted(QUANTITIES)) == QUANTITY_NAMES
    assert len(QUANTITY_NAMES) >= 30


def test_both_spellings_find_the_same_unknown_names() -> None:
    names = {"stall_current": 1, "motor_current": 2, "pack_mass": 3, "zeta": 4}
    assert (
        unknown_quantity_names(names)
        == unknown_names(names)
        == ("motor_current", "pack_mass", "zeta")
    )
    assert unknown_quantity_names({}) == unknown_names({}) == ()
    assert unknown_quantity_names("not a mapping") == ()


def test_the_hook_s_nearest_names_are_catalogued_and_share_a_word() -> None:
    near = nearest_quantity_names("motor_current")
    assert near and all(n in QUANTITIES for n in near)
    assert near[0].endswith("_current")
    assert nearest_quantity_names("zeta") == () and nearest_quantity_names("") == ()
