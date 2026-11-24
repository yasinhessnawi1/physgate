"""A hook that fails names no path of the protected material in its refusal, its log or stderr.

Anything that escapes a hook becomes a refusal, so that Claude Code does not run the tool: the
refusal goes to the session, its line to the hook log and its text to stderr. What the refusal
says of the failure is its kind (the exception's class, and for an error of the system the name
of its errno), never the exception's own text: an ``OSError`` carries the file it met, and a held-
out file's path carries its task's id. A file it names is named as every refusal names it: a
path of the protected material by its label, any other path as it is.

The sentinel meets such a file where a held-out file cannot be read: at the session's first hook
(a fault no session causes under the OS layer), or after a command the session ran without the
OS layer changed its mode blindly (``find / … -exec chmod 000 {} +``), with no path in hand.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from hook_helpers import SESSION

from physgate.hooks import sentinel
from physgate.hooks.registry import REGISTRY
from physgate.hooks.runtime import main
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.state import LOG_NAME

TASK_ID = "control.held-out-stand-in-8d2e41"
FILE_NAME = "brief-4c9e0d.json"
BYTES = b'{"stand-in": "a held-out brief"}\n'
DIGEST = hashlib.sha256(BYTES).hexdigest()

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="a mode of 000 keeps nothing from root")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "heldout" / TASK_ID).mkdir(parents=True)
    (tmp_path / "heldout" / TASK_ID / FILE_NAME).write_bytes(BYTES)
    (tmp_path / "worktree" / ".claude").mkdir(parents=True)
    (tmp_path / "apart").mkdir(mode=0o700)
    (tmp_path / "apart").chmod(0o700)
    return tmp_path


@pytest.fixture(autouse=True)
def _readable_again(root: Path) -> object:
    """Every file made unreadable here is made readable again, so the directory can be removed."""
    yield None
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)


def _install(root: Path, *, apart: bool = True) -> tuple[str, str]:
    fields: dict[str, object] = {
        "profile": "role",
        "role": "electrical",
        "worktree": str(root / "worktree"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(root / "outside" / "state"),
        "target_dir": str(root / "outside" / "session"),
        "claude_config_dir": str(root / "outside" / "cfg"),
        "user_home": str(root / "outside" / "home"),
        "token_ceiling": 1000,
        "held_out": (str(root / "heldout"),),
    }
    if apart:
        fields["sentinel_apart"] = str(root / "apart")
    config = build_config(InstallRequest(**fields), installation())  # type: ignore[arg-type]
    data = config.model_dump_json().encode()
    path = root / "outside" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest()


def _hook(
    root: Path,
    installed: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
    event: str,
    *,
    hooks: str = "sentinel",
    command: str = "ls",
) -> tuple[int, str, str]:
    stdin = json.dumps(
        {
            "session_id": SESSION,
            "hook_event_name": event,
            "cwd": str(root / "worktree"),
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": "x"},
            "transcript_path": str(root / "t.jsonl"),
        }
    )
    path, sha = installed
    argv = [event, "--hooks", hooks, "--config", path, "--config-sha256", sha]
    code = main(argv, stdin, REGISTRY)
    out = capsys.readouterr()
    return code, out.out, out.err


def _reason(out: str) -> str:
    said = json.loads(out)
    return str(said.get("hookSpecificOutput", {}).get("permissionDecisionReason") or said["reason"])


def _log(root: Path) -> str:
    path = root / "outside" / "state" / LOG_NAME
    return path.read_text() if path.exists() else ""


def _named(root: Path, **seen: str) -> dict[str, list[str]]:
    """Where the protected material is, as each place the session or a reader sees names it."""
    needles = (str(root / "heldout"), TASK_ID, FILE_NAME, DIGEST)
    return {where: [n for n in needles if n in text] for where, text in seen.items()}


def _held_to_labels(root: Path, code: int, out: str, err: str) -> str:
    assert code == 2, f"the call was not refused: {code} {out}"
    seen = {"the refusal": out, "stderr": err, "the hook log": _log(root)}
    assert _named(root, **seen) == dict.fromkeys(seen, []), _named(root, **seen)
    return _reason(out)


@pytest.mark.parametrize("apart", [True, False], ids=["place-apart", "no-place-apart"])
def test_a_held_out_file_unreadable_at_the_first_hook_is_refused_with_no_path_named(
    root: Path, capsys: pytest.CaptureFixture[str], apart: bool
) -> None:
    installed = _install(root, apart=apart)
    target = root / "heldout" / TASK_ID / FILE_NAME
    target.chmod(0)
    reason = _held_to_labels(root, *_hook(root, installed, capsys, "PreToolUse"))
    # The kind of the failure, and the file it met by its label.
    assert "PermissionError" in reason and "EACCES" in reason, reason
    if apart:
        label = sentinel.label_of(str(target), "held-out", sentinel.label_key(str(root / "apart")))
        assert label in reason, reason
    else:
        assert "held-out entry " in reason and "(one-off key)" in reason, reason


def test_a_held_out_file_made_unreadable_after_the_start_is_refused_with_no_path_on_every_call(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    installed = _install(root)
    assert _hook(root, installed, capsys, "SessionStart")[0] == 0
    # What a command run blind does: no path in hand, every file it reaches made unreadable.
    target = root / "heldout" / TASK_ID / FILE_NAME
    target.chmod(0)
    label = sentinel.label_of(str(target), "held-out", sentinel.label_key(str(root / "apart")))
    for event in ("PostToolUse", "PreToolUse", "SessionEnd"):
        reason = _held_to_labels(root, *_hook(root, installed, capsys, event))
        assert "PermissionError" in reason and label in reason, f"{event}: {reason}"
    # The log line says the same as the refusal, and names the same label.
    lines = [json.loads(line) for line in _log(root).splitlines()]
    assert [line["decision"] for line in lines] == ["error"] * 3, lines
    assert all(label in line["reason"] for line in lines), lines


def test_a_blind_recursive_mode_change_teaches_the_session_no_protected_path_without_the_os_layer(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command every hook is asked about, then what each later hook says once it ran.

    Whether the hooks let the command run is not what this row holds (no hook reads a path
    out of ``find /``); what it holds is that the session learns no path of the protected
    material from anything it is told afterwards.
    """
    installed = _install(root)
    assert _hook(root, installed, capsys, "SessionStart")[0] == 0
    command = "find / -name '*.json' -perm -u+r -exec chmod 000 {} + 2>/dev/null"
    every = ",".join(sorted(REGISTRY))
    code, out, err = _hook(root, installed, capsys, "PreToolUse", hooks=every, command=command)
    seen = {"the answer to the command": out, "stderr": err, "the hook log": _log(root)}
    assert _named(root, **seen) == dict.fromkeys(seen, []), _named(root, **seen)
    # What the command does where it runs: every JSON file the session's user can read.
    for path in root.rglob("*.json"):
        path.chmod(0)
    for event in ("PostToolUse", "PreToolUse", "SessionEnd"):
        code, out, err = _hook(root, installed, capsys, event, hooks=every, command="ls")
        assert code == 2, f"{event}: a hook that could not decide let the call through"
        seen = {"the refusal": out, "stderr": err, "the hook log": _log(root)}
        assert _named(root, **seen) == dict.fromkeys(seen, []), (event, _named(root, **seen))


def test_a_failure_that_is_no_error_of_the_system_is_named_by_its_kind_alone(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``ValueError``'s text can quote what it was handed: only its class is said."""
    installed = _install(root)
    secret = str(root / "heldout" / TASK_ID / FILE_NAME)

    def raises(*_args: object) -> object:
        raise ValueError(secret)

    monkeypatch.setattr(sentinel, "_baseline", raises)
    reason = _held_to_labels(root, *_hook(root, installed, capsys, "PreToolUse"))
    assert "ValueError" in reason, reason
