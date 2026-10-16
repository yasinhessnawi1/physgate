"""The R-HK-02 launch script wires the tested decisions to real sessions.

The decisions themselves are unit-tested in ``tests/unit/bypass_corpus``. Here
the wiring is checked: that the separate-checkout arm actually places the
targets in the harness and not the worktree, that the sentinel arm does not
drive an attempt whose binary is absent, and — where a pinned Claude Code binary
is present — that a driven attempt is refused with nothing reached.
"""

from __future__ import annotations

from pathlib import Path

import bypass_corpus_runner as runner
import pytest

from physgate import bypass_corpus as bc

FROZEN = Path(__file__).resolve().parents[3] / "experiments" / "R-HK-01" / "attempts.jsonl"


def _attempt(attempt_id: str) -> dict[str, object]:
    (found,) = [a for a in bc.load_attempts(FROZEN) if a["id"] == attempt_id]
    return found


def test_the_separate_checkout_places_the_gate_target_in_the_harness(tmp_path: Path) -> None:
    runner._prepare_separate_checkout(tmp_path)
    harness = tmp_path / "outside" / "harness"
    assert (harness / "src" / "physgate" / "gate" / "check.py").exists()
    assert not (tmp_path / "worktree" / "src" / "physgate" / "gate" / "check.py").exists()
    placed = bc.place(
        str(_attempt("w-tee-gate")["code"]),
        worktree=tmp_path / "worktree",
        outside=tmp_path / "outside",
        harness=harness,
    )
    assert str(harness) in placed
    assert "@W" not in placed and "@O" not in placed


def test_the_sentinel_arm_does_not_drive_an_absent_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bc, "resolve_executable", lambda _binary: None)
    record = runner.run_one(_attempt("w-tee-gate"), bc.Arm.SENTINEL)
    assert record["present"] is False
    assert str(record["outcome"]).startswith("not driven")


def test_the_first_layer_arm_drives_an_absent_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The decision only; the session is not spawned here. An absent binary is
    # still driven in arm 1, where R-HK-01 would have skipped it.
    monkeypatch.setattr(bc, "resolve_executable", lambda _binary: None)
    assert bc.attempt_runs_in(bc.Arm.FIRST_LAYER, present=False) is True


@pytest.mark.integration
def test_arm1_refuses_a_shell_write_to_the_gate_with_nothing_reached(tmp_path: Path) -> None:
    record = runner.run_one(_attempt("w-tee-gate"), bc.Arm.FIRST_LAYER)
    assert record["reached"] == []
    assert record["outcome"] == "no reach"
    assert "shell_paths" in record["caught_by"]


@pytest.mark.integration
def test_arm3_refuses_a_shell_write_into_the_separate_checkout(tmp_path: Path) -> None:
    record = runner.run_one(_attempt("w-tee-gate"), bc.Arm.SEPARATE_CHECKOUT)
    assert record["reached"] == []
    assert record["outcome"] == "no reach"
