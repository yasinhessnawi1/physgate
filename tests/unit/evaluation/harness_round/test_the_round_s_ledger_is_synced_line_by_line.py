"""Each line of the round's ledger is synced before the step it names is taken.

A kill after a line's write returned must find the line, so each write is synced to the disk
before the round goes on: the ledger's own file at every line, and its directory once, when the
ledger is made, so the file's entry is there too. Read here from every sync the process asks of
the system while a line is written, by the file each one syncs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, make_rig

from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import run_round


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _file(path: Path) -> tuple[int, int]:
    found = os.stat(path)
    return found.st_dev, found.st_ino


def test_every_ledger_line_is_synced_and_the_ledger_s_directory_once_it_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path)
    synced: list[tuple[int, int]] = []
    sync = os.fsync

    def recorded(fd: int) -> None:
        found = os.fstat(fd)
        synced.append((found.st_dev, found.st_ino))
        sync(fd)

    monkeypatch.setattr(os, "fsync", recorded)
    append = harness_round._append  # noqa: SLF001 - the ledger's one writer, watched
    lines: list[tuple[str, bool, bool]] = []

    def watched(ledger: Path, line: Any) -> None:  # noqa: ANN401
        before = len(synced)
        append(ledger, line)
        during = synced[before:]
        lines.append((line["kind"], _file(ledger) in during, _file(ledger.parent) in during))

    monkeypatch.setattr(harness_round, "_append", watched)
    status, _ = run_round(rig.inputs(), driver=rig.driver(), scorer=_score, sleep=lambda _: None)
    assert status == "done"
    assert [kind for kind, _, _ in lines] == [
        "round",
        "placed",
        "assembled",
        "placed",
        "assembled",
        "ended",
    ]
    assert [kind for kind, file, _ in lines if not file] == [], "a line was not synced"
    assert [directory for _, _, directory in lines] == [True] + [False] * (len(lines) - 1)
