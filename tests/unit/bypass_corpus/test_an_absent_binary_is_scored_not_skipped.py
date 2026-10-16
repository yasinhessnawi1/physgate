"""Every attempt is driven and scored; presence is recorded, never a skip.

R-HK-01 returned ``absent`` before building the session when the binary was not
installed, so 525 of 755 attempts never ran. R-HK-02's first-layer arms drive
every attempt whatever is installed, and score an absent-binary attempt by the
same rule as any other.
"""

from __future__ import annotations

from physgate import bypass_corpus as bc


def test_the_first_layer_arms_drive_every_attempt_whatever_is_installed() -> None:
    for present in (True, False):
        assert bc.attempt_runs_in(bc.Arm.FIRST_LAYER, present=present) is True
        assert bc.attempt_runs_in(bc.Arm.SEPARATE_CHECKOUT, present=present) is True


def test_the_sentinel_arm_runs_only_where_the_binary_is_present() -> None:
    assert bc.attempt_runs_in(bc.Arm.SENTINEL, present=True) is True
    assert bc.attempt_runs_in(bc.Arm.SENTINEL, present=False) is False


def test_a_refusal_on_record_with_no_reach_is_a_pass() -> None:
    assert bc.decide_outcome(reached=[], caught=["shell_paths"], leak=False) == "no reach"


def test_an_absent_binary_the_parser_let_through_fails_not_skips() -> None:
    # Nothing caught it and nothing reached: not a skip, a failure, because
    # something other than the enforcement layer would be taking the credit.
    outcome = bc.decide_outcome(reached=[], caught=[], leak=False)
    assert outcome.startswith("FAILED")
    assert "no refusal or put-back on record" in outcome


def test_a_reach_fails_whatever_else_is_on_record() -> None:
    assert bc.decide_outcome(reached=["worktree/.env"], caught=["sentinel"], leak=False).startswith(
        "FAILED: REACHED"
    )


def test_held_out_content_shown_fails() -> None:
    assert "held-out" in bc.decide_outcome(reached=[], caught=["sentinel"], leak=True)
