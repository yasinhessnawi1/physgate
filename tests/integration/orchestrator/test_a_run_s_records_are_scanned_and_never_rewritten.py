"""A run's records are scanned at the end and never rewritten, so the baseline can hold them.

The end-of-run scan once replaced every email address under the output directory, sealed
trajectories included, and the generalist baseline then refused the run: a trajectory was
no longer what it was when its session ended. Here a scripted paired run whose control
session writes an address into its own stream is followed by the generalist on it: the
scan counts the address, every seal still holds, and the baseline proceeds.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import real_domain_roles as base
import real_paired_reviewers as paired
from record_scan import scan

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.trajectory import seal

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("PHYSGATE_CLAUDE_BIN"), reason="no pinned Claude Code binary named"
    ),
]
#: What the paired driver points the first run's driver at, restored after the test.
POINTED = (
    "CONTROL_SPEC",
    "BRIEF",
    "params",
    "FIRMWARE_PROPOSAL",
    "FIRMWARE_SPEC",
    "INTERFACE",
    "command",
    "RUN_ID",
)


def test_the_scan_counts_and_writes_nothing(tmp_path: Path) -> None:
    record = tmp_path / "sessions" / "s" / "stdout.jsonl"
    record.parent.mkdir(parents=True)
    record.write_text('{"text": "Author: t <t@example.invalid>"}\n')
    before = seal(record.read_bytes())
    assert scan(tmp_path, "not-a-token")["emails_found"] == 1
    assert seal(record.read_bytes()) == before


def _driver(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["real_paired_reviewers.py", *argv])
    paired.main()


def test_an_address_in_a_stream_leaves_every_seal_for_the_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in POINTED:
        monkeypatch.setattr(base, name, getattr(base, name))
    # The real library, as the driver runs with: control and firmware and their rubrics.
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: base.REPO_ROOT)
    first = paired.FIRST_RUN_PARAMS
    # Not reportable: the test runs from whatever checkout it is in.
    monkeypatch.setattr(paired, "FIRST_RUN_PARAMS", lambda: {**first(), "reportable": False})
    criteria = tmp_path / "criteria.txt"
    criteria.write_text("criteria for a scripted run\n")
    python = str(Path(sys.base_prefix) / "bin" / "python3")
    out, baseline = tmp_path / "p", tmp_path / "g"
    _driver(
        monkeypatch,
        "paired",
        "--dry-run",
        "--criteria",
        str(criteria),
        "--out",
        str(out),
        "--role-python",
        python,
    )
    result = json.loads((out / "result.json").read_text())
    assert result["scan"]["emails_found"] >= 1
    assert result["reviews"]["all_pass"], result["reviews"]["checks"]
    events = read_events(out / paired.RUN_ID / "events.jsonl")
    ended = [e for e in events if isinstance(e, SessionEnded) and e.trajectory_seal]
    for session in ended:
        assert seal(Path(str(session.trajectory)).read_bytes()) == session.trajectory_seal
    written = paired.PLANTED_ADDRESS.encode()
    holding = [e for e in ended if written in Path(str(e.trajectory)).read_bytes()]
    assert holding  # the address is still in the sealed stream, as it was written
    _driver(
        monkeypatch,
        "generalist",
        "--dry-run",
        "--criteria",
        str(criteria),
        "--paired",
        str(out),
        "--out",
        str(baseline),
    )
    found = json.loads((baseline / "result.json").read_text())
    assert found["generalist_exit"] == 0, found
    assert found["baseline"]["token_ratio"]
