"""A raw session's record names the held-out digests of the harness run it was held to.

A raw session that saw a canary exposes a version, and its record says which: the digests of
the run's held-out roots, taken from the run's own record, as every other pin is. They are not
a pin: the pair is held equal on its pins, and the run's digests are the run's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from exposure_fixtures import config, stand_in_store

BASELINE_TESTS = Path(__file__).resolve().parents[1] / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import setup_for  # noqa: E402

from physgate.evaluation.per_role.arms import raw  # noqa: E402


def test_the_setup_from_a_run_carries_the_run_s_held_out_digests(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path / "s")
    run = config(made.tasks["visible"][0], made)
    setup = setup_for(run, "control")
    assert getattr(setup, "held_out_sha256", None) == tuple(run.held_out_sha256)


def test_the_raw_record_names_the_digests_beside_its_pins_not_among_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = stand_in_store(tmp_path / "s")
    task = made.tasks["visible"][0]
    run = config(task, made)

    def session(
        _prompt: str,
        _setup: Any,  # noqa: ANN401
        work: Path,
        *,
        cap: int,  # noqa: ARG001
        identity: list[tuple[int, int]],
    ) -> dict[str, Any]:
        work.mkdir()
        (work / "worktree").mkdir()
        identity.extend((i.st_dev, i.st_ino) for i in (work.stat(), (work / "worktree").stat()))
        return {"end": "ended", "held_out_seen": False}

    monkeypatch.setattr(raw, "run_session", session)
    harness = tmp_path / "trial" / "harness"
    harness.mkdir(parents=True)
    place = tmp_path / "trial" / "place"
    record = raw.run_raw(task, setup_for(run, "control"), place, cap=1, harness=harness)
    written = json.loads((harness / "raw.json").read_text())
    for found in (record, written):
        assert found.get("held_out_sha256") == list(run.held_out_sha256)
        assert "held_out_sha256" not in found["pins"]
