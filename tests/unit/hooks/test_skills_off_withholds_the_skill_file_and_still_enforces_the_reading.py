"""``skills: off``: the role's skill file is withheld, and the reading rule still holds the rest.

A role session of an ablation run's ``skills: off`` arm is installed with what the dispatcher gives
it under that arm (the loader's reading for the switch): the cross standards file, the role's own
standards file and the module specification to read before it acts, and the two standards files
as its always-loaded set. The role's skill file is in neither. It is withheld instead, as the run's
recorded configuration is: refused to every read of the file tools and of a shell command, denied
to every read in the OS layer, and held by the tripwire on the files no session reads.

The reading rule is not switched off with it: every call but a read is refused until the smaller
set is read, and a role whose standards file is missing is still refused. The token ceiling is
unchanged and is measured on the smaller set. Under ``hooks: off`` too the skill file stays
withheld: that arm drops what the session must read, not what it may not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import SESSION, bash, event

from physgate.hooks import paths, reading, shell_paths, token_ceiling, withheld
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.knowledge import loader
from physgate.oslayer.policy import sandbox_policy

ROLE = "electrical"
SPEC = Path(".physgate/specs/e1.md")
CANARY = "ef" * 16

#: Sizes that put the two standards files under the ceiling and all three files over it.
CEILING = 1000
SIZES = {"cross/standards.md": 300, f"{ROLE}/standards.md": 300, f"{ROLE}/skill.md": 600}


def _worktree(tmp: Path) -> Path:
    worktree = tmp / "run" / "worktrees" / "e1"
    for name, size in SIZES.items():
        path = worktree / "knowledge" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = CANARY + "\n" if name.endswith("skill.md") else ""
        path.write_text(body + "a line\n" * ((size - len(body)) // 7))
    (worktree / SPEC).parent.mkdir(parents=True, exist_ok=True)
    (worktree / SPEC).write_text("the module\n")
    (tmp / "run" / "run.json").write_text("{}\n")
    for d in ("state", "session", "config", "home"):
        (tmp / "outside" / d).mkdir(parents=True, exist_ok=True)
    return worktree


def _given(skills: str) -> Any:  # noqa: ANN401 - what a role session is given to read
    session_reading = getattr(loader, "session_reading", None)
    assert session_reading is not None, "the loader names no session's reading by the skills switch"
    return session_reading(ROLE, SPEC, skills=skills)


def _config(tmp: Path, skills: str, hooks: str = "on") -> SessionConfig:
    """A role session installed with what the dispatcher gives it under ``skills``."""
    worktree = _worktree(tmp)
    given = _given(skills)
    request = InstallRequest(
        profile="role",
        role=ROLE,
        worktree=str(worktree),
        own_branch="subtask/e1",
        store_root=str(tmp / "run" / "store"),
        state_dir=str(tmp / "outside" / "state"),
        target_dir=str(tmp / "outside" / "session"),
        claude_config_dir=str(tmp / "outside" / "config"),
        user_home=str(tmp / "outside" / "home"),
        token_ceiling=CEILING,
        required_reading=tuple(str(worktree / p) for p in given.required),
        always_loaded=tuple(str(worktree / p) for p in given.always_loaded),
        withheld=(str(tmp / "run" / "run.json"), *(str(worktree / p) for p in given.withheld)),
        hooks=hooks,  # type: ignore[arg-type]
    )
    return build_config(request, current_installation())


def _skill(config: SessionConfig) -> str:
    return str(Path(config.worktree) / "knowledge" / ROLE / "skill.md")


def _standards(config: SessionConfig) -> list[str]:
    knowledge = Path(config.worktree) / "knowledge"
    return [str(knowledge / "cross" / "standards.md"), str(knowledge / ROLE / "standards.md")]


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


def test_what_the_session_must_read_lacks_the_skill_file_and_keeps_both_standards_files(
    base: Path,
) -> None:
    config = _config(base, "off")
    spec = str(Path(config.worktree) / SPEC)
    assert _skill(config) not in config.required_reading, "the skill file is still required"
    assert _skill(config) not in config.always_loaded, "the skill file is still always loaded"
    assert sorted(config.required_reading) == sorted([*_standards(config), spec])
    assert list(config.always_loaded) == _standards(config)


def _bash(config: SessionConfig) -> HookInput:
    return HookInput.model_validate(bash("ls", cwd=config.worktree, session_id=SESSION))


def _read_in_full(config: SessionConfig, path: str) -> None:
    lines = reading.content_lines(Path(path).read_bytes())
    done = HookInput.model_validate(
        event(
            "PostToolUse",
            tool_name="Read",
            tool_input={"file_path": path},
            tool_response={
                "type": "text",
                "file": {
                    "filePath": path,
                    "content": "...",
                    "numLines": lines,
                    "startLine": 1,
                    "totalLines": lines,
                },
            },
        )
    )
    assert reading.post_tool_use(done, config).allow


def test_the_reading_rule_refuses_every_call_until_the_smaller_set_is_read(base: Path) -> None:
    config = _config(base, "off")
    first = reading.pre_tool_use(_bash(config), config)
    assert not first.allow, "skills: off let a call through before the standards were read"
    for path in _standards(config):
        assert path in first.reason
    assert _skill(config) not in first.reason
    _read_in_full(config, _standards(config)[0])
    second = reading.pre_tool_use(_bash(config), config)
    assert not second.allow, "skills: off let a call through with a standards file unread"
    assert _standards(config)[1] in second.reason
    _read_in_full(config, _standards(config)[1])
    _read_in_full(config, str(Path(config.worktree) / SPEC))
    # Read in full, without the skill file: the session acts.
    assert reading.pre_tool_use(_bash(config), config).allow


def test_a_role_whose_standards_file_is_missing_is_still_refused(base: Path) -> None:
    config = _config(base, "off")
    Path(_standards(config)[1]).unlink()
    decision = reading.pre_tool_use(_bash(config), config)
    assert not decision.allow, "skills: off let a role with no standards file act"
    assert f"{_standards(config)[1]} (cannot be read" in decision.reason


def test_the_ceiling_is_measured_on_the_two_standards_files(base: Path) -> None:
    on = _config(base / "on", "on")
    off = _config(base / "off", "off")
    assert on.token_ceiling == off.token_ceiling == CEILING
    # The same files and the same ceiling: over it with the skill file, under it without.
    assert not token_ceiling.measure(on).allow
    assert token_ceiling.measure(off).allow, "the ceiling still counts the withheld skill file"


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_a_file_tool_neither_reads_nor_writes_the_skill_file(base: Path, hooks: str) -> None:
    config = _config(base, "off", hooks)
    read = paths.protection(_skill(config), config.worktree, config, writing=False)
    assert read is not None, f"a file tool reads the withheld skill file (hooks: {hooks})"
    relative = f"knowledge/{ROLE}/skill.md"
    assert paths.protection(relative, config.worktree, config, writing=False) is not None
    assert paths.protection(_skill(config), config.worktree, config, writing=True) is not None


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_a_shell_command_does_not_read_the_skill_file(base: Path, hooks: str) -> None:
    config = _config(base, "off", hooks)
    for command in (
        f"cat {_skill(config)}",
        f"head -c 99 knowledge/{ROLE}/skill.md",
        f"grep -r line knowledge/{ROLE}/skill.md",
        f"python3 -c \"print(open('knowledge/{ROLE}/skill.md').read())\"",
        f'cat <<< "knowledge/{ROLE}/skill.md"',
    ):
        said = shell_paths.check(parse(command)[0], config.worktree, config)
        assert said is not None, f"a shell command reads the withheld skill file: {command}"


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_the_os_layer_denies_every_read_of_the_skill_file(base: Path, hooks: str) -> None:
    config = _config(base, "off", hooks)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-sk")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    skill = _skill(config)
    assert any(skill == d or skill.startswith(d.rstrip("/") + "/") for d in deny), (
        "the OS layer lets a shell command read the withheld skill file"
    )


def test_the_tripwire_holds_the_skill_file_to_one_name(base: Path) -> None:
    config = _config(base, "off")
    assert _skill(config) in withheld.roots_of(config), "the tripwire does not hold the skill file"


def test_with_skills_on_the_skill_file_is_read_and_loaded_as_it_always_was(base: Path) -> None:
    config = _config(base, "on")
    assert _skill(config) in config.required_reading
    assert _skill(config) in config.always_loaded
    assert paths.protection(_skill(config), config.worktree, config, writing=False) is None
    assert _skill(config) not in withheld.roots_of(config)
    # Its writes stay refused, as the knowledge tree's always were.
    assert paths.protection(_skill(config), config.worktree, config, writing=True) is not None
