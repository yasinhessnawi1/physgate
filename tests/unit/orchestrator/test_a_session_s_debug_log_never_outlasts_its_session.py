"""A role session's debug log never outlasts its session, whatever ends it.

On a pin whose sessions carry the catalog and flag traffic, each role session writes a debug log
into its configuration directory, beside its login, and the log may hold the credential. So it is
treated as the credential is: removed with it on every path, swept by name, never kept. It is read
only once the session's process group is confirmed gone, since a process still running could
write it again after it was read; when the stop is not confirmed the group is killed first, the
log is not read, and the resume's removal of every leftover session's credential takes whatever a
survivor wrote afterwards.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

import physgate.orchestrator.dispatch as dispatch
from physgate.orchestrator.credentials import (
    LOGIN_FILE,
    debug_logs_removed_on_failure,
    remove_secrets,
)
from physgate.orchestrator.dispatch import settle_debug_log
from physgate.orchestrator.exceptions import InvocationError

#: A log as 2.1.322 writes one at the scripted endpoint, with a credential in it.
LOG = "[servedCatalog] off (not_first_party)\nAuthorization: Bearer sk-ant-oat01-" + "Q" * 40 + "\n"


def _session(tmp_path: Path) -> tuple[Path, Path]:
    sdir = tmp_path / "sessions" / "s1"
    (sdir / "state").mkdir(parents=True)
    (sdir / "config").mkdir()
    (sdir / "config" / LOGIN_FILE).write_text("{}")
    (sdir / "config" / "debug.log").write_text(LOG)
    (sdir / "config" / "debug-1.txt").write_text(LOG)
    (sdir / "config" / "policy-limits.json").write_text("{}")
    return sdir / "state", sdir / "config"


def test_the_credential_s_removal_also_removes_every_debug_log_and_nothing_else(
    tmp_path: Path,
) -> None:
    state, config = _session(tmp_path)
    remove_secrets(state, config)
    assert sorted(p.name for p in config.iterdir()) == ["policy-limits.json"]


def test_a_failure_on_the_state_side_still_removes_the_log_and_the_login(tmp_path: Path) -> None:
    state, config = _session(tmp_path)
    state.rmdir()
    state.symlink_to(tmp_path)  # a link where the state directory was: refused, never followed
    with pytest.raises(InvocationError):
        remove_secrets(state, config)
    assert sorted(p.name for p in config.iterdir()) == ["policy-limits.json"]


def test_a_spawn_that_fails_leaves_no_debug_log(tmp_path: Path) -> None:
    _, config = _session(tmp_path)
    with pytest.raises(OSError, match="no such binary"), debug_logs_removed_on_failure(config):
        raise OSError("no such binary")
    assert not any(p.name.startswith("debug") for p in config.iterdir())
    assert (config / LOGIN_FILE).exists()  # only the logs: the login has its own removal


class _Process:
    pid = 4242
    returncode = None


def test_an_unconfirmed_stop_kills_the_group_first_and_reads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config = _session(tmp_path)
    killed: list[int] = []
    monkeypatch.setattr(dispatch, "kill_own", lambda p: killed.append(p.pid))
    process = cast("subprocess.Popen[bytes]", _Process())
    seen = settle_debug_log(process, confirmed=False, debug_file=config / "debug.log")
    assert seen is None and killed == [4242]


def test_a_log_rewritten_by_a_process_that_outlived_the_stop_goes_with_the_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, config = _session(tmp_path)
    monkeypatch.setattr(dispatch, "kill_own", lambda p: None)
    process = cast("subprocess.Popen[bytes]", _Process())
    settle_debug_log(process, confirmed=False, debug_file=config / "debug.log")
    (config / "debug.log").write_text(LOG)  # a survivor writes it again
    remove_secrets(state, config)  # as the session's end, and every resume, does
    assert not (config / "debug.log").exists()


def test_a_confirmed_stop_reads_the_log_once_keeps_no_credential_and_removes_it(
    tmp_path: Path,
) -> None:
    _, config = _session(tmp_path)
    process = cast("subprocess.Popen[bytes]", _Process())
    seen = settle_debug_log(process, confirmed=True, debug_file=config / "debug.log")
    assert seen is not None and seen.served_catalog_reason == "not_first_party"
    assert "sk-ant" not in seen.model_dump_json()
    assert not (config / "debug.log").exists()
