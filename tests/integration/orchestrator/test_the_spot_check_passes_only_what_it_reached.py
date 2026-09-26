"""The spot check's verdict: passed only when every applicable condition was reached and holds.

Its first real run stopped at decomposition and still printed ``passed: true``,
because the conditions it never reached were simply absent.
"""

from __future__ import annotations

import pytest
from spot_check import C1, C6, C7, C8, C10, applicable, verdict

pytestmark = pytest.mark.integration


def test_a_run_that_stopped_before_its_checks_has_not_passed() -> None:
    # The first real run: decomposition stopped it; what could be judged, was.
    checks = {C1: True, C6: True, C7: True, C8: True, C10: False}
    passed, not_reached = verdict(checks, "b")
    assert passed is False
    assert not_reached == [c for c in applicable("b") if c not in checks]
    assert len(not_reached) == 6


def test_every_condition_reached_and_holding_is_a_pass_and_one_false_is_not() -> None:
    for variant in ("a", "b"):
        checks = dict.fromkeys(applicable(variant), True)
        assert verdict(checks, variant) == (True, [])
        checks[C7] = False
        assert verdict(checks, variant) == (False, [])


def test_nothing_reached_is_never_a_pass() -> None:
    assert verdict({}, "a") == (False, list(applicable("a")))
    assert C10 not in applicable("a") and C10 in applicable("b")


def test_every_reached_condition_holding_is_still_no_pass_while_any_is_unreached() -> None:
    # Exactly the first real run's printout: the one condition it judged held.
    passed, not_reached = verdict({C8: True}, "b")
    assert passed is False and C8 not in not_reached and len(not_reached) == 10
