"""The raw arm's credential: the role path's code, and never anywhere the session can keep it.

An inert dummy token stands in for the credential throughout; no real one is used.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.task import parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import Absent

DUMMY = "inert-dummy-token-not-a-credential-0123456789"
BOUNDS = RunBounds(
    binary_max_retries=0, session_wall_clock_s=30.0, session_max_turns=5, infra_retry_delays_s=()
)
TASK = parse_task(json.dumps(own_task()).encode())


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o700)
    return path


def _fake_install(tmp_path: Path) -> Path:
    """An installer that writes a settings file whose only end check is ``true``."""
    settings = tmp_path / "fake-settings.json"
    settings.write_text(
        json.dumps({"hooks": {"SessionEnd": [{"hooks": [{"command": "true", "timeout": 5}]}]}})
    )
    out = {"settings": str(settings), "config": "c", "spawn_args": [], "spawn_env": {}}
    return _script(tmp_path / "install-bin", f"echo '{json.dumps(out)}'\n")


def _setup(tmp_path: Path, binary: Path, mode: str = "subscription") -> raw.RawSetup:
    return raw.RawSetup(
        binary=str(binary),
        claude_version="2.1.301",
        model="claude-opus-5-5",
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        bounds=BOUNDS,
        credential=Credential(mode=mode, secret=DUMMY),  # type: ignore[arg-type]
        base_url=None,
        install_bin=_fake_install(tmp_path),
        role_python=None,
        held_out=(),
        held_out_canaries=(),
        network="open",
        os_layer=Absent(reason="test", no_os_protection=False),
    )


def _holders(root: Path) -> list[str]:
    return [str(p) for p in root.rglob("*") if p.is_file() and DUMMY.encode() in p.read_bytes()]


#: A session that does everything a session could with its credential: reads the login and
#: the key helper, and prints both to its stream and its error output.
LEAKY = (
    'cat "$CLAUDE_CONFIG_DIR/.credentials.json" 2>/dev/null\n'
    'cat "$CLAUDE_CONFIG_DIR/.credentials.json" >&2 2>/dev/null\n'
    'echo "$@" > argv.txt\n'
    'echo \'{"type":"result","subtype":"success","usage":{}}\'\n'
)


@pytest.mark.parametrize("mode", ["subscription", "api_key"])
def test_after_the_session_no_file_holds_the_credential(tmp_path: Path, mode: str) -> None:
    binary = _script(tmp_path / "claude", LEAKY)
    work = tmp_path / "work"
    raw.run_raw(TASK, _setup(tmp_path, binary, mode), work, cap=10**9)
    assert _holders(work) == []
    assert DUMMY not in (work / "worktree" / "argv.txt").read_text()


def test_a_session_whose_end_fails_leaves_no_credential_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _script(tmp_path / "claude", LEAKY)

    def failing(*_a: object, **_k: object) -> object:
        raise RuntimeError("the process table could not be read")

    monkeypatch.setattr(raw, "await_session", failing)
    work = tmp_path / "work"
    with pytest.raises(RuntimeError):
        raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    assert _holders(work) == []


def test_the_session_s_own_directories_are_private(tmp_path: Path) -> None:
    binary = _script(tmp_path / "claude", LEAKY)
    work = tmp_path / "work"
    raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    for directory in (
        work,
        work / "session",
        work / "session" / "config",
        work / "session" / "state",
    ):
        assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0, directory


def test_the_raw_session_s_shell_is_denied_its_credential_files_by_the_os_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    from physgate.hooks.cli import add_parser

    seen: list[list[str]] = []

    def capture(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", capture)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    sdir = tmp_path / "session"
    raw._install(
        _setup(tmp_path, tmp_path / "claude"), worktree, sdir, Path("/tmp/pg-0123456789ab")
    )
    monkeypatch.undo()
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(seen[0][1:])
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    deny_read = json.loads(Path(printed["settings"]).read_text())["sandbox"]["filesystem"][
        "denyRead"
    ]
    for secret_place in (sdir / "config", sdir / "state"):
        assert any(Path(secret_place).is_relative_to(Path(d)) for d in deny_read), secret_place
    assert DUMMY not in " ".join(seen[0])


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("session_end_command", RuntimeError("the settings could not be read")),
        ("spawn_held", OSError("the process could not be started")),
        ("await_session", KeyboardInterrupt()),
    ],
    ids=["before the spawn", "at the spawn", "killed while it runs"],
)
def test_the_credential_is_removed_on_every_path_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, error: BaseException
) -> None:
    binary = _script(tmp_path / "claude", LEAKY)

    def failing(*_a: object, **_k: object) -> object:
        raise error

    monkeypatch.setattr(raw, step, failing)
    work = tmp_path / "work"
    with pytest.raises(type(error)):
        raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    assert _holders(work) == []


def test_a_cleanup_that_fails_is_recorded_and_refuses_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.orchestrator.exceptions import InvocationError

    binary = _script(tmp_path / "claude", LEAKY)

    def cannot(*_a: object, **_k: object) -> None:
        raise InvocationError("a directory on the way is a link")

    monkeypatch.setattr(raw, "remove_secrets", cannot)
    work = tmp_path / "work"
    with pytest.raises(raw.RawArmError, match="credential"):
        raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    record = json.loads((work / "cleanup.json").read_text())
    assert "a directory on the way is a link" in record["error"]
    assert DUMMY not in (work / "cleanup.json").read_text()
    assert not (work / "raw.json").exists()
