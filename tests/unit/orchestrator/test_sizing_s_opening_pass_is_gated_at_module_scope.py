"""Sizing's opening pass is gated at module scope as well as at its own (ARCH-080 amended).

The domains read sizing's nodes as they stand after its opening pass, so the relations those nodes
form are judged there, not only once sizing's closing pass completes the module. A domain's subtask
keeps module scope only when it completes its module: a half-written domain module would fail its
mass sum falsely.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import CLOSING, entry, rig_of, run  # noqa: E402
from loop_fakes import FakeGate  # noqa: E402

from physgate.orchestrator.record import PlanEntry  # noqa: E402


def scopes_by_subtask(tmp_path: Path, plan: list[PlanEntry]) -> dict[str, tuple[str, ...]]:
    rig = rig_of(tmp_path / "run", script=[()])
    assert run(rig, plan=plan) == "done"
    assert isinstance(rig.gate, FakeGate)
    return {a.subtask_id: tuple(a.scopes) for a in rig.gate.seen}


def test_the_opening_pass_is_checked_at_subtask_and_module_scope(tmp_path: Path) -> None:
    seen = scopes_by_subtask(tmp_path, CLOSING)
    assert seen["z0"] == ("subtask", "module")


def test_the_closing_pass_and_a_lone_domain_subtask_keep_their_scopes(tmp_path: Path) -> None:
    seen = scopes_by_subtask(tmp_path, CLOSING)
    assert seen["zc"] == ("subtask", "module")
    assert seen["s1"] == ("subtask", "module")


def test_a_domain_subtask_that_does_not_complete_its_module_is_checked_at_its_own_scope(
    tmp_path: Path,
) -> None:
    plan = [
        entry("z0", "sizing"),
        entry("s1", "electrical", "modules/e"),
        entry("s2", "electrical", "modules/e"),
        entry("zc", "sizing", "modules/z0"),
    ]
    seen = scopes_by_subtask(tmp_path, plan)
    assert seen["z0"] == ("subtask", "module")
    assert seen["s1"] == ("subtask",)
    assert seen["s2"] == ("subtask", "module")
