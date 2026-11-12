"""Claude Code's directory in a session's scratch home is out of the session's reach, whole.

A session's home is a scratch directory made for it, and its commands may write there. The one
place in it the binary treats as its own is ``.claude``: skills, mods, settings and commands a
user keeps are read from a directory of that name, and a later version may read more of it than
the measured ones do. So nothing of a session writes it or reads it: not a file tool, not a
command that names it, and not a sandboxed command that builds its name at run time (the OS
layer is told to deny it both ways). Where the OS layer does not run, nothing else stands
behind the hooks, so whatever appears there is moved aside at the next hook and that call is
refused. Where it runs, the layer denies the write, and the directory is not put back: the
runtime itself makes directories there before a shell command, on both pinned versions, as it
writes its configuration directory. The user settings file in it keeps its own root. The rest
of the home stays the session's own.

The home the installing user really has is not a scratch one: other sessions write its
``.claude`` all day, and it is left as it was (two named files, changes logged).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import SESSION, bash, event

from physgate.hooks import paths, sentinel, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.state import LOG_NAME
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "baseline", "reviewer", "orchestrator")
SHELL_PROFILES = ("role", "baseline", "orchestrator")


def _home(base: Path) -> Path:
    return base / "outside" / "home"


def _config(
    base: Path, profile: str = "role", home: Path | None = None, *, layer: bool = False
) -> SessionConfig:
    wt = base / "run" / "wt"
    wt.mkdir(parents=True, exist_ok=True)
    (home or _home(base)).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(wt),
        own_branch=None,
        store_root=str(base / "run" / "store"),
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(home or _home(base)),
        token_ceiling=40960,
        read_roots=(str(base / "run"),) if profile == "reviewer" else (),
        os_layer_temp_dir="/tmp/pg-1" if layer else None,
    )
    # Built as the spawner builds it, whose own home is another place; the hooks then run
    # with the scratch home as theirs (the fixture below), as a session's hooks do.
    with pytest.MonkeyPatch.context() as spawner:
        spawner.setenv("HOME", str(base / "the-spawner-s-home"))
        return build_config(request, current_installation())


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The request's base directory; a hook's own home is the session's scratch one."""
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv("HOME", str(_home(root)))
    return root


def _tool(config: SessionConfig, name: str, path: str) -> bool:
    key = "notebook_path" if name == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(cwd=config.worktree, tool_name=name, tool_input={key: path, "content": "x"})
    )
    return paths.pre_tool_use(hook_input, config).allow


def _shell(config: SessionConfig, command: str) -> bool:
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    return shell_paths.pre_tool_use(hook_input, config).allow


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(("layer", "watch"), [(False, "revert"), (True, "none")])
def test_the_directory_is_one_root_read_by_nothing_and_put_back_unless_the_os_layer_holds_it(
    base: Path, profile: str, layer: bool, watch: str
) -> None:
    # Without the OS layer nothing but the hooks stands between a script and the directory,
    # so what appears there is put back; with it, the layer denies the write and the runtime
    # makes its own directories there, which must not be taken for a session's.
    config = _config(base, profile, layer=layer)
    held = [
        (r.watch, r.reads, r.shell_writes, r.exceptions)
        for r in config.protected_roots
        if r.path == str(_home(base) / ".claude")
    ]
    assert held == [(watch, "denied", "denied", ())]


def _spellings(base: Path, config: SessionConfig) -> dict[str, str]:
    """One file in the directory, in each form a call could name it."""
    home = _home(base)
    (home / ".claude" / "skills" / "s").mkdir(parents=True, exist_ok=True)
    link = Path(config.worktree) / "elsewhere"
    if not link.is_symlink():
        link.symlink_to(home / ".claude")
    return {
        "absolute": str(home / ".claude" / "skills" / "s" / "SKILL.md"),
        "the directory itself": str(home / ".claude"),
        "a new entry at its top": str(home / ".claude" / "CLAUDE.md"),
        "with a tilde": "~/.claude/skills/s/SKILL.md",
        "through the parent": str(home / "work" / ".." / ".claude" / "skills" / "s" / "SKILL.md"),
        "through a link in the worktree": "elsewhere/skills/s/SKILL.md",
        "relative to the worktree": os.path.relpath(
            home / ".claude" / "settings.json", config.worktree
        ),
    }


@pytest.mark.parametrize("profile", PROFILES)
def test_no_file_tool_writes_or_reads_it_however_it_is_named(base: Path, profile: str) -> None:
    config = _config(base, profile)
    allowed = [
        (tool, form)
        for form, path in _spellings(base, config).items()
        for tool in ("Write", "Edit", "NotebookEdit", "Read")
        if _tool(config, tool, path)
    ]
    assert allowed == []


READERS = ("cat {p}", "ls -la {p}", "grep -r name {p}", "head -c 10 {p}", "diff {p} a.txt")
WRITERS = (
    "mkdir -p {p}",
    "echo x > {p}",
    "cp a.txt {p}",
    "tee {p} < a.txt",
    "ln -s {p} here",
    "rm -rf {p}",
    "python3 -c \"open('{p}', 'w').write('x')\"",
)


@pytest.mark.parametrize("profile", SHELL_PROFILES)
def test_no_command_that_names_it_runs_whether_it_writes_or_only_reads(
    base: Path, profile: str
) -> None:
    config = _config(base, profile)
    forms = _spellings(base, config) | {"with the variable": "$HOME/.claude/skills/s/SKILL.md"}
    allowed = [
        command
        for path in forms.values()
        for template in (*READERS, *WRITERS)
        # A tilde is the shell's to expand: inside a Python string it names a directory
        # called "~" beneath the worktree, which is the session's own.
        if not (path.startswith("~") and template.startswith("python3"))
        and _shell(config, command := template.format(p=path))
    ]
    assert allowed == []


@pytest.mark.parametrize("profile", ("role", "baseline"))
def test_the_os_layer_is_told_to_deny_it_both_ways(base: Path, profile: str) -> None:
    config = _config(base, profile)
    policy = sandbox_policy(config, home=str(_home(base)), temp_dir="/tmp/pg-1")
    filesystem: dict[str, Any] = policy.settings["sandbox"]["filesystem"]
    target = str(_home(base) / ".claude")
    assert target in filesystem["denyRead"]
    assert target in filesystem["denyWrite"]


def _check(config: SessionConfig, name: str) -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=config.worktree) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, config)
    return "allow" if decision.allow else decision.reason


#: What the runtime itself makes in a session's home before a shell command inside the OS
#: layer, with the modes it gives them (measured on macOS through the real binaries,
#: 12.11.2026); outside the layer neither version makes anything there.
RUNTIME_MADE = {
    "2.1.301": {".claude": 0o755, ".claude/bridge-spawn": 0o700},
    "2.1.322": {".claude": 0o700, ".claude/bridge-spawn": 0o700, ".claude/ssh": 0o700},
}


@pytest.mark.parametrize("version", sorted(RUNTIME_MADE))
def test_what_the_runtime_makes_there_inside_the_os_layer_refuses_no_call(
    base: Path, version: str
) -> None:
    config = _config(base, layer=True)
    assert _check(config, "SessionStart") == "allow"
    for relative, mode in RUNTIME_MADE[version].items():
        made = _home(base) / relative
        made.mkdir(mode=mode)
        made.chmod(mode)
    assert _check(config, "PostToolUse") == "allow"
    assert _check(config, "PreToolUse") == "allow"
    assert all((_home(base) / relative).is_dir() for relative in RUNTIME_MADE[version])
    log = base / "outside" / "state" / LOG_NAME
    assert not log.exists() or "put back" not in log.read_text()


def test_without_the_os_layer_what_a_script_left_there_is_seen_moved_aside_and_the_call_refused(
    base: Path,
) -> None:
    config = _config(base)
    assert _check(config, "SessionStart") == "allow"
    planted = _home(base) / ".claude" / "skills" / "s" / "SKILL.md"
    planted.parent.mkdir(parents=True)
    planted.write_text("---\nname: s\n---\n")
    ordinary = _home(base) / "notes.txt"
    ordinary.write_text("the session's own\n")
    reason = _check(config, "PostToolUse")
    assert reason != "allow" and str(_home(base) / ".claude") in reason
    assert not planted.exists() and not (_home(base) / ".claude").exists()
    assert ordinary.read_text() == "the session's own\n"
    log = base / "outside" / "state" / LOG_NAME
    events = [json.loads(line) for line in log.read_text().split("\n") if line]
    assert "put back" in [e["decision"] for e in events if e.get("session") == SESSION]
    # And again at the next call, should it be written again.
    planted.parent.mkdir(parents=True)
    planted.write_text("again\n")
    assert _check(config, "PreToolUse") != "allow"
    assert not planted.exists()


def test_the_user_settings_file_in_it_is_still_a_root_of_its_own_and_a_change_is_logged(
    base: Path,
) -> None:
    settings = _home(base) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n")
    config = _config(base, layer=True)
    assert [r.watch for r in config.protected_roots if r.path == str(settings)] == ["log"]
    assert _check(config, "SessionStart") == "allow"
    settings.write_text('{"disableAllHooks": true}\n')
    assert _check(config, "PostToolUse") == "allow"
    log = base / "outside" / "state" / LOG_NAME
    events = [json.loads(line) for line in log.read_text().split("\n") if line]
    assert [(e["decision"], e["paths"]) for e in events if e.get("session") == SESSION] == [
        ("changed", [str(settings)])
    ]


@pytest.mark.parametrize("profile", PROFILES)
def test_the_rest_of_the_home_stays_the_session_s_own(base: Path, profile: str) -> None:
    config = _config(base, profile)
    home = _home(base)
    beside = (
        home / "notes.txt",
        home / ".claudex" / "skills" / "s" / "SKILL.md",
        home / ".claude-old",
        home / "work" / ".claude" / "skills" / "s" / "SKILL.md",
        home / ".cache" / "tool" / "index",
    )
    refused = [str(p) for p in beside if not _tool(config, "Write", str(p))]
    assert refused == []
    if profile != "reviewer":
        # A reviewer reads by its allowance; for the others a read beside it is as before.
        assert [str(p) for p in beside if not _tool(config, "Read", str(p))] == []
        commands = [f"cat {p}" for p in beside] + [f"mkdir -p {p}" for p in beside]
        assert [c for c in commands if not _shell(config, c)] == []


def test_the_installing_user_s_own_home_is_left_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(os.path.realpath(tmp_path))
    own = root / "own-home"
    monkeypatch.setenv("HOME", str(own))
    own.mkdir()
    wt = root / "run" / "wt"
    wt.mkdir(parents=True)
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(wt),
        own_branch=None,
        store_root=str(root / "run" / "store"),
        state_dir=str(root / "outside" / "state"),
        target_dir=str(root / "outside" / "session"),
        claude_config_dir=str(root / "outside" / "config"),
        user_home=str(own),
        token_ceiling=40960,
    )
    config = build_config(request, current_installation())
    held = {r.path: r.watch for r in config.protected_roots if r.path.startswith(str(own))}
    assert held == {
        str(own / ".claude" / "settings.json"): "log",
        str(own / ".claude.json"): "log",
        str(own / ".gitconfig"): "revert",
        str(own / ".config" / "git"): "revert",
    }
