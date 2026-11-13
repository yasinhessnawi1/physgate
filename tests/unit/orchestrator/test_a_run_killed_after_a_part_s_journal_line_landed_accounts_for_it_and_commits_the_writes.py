"""A journal line that landed before its done line is the run's own; the writes are committed.

ARCH-122. A process killed after the store accepted a parts write and before the loop wrote its
done line leaves a journal line no intent's done line accounts for. The next process finds the
pending intent on the record, and the line is the intent's: it writes the done line, never the
write again, and never calls the line foreign. The run commits the store once the writes are
written, before it releases, so what the person declared is in the repository a resume reads, and
a run that wrote nothing commits nothing.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from loop_fakes import KilledError
from parts_rig import body, decide, find_all, log_of, started
from plan_hold_rig import again, kinds

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


def test_a_line_that_landed_before_its_done_line_is_the_intents_and_is_not_written_twice(
    tmp_path: Path,
) -> None:
    run_dir, the_rig = _decided(tmp_path)
    real = the_rig.diff.declare
    calls: list[str] = []

    def landed_then_killed(payload: dict[str, Any], item_ids: tuple[str, ...]) -> int:
        calls.append(str(payload["id"]))
        revision = real(payload, item_ids)
        if len(calls) == 1:
            raise KilledError("after the journal line, before its done line")
        return revision

    the_rig.diff.declare = landed_then_killed  # type: ignore[method-assign]
    with contextlib.suppress(KilledError):
        again(the_rig)
    assert len(_of(run_dir, "parts_write_intended")) == 1
    assert _of(run_dir, "parts_write_done") == []
    the_rig.diff.declare = real  # type: ignore[method-assign]
    assert again(the_rig) == "done"
    assert "incident" not in kinds(run_dir)
    nodes = [one["node_id"] for one in _of(run_dir, "parts_write_intended")]
    assert len(nodes) == len(set(nodes)) == 3
    assert [one["node_id"] for one in _of(run_dir, "parts_write_done")] == nodes
    assert len(_of(run_dir, "parts_released")) == 1


def test_the_store_is_committed_once_after_the_last_write_and_before_the_release(
    tmp_path: Path,
) -> None:
    run_dir, the_rig = _decided(tmp_path)
    committed: list[tuple[str, int]] = []
    the_rig.diff.commit = lambda message: committed.append(  # type: ignore[method-assign]
        (message, len(_of(run_dir, "parts_write_done")))
    )
    assert again(the_rig) == "done"
    assert len(committed) == 1
    assert committed[0][1] == 3, "the commit came before the last write was done"
    assert "parts_released" in kinds(run_dir)
    assert _of(run_dir, "parts_released")[0]["seq"] > _of(run_dir, "parts_write_done")[-1]["seq"]
    assert "declared" in committed[0][0].lower()


def test_a_run_that_wrote_nothing_commits_nothing(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    committed: list[str] = []
    the_rig.diff.commit = committed.append  # type: ignore[method-assign]
    find_all(the_rig.run_dir)
    assert again(the_rig) == "done"
    assert committed == []
    assert _of(the_rig.run_dir, "parts_write_intended") == []
