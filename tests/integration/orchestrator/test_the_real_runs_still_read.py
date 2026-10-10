"""The records of the real paired-review runs still read, with every reader.

The logs of the first three real paired-review runs are evidence, and the third was
written before a blocked review was a review line: it holds one no-verdict line with
the legacy blocked cause. Each run is copied out first; the originals are never
opened for writing. Every reader command reads each copy and exits 0, the replay
takes every line, the paired driver's own checks run, and the legacy line is read as
written. ``PHYSGATE_REAL_RUNS`` names the directory holding ``paired-1`` to
``paired-3``; without it the test is skipped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest
from real_paired_reviewers import REVIEW_DIRNAME, RUN_ID, check_paired

from physgate.cli import main
from physgate.orchestrator.events import ReviewUnavailable, read_events
from physgate.orchestrator.replay import RunState

RUNS = os.environ.get("PHYSGATE_REAL_RUNS")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not RUNS, reason="PHYSGATE_REAL_RUNS names no directory of real runs"),
]
NAMES = ("paired-1", "paired-2", "paired-3")
#: The real runs' price sheet.
PRICES = "2026-09-27"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(name: str, into: Path) -> Path:
    """The run's records, copied; its installed environment and target checkout left out."""
    source = Path(str(RUNS)) / name
    top = {"install", "target"}

    def skip(directory: str, names: list[str]) -> set[str]:
        return top & set(names) if Path(directory) == source else set()

    return Path(shutil.copytree(source, into / name, ignore=skip, symlinks=True))


@pytest.fixture(scope="module")
def copies(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    into = tmp_path_factory.mktemp("real-runs")
    before = {n: _digest(Path(str(RUNS)) / n / RUN_ID / "events.jsonl") for n in NAMES}
    made = {n: _copy(n, into) for n in NAMES}
    assert {n: _digest(made[n] / RUN_ID / "events.jsonl") for n in NAMES} == before
    return made


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "command",
    ["gate-events", "catches", "manifest", "trace", "cost", "compare", "queue list"],
)
def test_every_reader_reads_the_copy(
    copies: dict[str, Path], name: str, command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = str(copies[name] / RUN_ID)
    argv = {
        "cost": ["cost", "--run-dir", run_dir, "--prices", PRICES],
        "compare": ["compare", run_dir, run_dir],
        "queue list": ["queue", "list", "--run-dir", run_dir],
    }.get(command, [command, "--run-dir", run_dir])
    assert main(argv) == 0, capsys.readouterr().err[-500:]


def test_the_runs_are_told_apart_by_their_configuration_not_refused_as_unreadable(
    copies: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["variance", "--runs", *(str(copies[n] / RUN_ID) for n in NAMES)]
    assert main(argv) == 2
    printed = capsys.readouterr()
    assert "not repeats of one configuration" in printed.out + printed.err


@pytest.mark.parametrize("name", NAMES)
def test_the_replay_takes_every_line_and_the_driver_s_checks_run(
    copies: dict[str, Path], name: str
) -> None:
    run_dir = copies[name] / RUN_ID
    state = RunState()
    for event in read_events(run_dir / "events.jsonl"):
        state.record(event)
    checked = check_paired(run_dir, copies[name] / REVIEW_DIRNAME)
    assert set(checked["checks"]) >= {"every_review_ends_in_a_verdict", "every_subtask_reviewed"}


def test_the_legacy_line_is_read_as_written(copies: dict[str, Path]) -> None:
    events = read_events(copies["paired-3"] / RUN_ID / "events.jsonl")
    legacy = [
        e for e in events if isinstance(e, ReviewUnavailable) and e.cause == "blocking_spec_defect"
    ]
    assert len(legacy) == 1 and not legacy[0].retry
    assert sum(d.blocking for d in legacy[0].spec_defects) == 18
    assert len(legacy[0].spec_defects) == 28
