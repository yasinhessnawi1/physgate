"""A parts write the journal no longer holds as it landed halts the run before the release.

ARCH-122. The parts writer's writes land each with the digest of its whole payload. Once they
have landed, every declared quantity at the journal's head is held to them, by node, name,
value, unit, source and record. A journal whose line was changed after it landed (a value
changed, a declared quantity dropped, one added beside it) is not what the record says was
landed: the run halts with an integrity incident and is never released, and a process killed
after the writes landed makes the same check when it next starts.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import KilledError
from parts_rig import body, decide, log_of, started
from plan_hold_rig import again, kinds

from physgate.state.schema import DECLARED_SOURCE

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]


def _decided(tmp_path: Path) -> tuple[Path, Any]:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    the_rig.diff.ledger = run_dir / "parts_ledger.jsonl"
    assert not isinstance(
        decide(run_dir, IDS[0], "have", body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")})),
        Exception,
    )
    made = body({"mass": (0.1, "kg")}, texts=("printed in PETG",))
    assert not isinstance(decide(run_dir, IDS[1], "make", made), Exception)
    assert not isinstance(decide(run_dir, IDS[2], "find"), Exception)
    return run_dir, the_rig


def _of(run_dir: Path, kind: str) -> list[dict[str, Any]]:
    return [one for one in log_of(run_dir) if one["kind"] == kind]


def _value_changed(quantities: dict[str, Any]) -> None:
    name = next(n for n, q in quantities.items() if q.get("declared") is not None)
    quantities[name]["value"] = quantities[name]["value"] * 10


def _dropped(quantities: dict[str, Any]) -> None:
    name = next(n for n, q in quantities.items() if q.get("declared") is not None)
    del quantities[name]


def _one_added(quantities: dict[str, Any]) -> None:
    record = next(q["declared"] for q in quantities.values() if q.get("declared") is not None)
    quantities["torque_rated"] = {
        "value": 0.2,
        "unit": "N*m",
        "source": DECLARED_SOURCE,
        "written_by": next(iter(quantities.values()))["written_by"],
        "declared": dict(record),
    }


TAMPERS = {"value-changed": _value_changed, "dropped": _dropped, "one-added": _one_added}


def _rewrite_first_line(ledger: Path, tamper: Any) -> None:  # noqa: ANN401
    """Change the first landed line's payload in place, as an edit of the journal would."""
    lines = [json.loads(raw) for raw in ledger.read_text().splitlines()]
    tamper(lines[0]["payload"]["quantities"])
    ledger.write_text("".join(json.dumps(line) + "\n" for line in lines))


def _tampering(the_rig: Any, tamper: Any, *, kill: bool = False) -> None:  # noqa: ANN401
    """Each write lands; after the last one, the first landed line is changed in the journal."""
    diff: Any = the_rig.diff
    real = diff.declare
    owed = 4  # each component with a value: its own node, then its cross node

    def declare(payload: dict[str, Any], item_ids: tuple[str, ...]) -> int:
        revision: int = real(payload, item_ids)
        if len(diff.declared) == owed:
            _rewrite_first_line(diff.ledger, tamper)
            if kill:
                raise KilledError("after the last parts write landed, before its done line")
        return revision

    diff.declare = declare


@pytest.mark.parametrize("tamper", list(TAMPERS))
def test_a_landed_parts_line_changed_in_the_journal_halts_before_the_release(
    tmp_path: Path, tamper: str
) -> None:
    run_dir, the_rig = _decided(tmp_path)
    _tampering(the_rig, TAMPERS[tamper])
    assert again(the_rig) == "halted"
    (incident,) = _of(run_dir, "incident")
    assert incident["cause"] == "foreign_journal_line"
    assert _of(run_dir, "parts_released") == []
    assert "stage_entered" not in kinds(run_dir)


@pytest.mark.parametrize("tamper", list(TAMPERS))
def test_killed_after_the_writes_landed_the_next_process_finds_the_change_and_halts(
    tmp_path: Path, tamper: str
) -> None:
    run_dir, the_rig = _decided(tmp_path)
    _tampering(the_rig, TAMPERS[tamper], kill=True)
    with contextlib.suppress(KilledError):
        again(the_rig)
    assert _of(run_dir, "incident") == []
    the_rig.diff.declare = type(the_rig.diff).declare.__get__(the_rig.diff)
    assert again(the_rig) == "halted"
    (incident,) = _of(run_dir, "incident")
    assert incident["cause"] == "foreign_journal_line"
    assert _of(run_dir, "parts_released") == []
    # The last write was the run's own, accounted for before the check: never written twice.
    nodes = [one["node_id"] for one in _of(run_dir, "parts_write_intended")]
    assert len(nodes) == len(set(nodes))


def test_writes_that_stand_as_they_landed_release_the_run(tmp_path: Path) -> None:
    run_dir, the_rig = _decided(tmp_path)
    assert again(the_rig) == "done"
    assert "incident" not in kinds(run_dir)
    assert len(_of(run_dir, "parts_released")) == 1
