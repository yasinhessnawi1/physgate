"""A law's worked examples are run when the table loads, through the evaluator the check uses.

Each law carries a worked example that passes and one that fails, from a cited data sheet or
text. The loader measures every example value against its kind and evaluates the law on them
exactly as the laws check evaluates an instance on a graph. A table whose example does not give
its stated outcome, or cannot be evaluated at all, is refused, naming the law and the example:
a law that misjudges its own worked numbers never reaches a design.
"""

from __future__ import annotations

from pathlib import Path

from law_cases import (
    every_case,
    example,
    reaction_sum,
    stall_by_resistance,
    table,
    within_rating,
)
from law_fixtures import refused, sound_law


def test_every_case_s_examples_give_their_outcomes_and_the_table_loads(tmp_path: Path) -> None:
    loaded = table(tmp_path, every_case())
    assert sorted(loaded.laws) == sorted(law["id"] for law in every_case())


def test_a_pass_example_that_fails_refuses_the_table(tmp_path: Path) -> None:
    law = within_rating(
        example=[
            example("pass", I=(2.5, "A"), L=(2, "A")),
            example("fail", I=(2.5, "A"), L=(2, "A")),
        ]
    )
    reason = refused(tmp_path, [law])
    assert "within_rating" in reason and "pass example" in reason and "fails" in reason


def test_a_fail_example_that_passes_refuses_the_table(tmp_path: Path) -> None:
    # Within the propagated rounding of 3.3 V times 3.9 mA: the law holds on it.
    law = sound_law(
        example=[
            example("pass", P=(12.9, "mW"), V=(3.3, "V"), I=(3.9, "mA")),
            example("fail", P=(12.95, "mW"), V=(3.3, "V"), I=(3.9, "mA")),
        ]
    )
    reason = refused(tmp_path, [law])
    assert "electrical_power" in reason and "fail example" in reason and "passes" in reason


def test_an_example_summed_over_members_is_judged_member_by_member(tmp_path: Path) -> None:
    law = reaction_sum(
        example=[
            example("pass", M=(3, "N*m"), T=[(1, "N*m"), (2, "N*m")]),
            example("fail", M=(3, "N*m"), T=[(1, "N*m"), (2.001, "N*m")]),
        ]
    )
    # 3 against 3.001 is within the rounding of 3 + 1 + 2.001: the fail example holds.
    reason = refused(tmp_path, [law])
    assert "reaction_moment_sum" in reason and "fail example" in reason


def test_an_example_that_divides_by_zero_refuses_the_table(tmp_path: Path) -> None:
    law = stall_by_resistance(
        example=[
            example("pass", I=(2, "A"), V=(12, "V"), R=(6, "ohm")),
            example("fail", I=(3, "A"), V=(12, "V"), R=(0, "ohm")),
        ]
    )
    reason = refused(tmp_path, [law])
    assert "stall_by_resistance" in reason and "fail example" in reason and "zero" in reason


def test_an_example_in_a_unit_its_kind_refuses_refuses_the_table(tmp_path: Path) -> None:
    law = within_rating(
        example=[
            example("pass", I=(1.2, "V"), L=(2, "A")),
            example("fail", I=(2.5, "A"), L=(2, "A")),
        ]
    )
    reason = refused(tmp_path, [law])
    assert "within_rating" in reason and "pass example" in reason and "I" in reason
