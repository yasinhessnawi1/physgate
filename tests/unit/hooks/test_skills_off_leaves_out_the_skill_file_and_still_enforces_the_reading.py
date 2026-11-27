"""``skills: off``: the role's skill file is not there, and the reading rule still holds the rest.

A role session of an ablation run's ``skills: off`` arm is installed with what the dispatcher gives
it under that arm (the loader's reading for the switch): the cross standards file, the role's own
standards file and the module specification to read before it acts, and the two standards files
as its always-loaded set. Its worktree holds no skill file, since decomposition put none into the
run's target, so nothing is withheld for it.

The reading rule is not switched off with it: every call but a read is refused until the smaller
set is read, and a role whose standards file is missing is still refused. The token ceiling is
unchanged and is measured on the smaller set. Every other part of the installation, the hooks'
protected places and the OS layer's policy, is the same under both arms, under ``hooks: on`` and
under ``hooks: off``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import SESSION, bash, event

from physgate.hooks import reading, token_ceiling, withheld
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.knowledge import loader
from physgate.oslayer.policy import sandbox_policy

ROLE = "electrical"
SPEC = Path(".physgate/specs/e1.md")
CANARY = "ef" * 16

#: Sizes that put the two standards files under the ceiling and all three files over it.
CEILING = 1000
SIZES = {"cross/standards.md": 300, f"{ROLE}/standards.md": 300, f"{ROLE}/skill.md": 600}
#: What the session's configuration is told to read; everything else of it is the same per arm.
READING_FIELDS = ("required_reading", "always_loaded")


def _worktree(tmp: Path, skills: str) -> Path:
    """The session's worktree as the arm's specification commit checks it out."""
    worktree = tmp / "run" / "worktrees" / "e1"
    for name, size in SIZES.items():
        if skills == "off" and name.endswith(loader.SKILL_NAME):
            continue
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


def _config(tmp: Path, skills: str, hooks: str = "on") -> SessionConfig:
    """A role session installed with what the dispatcher gives it under ``skills``."""
    worktree = _worktree(tmp, skills)
    given = loader.session_reading(ROLE, SPEC, skills=skills)  # type: ignore[arg-type]
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
        withheld=(str(tmp / "run" / "run.json"),),
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
    assert token_ceiling.measure(off).allow, "the ceiling still counts the skill file"


def _spelled(data: Any, root: Path) -> Any:  # noqa: ANN401 - a configuration's own shape
    """``data`` with ``root`` written as one placeholder, so two runs' places compare."""
    if isinstance(data, dict):
        return {k: _spelled(v, root) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [_spelled(v, root) for v in data]
    if isinstance(data, str):
        return data.replace(str(root), "@")
    return data


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_the_hooks_are_installed_as_under_skills_on_but_for_what_is_read(
    base: Path, hooks: str
) -> None:
    on = _config(base / "on", "on", hooks).model_dump(mode="json")
    off = _config(base / "off", "off", hooks).model_dump(mode="json")
    for field in READING_FIELDS:
        on.pop(field)
        off.pop(field)
    assert _spelled(off, base / "off") == _spelled(on, base / "on"), (
        f"skills: off installs the hooks otherwise than on does (hooks: {hooks})"
    )


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_the_os_layer_s_policy_is_the_one_under_skills_on(base: Path, hooks: str) -> None:
    policies = []
    for arm in ("on", "off"):
        config = _config(base / arm, arm, hooks)
        home = str(base / arm / "outside" / "home")
        policy = sandbox_policy(config, home=home, temp_dir="/var/tmp/pgs/0123456789")
        policies.append(_spelled(policy.settings, base / arm))
    assert policies[1] == policies[0], f"skills: off changes the OS layer (hooks: {hooks})"


def test_nothing_is_withheld_for_the_skill_file_under_either_arm(base: Path) -> None:
    for arm in ("on", "off"):
        config = _config(base / arm, arm)
        assert _skill(config) not in withheld.roots_of(config), arm


def test_with_skills_on_the_skill_file_is_read_and_loaded_as_it_always_was(base: Path) -> None:
    config = _config(base, "on")
    assert _skill(config) in config.required_reading
    assert _skill(config) in config.always_loaded
    assert sorted(config.always_loaded) == sorted([*_standards(config), _skill(config)])
