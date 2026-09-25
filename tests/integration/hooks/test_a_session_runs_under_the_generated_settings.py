"""The real Claude Code binary starts under the generated settings and runs every hook.

These run the pinned binary against the scripted API: real tool execution, real
hooks, no model and no token. Each asserts on two things at once, the hook
layer's own decision log and the bytes on disk, because a file that is absent
proves nothing about why.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from fake_messages_api import FakeMessagesApi, Recorded, Script, text, tool
from hook_session import (
    HarnessError,
    SessionRun,
    check_the_run_means_something,
    claude_binary,
    run_session,
)

from physgate.hooks import git_ops

pytestmark = pytest.mark.integration


def test_a_session_starts_and_each_event_runs_the_one_generated_command(tmp_path: Path) -> None:
    run = run_session(
        tmp_path,
        Script(main=[tool("Bash", command="echo ok > allowed.txt", description="x"), text("end")]),
    )
    assert run.exit_code == 0, run.stderr
    assert (run.worktree / "allowed.txt").read_text() == "ok\n"
    started = run.hook_commands_started()
    assert started["SessionStart:startup"] == 1
    assert started["PreToolUse:Bash"] == 1
    assert started["PostToolUse:Bash"] == 1
    assert run.hook_log == []
    assert not (run.worktree / ".claude").exists()


def test_a_forbidden_git_operation_is_refused_through_the_real_tool_path(tmp_path: Path) -> None:
    run = run_session(
        tmp_path,
        Script(
            main=[
                tool(
                    "Bash",
                    command="git push --force origin main; echo ran > marker.txt",
                    description="x",
                ),
                text("end"),
            ]
        ),
    )
    assert not (run.worktree / "marker.txt").exists()
    refusals = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert [(e["hook"], e["tool"], e["reason"]) for e in refusals] == [
        ("git_ops", "Bash", git_ops.FORCE_PUSH)
    ]
    assert git_ops.FORCE_PUSH in run.told_after(1)
    assert "trampoline" not in run.told_after(1), "the agent was shown the hook command line"


def test_the_harness_refuses_any_binary_but_the_pinned_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake))
    with pytest.raises(HarnessError, match="measured on 2.1.272"):
        claude_binary()


def test_a_session_that_never_reached_the_scripted_api_is_not_a_result(tmp_path: Path) -> None:
    # Nothing listens on port 9. The session fails to reach any API, the
    # scripted one serves nothing, and the harness says so instead of
    # reporting a pass that saw nothing.
    with pytest.raises(HarnessError, match="served nothing"):
        run_session(
            tmp_path,
            Script(main=[tool("Bash", command="echo x > x.txt", description="x")]),
            api_url_override="http://127.0.0.1:9",
        )


def _synthetic(tmp_path: Path, **recorded: object) -> SessionRun:
    api = FakeMessagesApi(Script(main=[]))
    fields: dict[str, object] = {
        "path": "/v1/messages",
        "carried_dummy_key": True,
        "carried_other_credential": False,
        "thread": "main",
        "tool_results": 0,
        "offered_tools": ("Bash",),
        "last_user": "go",
        "served": {"tool": "Bash", "input": {}},
    }
    fields.update(recorded)
    api.requests.append(Recorded(**fields))  # type: ignore[arg-type]
    started = [{"type": "system", "subtype": "hook_started", "hook_name": "PreToolUse:Bash"}]
    return SessionRun(0, api, started, [], None, tmp_path, "")  # type: ignore[arg-type]


def test_a_run_where_a_request_carried_another_credential_is_not_a_result(tmp_path: Path) -> None:
    with pytest.raises(HarnessError, match="credential"):
        check_the_run_means_something(_synthetic(tmp_path, carried_other_credential=True))
    check_the_run_means_something(_synthetic(tmp_path))


def test_a_run_where_a_hook_from_elsewhere_fired_is_not_a_result(tmp_path: Path) -> None:
    run = _synthetic(tmp_path)
    run.stream.append(dict(run.stream[0]))
    with pytest.raises(HarnessError, match="more hook commands"):
        check_the_run_means_something(run)
