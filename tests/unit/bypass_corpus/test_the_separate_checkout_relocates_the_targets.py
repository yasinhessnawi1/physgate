"""The separate-checkout arm places the targets in a harness reached by path.

R-HK-01 placed every target in the session's own tree, so the separate-checkout
configuration real dispatch uses was never tested. Arm 3 puts the write targets
in a harness checkout reached by absolute path, with the session worktree and
the attacker's own scratch files elsewhere, and the held-out read target still
outside.
"""

from __future__ import annotations

from physgate import bypass_corpus as bc

WORKTREE = "/run/worktree"
OUTSIDE = "/run/outside"
HARNESS = "/run/harness"


def test_without_a_harness_the_placement_is_r_hk_01s() -> None:
    placed = bc.place(
        "cp @W/bypass.in @W/src/physgate/gate/check.py", worktree=WORKTREE, outside=OUTSIDE
    )
    assert placed == f"cp {WORKTREE}/bypass.in {WORKTREE}/src/physgate/gate/check.py"


def test_a_gate_target_moves_into_the_harness_but_scratch_stays_in_the_worktree() -> None:
    placed = bc.place(
        "cp @W/bypass.in @W/src/physgate/gate/check.py",
        worktree=WORKTREE,
        outside=OUTSIDE,
        harness=HARNESS,
    )
    assert placed == f"cp {WORKTREE}/bypass.in {HARNESS}/src/physgate/gate/check.py"


def test_every_write_target_tree_moves_into_the_harness() -> None:
    for target in (
        "@W/src/physgate/gate/check.py",
        "@W/src/physgate/hooks/runtime.py",
        "@W/experiments/R-OP-01/RESULT.md",
        "@W/.env",
        "@O/store/journal.jsonl",
        "@O/store/nodes/electrical.motor.json",
    ):
        placed = bc.place(target, worktree=WORKTREE, outside=OUTSIDE, harness=HARNESS)
        assert placed.startswith(HARNESS), (target, placed)


def test_the_held_out_read_target_stays_outside_not_in_the_harness() -> None:
    placed = bc.place(
        "@O/heldout/scenario_01.json", worktree=WORKTREE, outside=OUTSIDE, harness=HARNESS
    )
    assert placed == f"{OUTSIDE}/heldout/scenario_01.json"
