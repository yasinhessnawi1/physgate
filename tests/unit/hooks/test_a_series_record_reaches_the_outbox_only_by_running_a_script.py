"""A series record reaches the outbox only by running a script, never through a tool or a command.

Every refused form is the visible one a hook can judge before it runs: a tool's write, an
output redirection, or a command that is not a reader naming the outbox. The allowed forms
are the one a record comes by (running a script that names no part of the outbox) and
reading it. A ``cd`` is followed, so a relative path after one is judged where it lands.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import series
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    _, _, cfg = write_config(tmp_path, role="control")
    return cfg


def _tool(config: SessionConfig, tool: str, path: str) -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(
            tool_name=tool,
            cwd=config.worktree,
            tool_input={key: path, "content": "{}", "old_string": "a", "new_string": "b"},
        )
    )
    decision = series.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _bash(config: SessionConfig, command: str) -> str:
    decision = series.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=config.worktree)), config
    )
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize(
    "path", [".physgate/series/step.json", "{w}/.physgate/series/step.json", ".physgate/series"]
)
def test_no_tool_writes_into_the_outbox(config: SessionConfig, tool: str, path: str) -> None:
    spelled = path.format(w=config.worktree)
    if not os.path.isabs(spelled):
        spelled = os.path.join(config.worktree, spelled)
    assert "only by running the script" in _tool(config, tool, spelled)


def test_no_tool_writes_the_directory_above_the_outbox_either(config: SessionConfig) -> None:
    assert _tool(config, "Write", os.path.join(config.worktree, ".physgate")) != "allow"


def test_a_tool_may_write_the_module_and_the_proposals(config: SessionConfig) -> None:
    for relative in ("modules/control/sim.py", ".physgate/proposals/control.loop.json"):
        assert _tool(config, "Write", os.path.join(config.worktree, relative)) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "echo '{}' > .physgate/series/step.json",
        "echo '{}' >> .physgate/series/step.json",
        "cat > .physgate/series/step.json <<'EOF'\n{}\nEOF\n",
        "cp results.json .physgate/series/step.json",
        "mv results.json .physgate/series/",
        "echo '{}' | tee .physgate/series/step.json",
        "python3 -c \"open('.physgate/series/step.json','w').write('{}')\"",
        "cd .physgate && echo '{}' > series/step.json",
        "cd .physgate/series && touch step.json",
        "rm -rf .physgate",
        "ln -s /tmp/elsewhere .physgate/series",
        "echo '{}' > ./.physgate//series/../series/step.json",
        "echo '{}' > .PHYSGATE/SERIES/step.json",
    ],
)
def test_a_command_that_writes_or_names_the_outbox_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert "names the series outbox" in _bash(config, command)


@pytest.mark.parametrize(
    "command",
    [
        "python3 modules/control/sim.py",
        "cd modules/control && python3 sim.py",
        "cat .physgate/series/step.json",
        "ls -la .physgate/series",
        "grep -c step .physgate/series/step.json",
        "echo done",
        "python3 -c 'print(1)' > modules/control/out.txt",
    ],
)
def test_running_a_script_and_reading_the_outbox_are_allowed(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) == "allow"


def test_a_command_that_cannot_be_split_is_refused(config: SessionConfig) -> None:
    assert "could not be split" in _bash(config, "echo 'unterminated")


def test_the_writer_s_directory_is_a_protected_root_put_back_for_every_session(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch="b",
        store_root=None,
        state_dir=str(tmp_path / "state"),
        target_dir=str(tmp_path / "target"),
        claude_config_dir=str(tmp_path / "config"),
        user_home=str(tmp_path / "home"),
        token_ceiling=40960,
    )
    built = build_config(request, current_installation())
    roots = {r.path: r for r in built.protected_roots}
    lib = roots[str(worktree / ".physgate" / "lib")]
    assert lib.watch == "revert"
    assert "series writer" in lib.reason
