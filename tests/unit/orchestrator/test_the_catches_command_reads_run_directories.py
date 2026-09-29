"""``physgate catches``: the catch count over run directories on disk, and a window of time.

The same two synthetic runs and hand-computed table as the query's own tests,
written as run directories the command reads through the log reader.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from orch_helpers import make_config
from synthetic_ledger import Log
from test_the_catch_count_is_queryable_from_the_ledger import (
    BY_HAND,
    observe_run,
    on_run,
    table,
)

from physgate.orchestrator.catches import CatchRow
from physgate.orchestrator.events import Event, RunStarted, SubtaskPlanned, read_events
from physgate.orchestrator.run_config import write_run_config


def write_run(root: Path, log: Log) -> Path:
    """``log`` as a run directory the command reads: a start, a plan, then its lines.

    Written line by line with each line's own time, so a window over it means
    what it says, and read back through the log reader that refuses a line no
    run could have written. A real ``run.json`` is written too, since the
    command now takes the run's manifest id (``RunConfig.sha256()``) from it,
    the same way ``run``/``resume`` do.
    """
    root.mkdir(parents=True)
    config = make_config(run_id=log.run_id, gate_mode=log.mode)
    write_run_config(root / "run.json", config)
    env: dict[str, Any] = {"ts": log.ts, "run_id": log.run_id, "gate_mode": log.mode}
    subtasks = sorted({s for e in log.lines if (s := getattr(e, "subtask_id", None))})
    head: list[Event] = [RunStarted(seq=0, **env, config_sha256=config.sha256())]
    head += [
        SubtaskPlanned(
            seq=n,
            **env,
            subtask_id=s,
            spec_path=f"specs/{s}.md",
            assigned_role="electrical",
            module_dir="m",
        )
        for n, s in enumerate(subtasks, start=1)
    ]
    body = [e.model_copy(update={"seq": e.seq + len(head)}) for e in log.lines]
    path = root / "events.jsonl"
    path.write_text("".join(e.model_dump_json() + "\n" for e in head + body))
    assert len(read_events(path)) == len(head) + len(body)
    return root


def test_the_command_prints_the_table_over_several_run_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    one = write_run(tmp_path / "one", observe_run())
    two = write_run(tmp_path / "two", on_run())
    assert main(["catches", "--run-dir", str(one), "--run-dir", str(two)]) == 0
    rows = [CatchRow.model_validate(json.loads(x)) for x in capsys.readouterr().out.splitlines()]
    assert table(rows) == BY_HAND


def test_the_command_s_rows_name_no_single_run_since_a_row_can_span_several(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unlike ``gate-events``, a row here is aggregated over every run named.

    ``observe_run()`` and ``on_run()`` are written under two distinct configs
    (distinct ``run.json``, distinct manifest id), and the "all" row below sums
    over both. An artefact is already kept distinct by its own run id inside
    the count (``artefact()`` in ``catches.py``); there is no one manifest id
    a spanning row could honestly carry, so the command adds none.
    """
    from physgate.cli import main

    one = write_run(tmp_path / "one", observe_run())
    two = write_run(tmp_path / "two", on_run())
    assert main(["catches", "--run-dir", str(one), "--run-dir", str(two)]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert lines  # the run above the assertion needs at least one row to be meaningful
    assert all("manifest_id" not in x for x in lines)


def test_the_command_takes_a_week(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from physgate.cli import main

    one = write_run(tmp_path / "one", observe_run())
    two = write_run(tmp_path / "two", on_run())
    args = ["--since", "2026-09-28", "--until", "2026-10-05"]
    assert main(["catches", "--run-dir", str(one), "--run-dir", str(two), *args]) == 0
    rows = [CatchRow.model_validate(json.loads(x)) for x in capsys.readouterr().out.splitlines()]
    assert {r.gate_mode for r in rows} == {"on"}


def test_the_command_prints_nothing_for_a_run_with_no_gate_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    log = Log()
    log.review("s1", 1, "pass")
    run = write_run(tmp_path / "run", log)
    capsys.readouterr()
    assert main(["catches", "--run-dir", str(run)]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "args",
    [["--run-dir", "/nowhere"], ["--run-dir", ".", "--since", "last week"]],
    ids=["a run directory with no log", "a window that is not a date"],
)
def test_the_command_refuses_what_it_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    from physgate.cli import main

    assert main(["catches", *args]) == 2
    assert "error" in json.loads(capsys.readouterr().err)
