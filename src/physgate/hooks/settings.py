"""Generate a session's settings file and configuration, and nothing else.

The installed files are generated, never edited by hand, and a second run with
the same request writes the same bytes.

**Where the files go, and why.** Both files are written to a directory outside
the session's worktree, and the session is started with
``--setting-sources ""`` and ``--settings <that file>``. Measured on the pinned
Claude Code: when any settings file inside the worktree is loaded, one write of
``disableAllHooks`` into it switches every hook off for the rest of the session,
and an ``env`` block written the same way changes what every hook sees. With no
worktree settings loaded and the hooks in a file passed by flag, neither write
changes anything, and the flag file itself is not re-read when edited.

**Where the hook code runs from.** The interpreter and the package the hook
commands name belong to an installation outside every worktree, and both are
protected paths, together with the settings directory, the state directory, the
session's Claude configuration directory and the user-level Claude settings. A
role that could edit the code judging it, or the files telling that code who the
session is, would not be judged at all.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

import physgate
from physgate.hooks.config import (
    AbsolutePath,
    ExperimentRule,
    Installation,
    Profile,
    ProtectedRoot,
    SessionConfig,
    Watch,
    digest,
)
from physgate.hooks.reasons import GATE_REASON as GATE_REASON
from physgate.hooks.reasons import HELD_OUT_REASON as HELD_OUT_REASON
from physgate.hooks.reasons import STORE_REASON as STORE_REASON
from physgate.hooks.runtime import EVENTS, HookSpec

WATCHDOG_SECONDS = 5
HOOK_TIMEOUT_SECONDS = 30
SETTINGS_NAME = "settings.json"
CONFIG_NAME = "session-config.json"

#: The tools each profile may call. A closed list, so a tool this version of
#: Claude Code does not have yet is refused rather than missed. Opening one is a
#: decision with a test, never a default.
_TASK_LIST = ("TaskCreate", "TaskGet", "TaskList", "TaskUpdate")
PROFILE_TOOLS: Mapping[Profile, tuple[str, ...]] = {
    "role": ("Bash", "Edit", "NotebookEdit", "Read", "Write", *_TASK_LIST),
    "reviewer": ("Read", *_TASK_LIST),
    "orchestrator": ("Bash", "Edit", "NotebookEdit", "Read", "Write", *_TASK_LIST),
}


#: The events on which Claude Code applies a tool matcher.
_TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure"}


class InstallRequest(BaseModel):
    """What the spawner knows about the session it is about to start."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    profile: Profile
    role: str | None
    worktree: AbsolutePath
    own_branch: str | None
    store_root: AbsolutePath | None
    state_dir: AbsolutePath
    target_dir: AbsolutePath
    claude_config_dir: AbsolutePath
    user_home: AbsolutePath
    token_ceiling: int = Field(gt=0)
    required_reading: tuple[AbsolutePath, ...] = ()
    always_loaded: tuple[AbsolutePath, ...] = ()
    held_out: tuple[AbsolutePath, ...] = ()
    extra_protected: tuple[AbsolutePath, ...] = ()
    #: A script that prints the API key, named in the settings file so the key is
    #: never in the session's environment, where every tool call could print it.
    #: It must live in the session's own files or its state directory, both
    #: protected roots, so no session tool can rewrite it.
    api_key_helper: AbsolutePath | None = None


@dataclass(frozen=True)
class Installed:
    """What an install wrote, and how to start the session that uses it."""

    settings_path: Path
    config_path: Path
    spawn_args: tuple[str, ...]
    spawn_env: Mapping[str, str]


def current_installation() -> Installation:
    """The interpreter and package this process runs from."""
    return Installation(
        interpreter=sys.executable,
        package_dir=str(Path(physgate.__file__).resolve().parent),
        environment_root=sys.prefix,
        base_prefix=sys.base_prefix,
    )


def _inside(path: str, root: str) -> bool:
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def build_config(request: InstallRequest, installation: Installation) -> SessionConfig:
    """The session configuration for ``request``.

    Raises:
        ValueError: a file the session must not be able to change would sit
            inside its worktree.
    """
    outside = {
        "the settings directory": request.target_dir,
        "the state directory": request.state_dir,
        "the Claude configuration directory": request.claude_config_dir,
        "the hook package": installation.package_dir,
        "the hook interpreter's environment": installation.environment_root,
        "the hook interpreter's own installation": installation.base_prefix,
    }
    for what, path in outside.items():
        if _inside(path, request.worktree):
            msg = f"{what} ({path}) is inside the worktree, where the session could change it"
            raise ValueError(msg)
    worktree = Path(request.worktree)
    home = Path(request.user_home)
    hook_code = "it is the code the hooks run from"
    protected: dict[str, tuple[str, Watch]] = {
        str(worktree / "src" / "physgate" / "gate"): (GATE_REASON, "revert"),
        str(worktree / "src" / "physgate" / "hooks"): (
            "it holds the hook layer's source, which no agent session edits",
            "revert",
        ),
        str(worktree / ".env"): ("it holds the environment's secrets", "revert"),
        str(worktree / ".claude"): (
            "it holds Claude Code settings, and a settings write can switch the hooks off",
            "revert",
        ),
        request.target_dir: ("it holds this session's settings and configuration", "revert"),
        # Written by the hooks themselves, so only the layers that refuse a write
        # before it happens protect it.
        request.state_dir: ("it holds the hook layer's own records of this session", "none"),
        # Written by Claude Code itself during the session.
        request.claude_config_dir: ("it is this session's Claude Code configuration", "none"),
        installation.package_dir: (hook_code, "halt"),
        installation.environment_root: (hook_code, "halt"),
        installation.base_prefix: (hook_code, "halt"),
        # Other sessions on the machine write these legitimately.
        str(home / ".claude" / "settings.json"): (
            "it is the user's Claude Code settings, which later sessions read",
            "log",
        ),
        str(home / ".claude.json"): (
            "it is the user's Claude Code state, which later sessions read",
            "log",
        ),
    }
    for path in request.extra_protected:
        protected.setdefault(path, ("the orchestrator protects it for this session", "revert"))
    for path in request.held_out:
        protected.setdefault(path, (HELD_OUT_REASON, "revert"))
    if request.store_root is not None:
        protected[request.store_root] = (STORE_REASON, "journal")
    for path in protected:
        if _inside(request.worktree, path):
            msg = (
                f"the protected path {path} contains the worktree, so every write would be refused"
            )
            raise ValueError(msg)
    return SessionConfig(
        profile=request.profile,
        role=request.role,
        worktree=request.worktree,
        own_branch=request.own_branch,
        store_root=request.store_root,
        state_dir=request.state_dir,
        protected_roots=tuple(
            ProtectedRoot(path=path, reason=reason, watch=watch)
            for path, (reason, watch) in sorted(protected.items())
        ),
        experiments=(
            ExperimentRule(
                root=str(worktree / "experiments"),
                frozen_marker="RESULT.md",
                always_frozen_name="CRITERIA.md",
            ),
        ),
        held_out=tuple(sorted(request.held_out)),
        required_reading=tuple(sorted(request.required_reading)),
        always_loaded=tuple(sorted(request.always_loaded)),
        token_ceiling=request.token_ceiling,
        tools_allowed=tuple(sorted(PROFILE_TOOLS[request.profile])),
        installation=installation,
        watchdog_seconds=WATCHDOG_SECONDS,
        hook_timeout_seconds=HOOK_TIMEOUT_SECONDS,
    )


def render_settings(
    config: SessionConfig,
    config_path: str,
    config_sha256: str,
    registry: Mapping[str, HookSpec],
    api_key_helper: str | None = None,
) -> dict[str, object]:
    """The settings file: one command per event, naming every hook module that handles it."""
    trampoline = str(Path(config.installation.package_dir) / "hooks" / "trampoline.sh")
    hooks: dict[str, object] = {}
    for event in EVENTS:
        names = sorted(name for name, spec in registry.items() if event in spec.handlers)
        if not names:
            continue
        command = shlex.join(
            [
                "/bin/sh",
                trampoline,
                str(config.watchdog_seconds),
                config.installation.interpreter,
                "-I",
                "-m",
                "physgate.hooks",
                event,
                "--hooks",
                ",".join(names),
                "--config",
                config_path,
                "--config-sha256",
                config_sha256,
            ]
        )
        group: dict[str, object] = {
            "hooks": [
                {"type": "command", "command": command, "timeout": config.hook_timeout_seconds}
            ]
        }
        if event in _TOOL_EVENTS:
            group["matcher"] = "*"
        hooks[event] = [group]
    settings: dict[str, object] = {"disableAllHooks": False, "hooks": hooks}
    if api_key_helper is not None:
        settings["apiKeyHelper"] = api_key_helper
    return settings


def _dump(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def install(
    request: InstallRequest,
    registry: Mapping[str, HookSpec],
    installation: Installation | None = None,
) -> Installed:
    """Write the session's configuration and settings file; return how to spawn it."""
    helper = request.api_key_helper
    if helper is not None and not any(
        _inside(helper, root) for root in (request.target_dir, request.state_dir)
    ):
        msg = "the key helper must live in the session's files or its state directory"
        raise ValueError(msg)
    config = build_config(request, installation or current_installation())
    target = Path(request.target_dir)
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / CONFIG_NAME
    config_bytes = _dump(config.model_dump(mode="json"))
    # The shape is validated where it is written, through the schema, on the very
    # bytes the hooks will read and whose digest they carry: the hooks validate
    # them again with the standard-library validator a test holds to this one.
    if SessionConfig.model_validate_json(config_bytes) != config:
        msg = "the configuration does not read back as the one that was built"
        raise ValueError(msg)
    config_path.write_bytes(config_bytes)
    settings = render_settings(
        config, str(config_path), digest(config_bytes), registry, request.api_key_helper
    )
    settings_path = target / SETTINGS_NAME
    settings_path.write_bytes(_dump(settings))
    return Installed(
        settings_path=settings_path,
        config_path=config_path,
        spawn_args=("--setting-sources", "", "--settings", str(settings_path)),
        spawn_env={"CLAUDE_CONFIG_DIR": request.claude_config_dir},
    )
