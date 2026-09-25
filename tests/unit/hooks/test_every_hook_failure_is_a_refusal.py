"""A hook that cannot decide refuses, because Claude Code would otherwise run the tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from hook_helpers import SESSION, bash, event, write_config

from physgate.hooks import __main__ as entry
from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, dispatch, main, refuse
from physgate.hooks.state import LOG_NAME


def _raises(_: HookInput, __: SessionConfig) -> Decision:
    msg = "boom"
    raise RuntimeError(msg)


def _allows(_: HookInput, __: SessionConfig) -> Decision:
    return ALLOW


def _refuses_a(_: HookInput, __: SessionConfig) -> Decision:
    return refuse("reason a")


def _refuses_b(_: HookInput, __: SessionConfig) -> Decision:
    return refuse("reason b")


REG = {
    "raises": HookSpec("raises", {"PreToolUse": _raises}),
    "allows": HookSpec("allows", {"PreToolUse": _allows, "PostToolUse": _allows}),
    "a": HookSpec("a", {"PreToolUse": _refuses_a, "PostToolUse": _refuses_a}),
    "b": HookSpec("b", {"PreToolUse": _refuses_b}),
}


def _argv(path: Path, sha: str, hooks: str, ev: str = "PreToolUse") -> list[str]:
    return [ev, "--hooks", hooks, "--config", str(path), "--config-sha256", sha]


def _run(capsys: pytest.CaptureFixture[str], argv: list[str], stdin: str) -> tuple[int, str, str]:
    rc = main(argv, stdin, REG)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_a_handler_that_raises_refuses_the_call_with_the_error_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, sha, _ = write_config(tmp_path)
    rc, out, _ = _run(capsys, _argv(path, sha, "raises"), json.dumps(bash("ls")))
    assert rc == 2
    reason = json.loads(out)["hookSpecificOutput"]
    assert reason["permissionDecision"] == "deny"
    assert "RuntimeError: boom" in reason["permissionDecisionReason"]


def test_an_allowing_handler_exits_zero_and_says_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, sha, _ = write_config(tmp_path)
    rc, out, err = _run(capsys, _argv(path, sha, "allows"), json.dumps(bash("ls")))
    assert (rc, out, err) == (0, "", "")


@pytest.mark.parametrize(
    "argv_fault",
    ["no-arguments", "unknown-event", "unknown-hook", "missing-sha-flag"],
)
def test_a_malformed_command_line_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv_fault: str
) -> None:
    path, sha, _ = write_config(tmp_path)
    argv = {
        "no-arguments": [],
        "unknown-event": _argv(path, sha, "allows", ev="PreCompact"),
        "unknown-hook": _argv(path, sha, "no-such-hook"),
        "missing-sha-flag": _argv(path, sha, "allows")[:5] + ["--sha", sha],
    }[argv_fault]
    rc, out, _ = _run(capsys, argv, json.dumps(bash("ls")))
    assert rc == 2
    assert "could not reach a decision" in out


def test_a_configuration_changed_after_the_spawn_refuses_every_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, sha, _ = write_config(tmp_path)
    path.write_bytes(path.read_bytes().replace(b'"role"', b'"orchestrator"', 1))
    rc, out, _ = _run(capsys, _argv(path, sha, "allows"), json.dumps(bash("ls")))
    assert rc == 2
    assert "SessionConfigMismatchError" in out


@pytest.mark.parametrize("stdin", ["", "not json", "{}", json.dumps(event(session_id="../x"))])
def test_an_event_description_that_does_not_validate_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], stdin: str
) -> None:
    path, sha, _ = write_config(tmp_path)
    rc, _, _ = _run(capsys, _argv(path, sha, "allows"), stdin)
    assert rc == 2


def test_an_event_other_than_the_one_wired_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, sha, _ = write_config(tmp_path)
    rc, _, _ = _run(capsys, _argv(path, sha, "allows"), json.dumps(event("PostToolUse")))
    assert rc == 2


def test_every_refusal_is_logged_and_the_first_is_the_one_returned(tmp_path: Path) -> None:
    _, _, config = write_config(tmp_path)
    decision = dispatch(
        [REG["allows"], REG["a"], REG["b"]], HookInput.model_validate(bash("ls")), config
    )
    assert decision == refuse("reason a")
    lines = [json.loads(x) for x in (tmp_path / "state" / LOG_NAME).read_text().splitlines()]
    assert [(x["hook"], x["reason"], x["session"]) for x in lines] == [
        ("a", "reason a", SESSION),
        ("b", "reason b", SESSION),
    ]


def test_a_refusal_after_the_call_is_reported_as_a_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, sha, _ = write_config(tmp_path)
    post = event("PostToolUse", tool_name="Bash", tool_input={"command": "ls"})
    rc, out, _ = _run(capsys, _argv(path, sha, "a", ev="PostToolUse"), json.dumps(post))
    assert rc == 2
    assert json.loads(out) == {"decision": "block", "reason": "reason a"}


def test_a_package_that_fails_to_import_refuses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "physgate.hooks.registry", None)
    monkeypatch.setattr(sys, "stdin", open("/dev/null"))  # noqa: SIM115 - closed by pytest
    assert entry._run() == 2
    assert "could not load" in capsys.readouterr().err


def test_the_module_entry_point_refuses_through_a_real_interpreter(tmp_path: Path) -> None:
    path, sha, _ = write_config(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-I", "-m", "physgate.hooks", *_argv(path, sha, "no-such-hook")],
        input=json.dumps(bash("ls")),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
