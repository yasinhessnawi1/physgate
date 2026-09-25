"""Through the real binary: the second layer catches what the first did not see.

Criterion 7 first: with the shell layer not wired at all, a heredoc into the
gate runs, and the sentinel alone puts the gate back and reports the call as
failed. Then, with every layer wired, the forms the shell layer deliberately
leaves alone: each runs, and each is put back.

Every case writes a marker outside the gate in the same command, which proves
the command really ran; a gate left unchanged by a command that never ran
would prove nothing about the sentinel.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import sentinel
from physgate.hooks.registry import REGISTRY

pytestmark = pytest.mark.integration

FILES = {"README.md": "a worktree\n", "src/physgate/gate/check.py": "CHECK = True\n"}
GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _payloads(worktree: Path) -> None:
    """A tar and a patch that each rewrite the gate, made before the session starts."""
    data = b"CHECK = False\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("src/physgate/gate/check.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (worktree / "payload.tar").write_bytes(buffer.getvalue())
    gate = worktree / "src" / "physgate" / "gate" / "check.py"
    gate.write_text("CHECK = False\n")
    diff = subprocess.run(
        ["git", "diff"], cwd=worktree, env=GIT_ENV, capture_output=True, text=True, check=True
    )
    (worktree / "payload.patch").write_text(diff.stdout)
    gate.write_text("CHECK = True\n")


def _run(root: Path, command: str, *, parser: bool = True) -> SessionRun:
    registry = REGISTRY if parser else {k: v for k, v in REGISTRY.items() if k != "shell_paths"}
    return run_session(
        root,
        Script(main=[tool("Bash", command=command, description="x"), text("end")]),
        files=FILES,
        prepare=_payloads,
        registry=registry,
    )


def _assert_put_back_by_the_sentinel(run: SessionRun) -> None:
    assert (run.worktree / "ran.txt").read_text() == "ran\n", "the command did not run"
    gate = run.worktree / "src" / "physgate" / "gate"
    assert sorted(p.name for p in gate.iterdir()) == ["check.py"]
    assert (gate / "check.py").read_text() == "CHECK = True\n"
    events = [e for e in run.hook_log if e.get("hook") == "sentinel"]
    # The sentinel's own record of what it put back, then the dispatcher's
    # record of the refusal it returned: one of each.
    assert [e["decision"] for e in events] == ["put back", "refuse"], run.hook_log
    assert any(str(p).endswith("gate/check.py") for p in events[0]["paths"])
    assert [e for e in run.hook_log if e.get("hook") == "shell_paths"] == []
    assert "put back" in run.told_after(1)


def test_with_the_parser_off_the_sentinel_alone_puts_back_a_heredoc_into_the_gate(
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        "cat > src/physgate/gate/check.py <<'EOF'\nCHECK = False\nEOF\necho ran > ran.txt",
        parser=False,
    )
    _assert_put_back_by_the_sentinel(run)
    started = run.hook_commands_started()
    assert started["PostToolUse:Bash"] == 1


@pytest.mark.parametrize(
    "command",
    [
        "d=ga; echo 'CHECK = False' > src/physgate/${d}te/check.py; echo ran > ran.txt",
        "echo 'CHECK = False' > $(printf src/physgate/ga)te/check.py; echo ran > ran.txt",
        "python3 -c \"import os; open(os.path.join('src','physgate','ga'+'te','check.py'),'w')"
        ".write('CHECK = False')\"; echo ran > ran.txt",
        "tar -xf payload.tar; echo ran > ran.txt",
        "git apply payload.patch; echo ran > ran.txt",
    ],
    ids=["variable", "substitution", "string-built-path", "archive", "patch"],
)
def test_what_the_shell_layer_leaves_alone_the_sentinel_puts_back(
    tmp_path: Path, command: str
) -> None:
    _assert_put_back_by_the_sentinel(_run(tmp_path, command))


def test_a_write_by_a_command_that_then_fails_is_put_back(tmp_path: Path) -> None:
    # A failing command fires only the failure event, so this is the case a
    # sentinel wired to the ordinary after-call event alone would miss.
    run = _run(tmp_path, "tar -xf payload.tar; echo ran > ran.txt; false")
    _assert_put_back_by_the_sentinel(run)
    assert run.hook_commands_started()["PostToolUseFailure:Bash"] == 1


def test_the_sentinel_reason_is_the_one_the_agent_reads(tmp_path: Path) -> None:
    run = _run(tmp_path, "tar -xf payload.tar; echo ran > ran.txt")
    assert sentinel.PUT_BACK.split("{paths}")[0] in run.told_after(1)
