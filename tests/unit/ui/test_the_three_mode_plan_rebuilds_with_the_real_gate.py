"""The three-mode plan, rebuilt with the real loop, store and gate, shows what its test asserts.

The operator UI's views and browser tests read these runs. The rig asserts each run's shape as
it builds it, so this test is that assertion run once; it then checks the run directories hold
what the UI reads, and that the gate's records are the real gate's: unchecked records, a pass
over nothing, and the catalogue digest the real gate stamps.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ui_three_mode_rig import MODES, three_mode_runs

from physgate.orchestrator.events import GateRan, IntegrationGateRan, read_events
from physgate.orchestrator.gate_events import recorded_gate_checks
from physgate.orchestrator.protocols import UncheckedDetails
from physgate.state.store import journal_records_after


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ...]:
    root = tmp_path_factory.mktemp("drive")
    return three_mode_runs(root, root / "runs")


def test_every_mode_is_built_whole(built: tuple[Path, ...]) -> None:
    assert [run.name for run in built] == [f"drive-{mode}" for mode in MODES]
    for run in built:
        for name in ("run.json", "events.jsonl", "ledger.jsonl", "store/journal.jsonl"):
            assert (run / name).is_file(), (run.name, name)
        assert len(journal_records_after(run / "store", 0)) >= 1
        assert any((run / "sessions").iterdir())


def test_the_gate_s_records_are_the_real_gate_s(built: tuple[Path, ...]) -> None:
    on, observe, off = built
    checks = recorded_gate_checks(on / "events.jsonl", on / "run.json")
    unchecked = [c for c in checks if c.event.outcome == "unchecked"]
    assert unchecked, "the real gate left nothing unchecked on the three-mode plan"
    for check in unchecked:
        assert isinstance(check.details, UncheckedDetails) and check.details.quantities
        assert check.message.strip()
    assert any("no sourced range" in c.message for c in unchecked)
    assert any(c.event.outcome == "pass" and c.event.evaluated == 0 for c in checks)
    assert recorded_gate_checks(off / "events.jsonl", off / "run.json") == []
    catalogues = {
        e.result.catalogue_sha256
        for e in read_events(observe / "events.jsonl")
        if isinstance(e, GateRan | IntegrationGateRan)
    }
    assert len(catalogues) == 1 and catalogues != {"c" * 64}, "not the real gate's catalogue"
