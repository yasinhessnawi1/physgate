"""The sentinel arm holds the first-layer parser off; the others keep it.

Arm 2 puts the second layer on trial by running without the shell-path parser,
so the binary executes and the sentinel must catch it. Every other arm runs the
full registry.
"""

from __future__ import annotations

from physgate import bypass_corpus as bc

FULL = {"shell_paths": 1, "sentinel": 2, "tools": 3, "reading": 4}


def test_the_sentinel_arm_drops_the_shell_path_parser() -> None:
    reduced = bc.registry_for(bc.Arm.SENTINEL, FULL)
    assert "shell_paths" not in reduced
    assert set(reduced) == set(FULL) - {"shell_paths"}


def test_the_first_layer_arms_keep_every_hook() -> None:
    for arm in (bc.Arm.FIRST_LAYER, bc.Arm.SEPARATE_CHECKOUT):
        assert bc.registry_for(arm, FULL) == FULL


def test_registry_for_does_not_mutate_the_registry_it_is_given() -> None:
    bc.registry_for(bc.Arm.SENTINEL, FULL)
    assert "shell_paths" in FULL


def test_an_arm_is_named_by_its_value_or_its_name() -> None:
    assert bc.Arm.of("arm2-sentinel") is bc.Arm.SENTINEL
    assert bc.Arm.of("SENTINEL") is bc.Arm.SENTINEL
