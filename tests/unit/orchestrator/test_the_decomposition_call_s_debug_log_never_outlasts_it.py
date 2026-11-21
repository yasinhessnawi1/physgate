"""The decomposition call's debug log is read only after a normal end, and never outlasts the call.

The call writes a debug log in its own directory, which may hold the credential it ran with. It
is read for the catalog and flags only when the call ended on its own: a call stopped at its
wall clock may have left a process that writes it again, so nothing of it is read then. Every
file named like the log is removed with the credential whichever way the call ended, a failure
to start included; the log's place is the one it always had, so the call's argv is unchanged.

The binary is a stand-in that writes its log (and a second file named like it), then exits or
outlives its clock.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.managed import ObservedTraffic

STANDIN = r"""
import sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.301 (Claude Code)")
    sys.exit(0)
log = args[args.index("--debug-file") + 1]
for path in (log, log + ".1"):
    with open(path, "w") as out:
        out.write("[servedCatalog] off (essential_traffic)\nGrowthBook is off for this session\n")
if "hang" in sys.argv[0]:
    time.sleep(60)
sys.exit(0)
"""


def _binary(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{STANDIN}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binary: Path) -> decompose.Outcome:
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(binary))
    bounds = SCRIPTED_BOUNDS.model_copy(update={"session_wall_clock_s": 3.0})
    return decompose.call(
        "brief",
        config=make_config(claude_version="2.1.301", bounds=bounds),
        workdir=tmp_path / "w",
        base_url=None,
        credential=Credential("api_key", "not-a-key"),
    )


def _logs(workdir: Path) -> list[str]:
    return sorted(p.name for p in workdir.iterdir() if p.name.startswith("debug"))


def test_after_a_normal_end_the_log_is_read_and_every_file_named_like_it_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _call(tmp_path, monkeypatch, _binary(tmp_path, "claude"))
    assert outcome.observed_traffic == ObservedTraffic(
        served_catalog="off", served_catalog_reason="essential_traffic", feature_flags="off"
    )
    assert _logs(tmp_path / "w") == []


def test_a_call_stopped_at_its_clock_reads_nothing_of_its_log_and_leaves_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _call(tmp_path, monkeypatch, _binary(tmp_path, "claude-hang"))
    assert not outcome.ok
    assert outcome.observed_traffic is None
    assert outcome.cause != "managed_settings_changed"  # the clock is the cause, not a reading
    assert _logs(tmp_path / "w") == []


def test_a_call_that_never_started_leaves_no_file_named_like_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / "w"
    workdir.mkdir()
    for name in ("debug.log", "debug.log.1"):  # what an earlier attempt in the directory left
        (workdir / name).write_text("a line that may hold the credential\n")
    missing = tmp_path / "bin" / "not-there"
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.301")
    with pytest.raises(OSError):  # noqa: PT011 - whichever error the failed start raises
        _call(tmp_path, monkeypatch, missing)
    assert _logs(workdir) == []
