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
import os
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
from physgate.hooks.reasons import ANSWER_KEY_REASON as ANSWER_KEY_REASON
from physgate.hooks.reasons import GATE_REASON as GATE_REASON
from physgate.hooks.reasons import HARNESS_REASON as HARNESS_REASON
from physgate.hooks.reasons import HELD_OUT_REASON as HELD_OUT_REASON
from physgate.hooks.reasons import KNOWLEDGE_REASON as KNOWLEDGE_REASON
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
    # A reviewer reads, and answers once through the structured verdict tool. It writes
    # no file, so no tool that writes is on its list.
    "reviewer": ("Read", "StructuredOutput"),
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
    #: Evaluation corpora carrying their answers, beside the worktree's own
    #: ``corpora`` directory, which is always one.
    answer_keys: tuple[AbsolutePath, ...] = ()
    extra_protected: tuple[AbsolutePath, ...] = ()
    #: Paths no session tool may write, but which the runtime or the spawner writes
    #: while the session runs (its captured stream, its process record), so the
    #: sentinel must not put them back. Only the layers that refuse a write before
    #: it happens protect them.
    extra_protected_refuse_only: tuple[AbsolutePath, ...] = ()
    #: The source checkout the orchestrator runs from, when it runs from one: the
    #: gate's source, the curated library and the frozen experiments the run is
    #: judged by. A session in any other worktree may write none of it.
    harness_root: AbsolutePath | None = None
    #: The ``site-packages`` of the interpreter the orchestrator runs on. A ``.pth`` file
    #: or a customize module at its top level runs inside the orchestrator's next
    #: start, the process that imports the gate.
    harness_site_packages: tuple[AbsolutePath, ...] = ()
    #: A reviewer's read allowance: the directories it may read, and nothing else.
    #: Required for a reviewer, refused for every other profile.
    read_roots: tuple[AbsolutePath, ...] = ()
    #: Further places only reviewers read, withheld from every other session like the
    #: library's reviewer tree: the directory reviews are prepared in.
    extra_review_material: tuple[AbsolutePath, ...] = ()
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


#: The tracked directory holding curated standards, skill and bounds content, and
#: the one subdirectory beneath it a session may still write: a subtask's own
#: outcome leaves a candidate there, and nothing promotes it into the library but
#: the human-run promotion command.
KNOWLEDGE_DIR_NAME = "knowledge"
KNOWLEDGE_STAGING_NAME = "staging"


def _knowledge_root(worktree: Path) -> str:
    """The whole curated-knowledge tree under ``worktree``, as one path.

    Protected whole, whether or not the tree or any domain beneath it exists
    yet on disk — the string test in ``paths.py`` works for a root that does
    not exist yet, the same way the gate directory is protected before its
    first file. Protecting only the domains discovered at settings-build time
    left a not-yet-existing domain's standards file completely unprotected (a
    role session could plant one with an ordinary Write call, found live
    against the real binary): a domain before its first promotion is exactly
    the case needing protection most, not the one a discover-what-exists
    approach skips.
    """
    return str(worktree / KNOWLEDGE_DIR_NAME)


#: The tree beneath ``knowledge/`` holding what only reviewers read: each role's
#: rubric. One directory for all of it, so withholding it from every other session
#: is one rule that covers rubrics not yet written, not a list of files.
REVIEWERS_DIR_NAME = "reviewers"


def review_material(worktree: Path, harness: Path | None) -> tuple[str, ...]:
    """Where reviewer-only material can be, for a session in ``worktree``.

    Its own checkout's reviewer tree, and the harness checkout's when there is one.
    """
    found = {str(worktree / KNOWLEDGE_DIR_NAME / REVIEWERS_DIR_NAME)}
    if harness is not None:
        found.add(str(harness / KNOWLEDGE_DIR_NAME / REVIEWERS_DIR_NAME))
    return tuple(sorted(found))


def _knowledge_staging(worktree: Path) -> str:
    """The one path beneath the knowledge tree a session may still write.

    A subtask's own outcome leaves a candidate here, and nothing promotes it
    into the library but the human-run promotion command.
    """
    return str(worktree / KNOWLEDGE_DIR_NAME / KNOWLEDGE_STAGING_NAME)


#: Beneath the harness checkout, what the sentinel also puts back if it changes: the
#: trees whose bytes a run trusts, small enough to walk at every hook. Measured
#: 02.10.2026: ``src`` and ``knowledge`` together are about 270 entries, a 1.6 ms
#: walk and a 30 ms record at session start. The whole checkout is not: its
#: environment and frozen experiments are 6,500 to 49,000 entries, a 2 s walk at
#: every hook and 200 MB to 1.3 GB copied at every session's start. So the rest of
#: the checkout is refused before a write and not put back after one.
HARNESS_REVERTED = ("src", "knowledge", "scripts", "pyproject.toml", "uv.lock")
#: The frozen records of every experiment in the harness checkout, put back by name
#: rather than with their whole directories, for the same reason.
HARNESS_EVIDENCE = ("CRITERIA.md", "RESULT.md")


def _harness_roots(harness: Path) -> dict[str, tuple[str, Watch]]:
    """The harness checkout, refused whole; what in it a run trusts, also put back.

    No exception beneath it, at either layer: a session whose worktree is not this
    checkout has nothing of its own to write here (its own ``knowledge/staging/`` is
    in its own worktree).
    """
    roots: dict[str, tuple[str, Watch]] = {str(harness): (HARNESS_REASON, "none")}
    for name in HARNESS_REVERTED:
        roots[str(harness / name)] = (HARNESS_REASON, "revert")
    evidence = {name.casefold() for name in HARNESS_EVIDENCE}
    for directory, _, files in os.walk(harness / "experiments"):
        for name in files:
            if name.casefold() in evidence:
                roots[os.path.join(directory, name)] = (HARNESS_REASON, "revert")
    return roots


#: The entries at the top of an environment's ``site-packages`` that Python runs on its
#: own at start: every ``*.pth`` file, and the two customize modules.
STARTUP_MODULES = ("sitecustomize.py", "usercustomize.py")


def _startup_watch(site_packages: Path) -> tuple[str, ...]:
    """Every top-level entry of ``site-packages`` the sentinel need not watch.

    What is left watched is each ``*.pth`` file and customize module there now, and
    anything new at the top level, of any name, which is moved aside. Not a walk of
    the environment: measured 02.10.2026 at 2 to 4 watched entries, a 0.3 to 6.6 ms
    walk and 8 KB kept, against 38 MB kept if every top-level file were watched.
    """
    try:
        entries = list(os.scandir(site_packages))
    except OSError:
        return ()
    return tuple(
        sorted(
            e.path for e in entries if not (e.name.endswith(".pth") or e.name in STARTUP_MODULES)
        )
    )


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
    for root in request.read_roots:
        if not root.strip("/"):
            msg = f"the read root {root!r} names the whole filesystem"
            raise ValueError(msg)
    if (request.profile == "reviewer") != bool(request.read_roots):
        msg = "a reviewer reads only beneath its read roots, and only a reviewer has them"
        raise ValueError(msg)
    for what, path in (
        ("the settings directory", request.target_dir),
        ("the state directory", request.state_dir),
        ("the Claude configuration directory", request.claude_config_dir),
    ):
        if any(_inside(path, root) for root in request.read_roots):
            msg = f"{what} ({path}) is inside a reviewer's read allowance"
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
        _knowledge_root(worktree): (KNOWLEDGE_REASON, "revert"),
    }
    #: Paths that are not protected by the root they sit under, despite the
    #: string/inode tests otherwise reaching it. Only one root needs this today.
    root_exceptions: dict[str, tuple[str, ...]] = {
        _knowledge_root(worktree): (_knowledge_staging(worktree),),
    }
    if request.harness_root is not None:
        for path, entry in _harness_roots(Path(request.harness_root)).items():
            protected.setdefault(path, entry)
    for site_packages in request.harness_site_packages:
        protected.setdefault(site_packages, (HARNESS_REASON, "revert"))
        root_exceptions[site_packages] = _startup_watch(Path(site_packages))
    for path in request.extra_protected:
        protected.setdefault(path, ("the orchestrator protects it for this session", "revert"))
    for path in request.extra_protected_refuse_only:
        protected.setdefault(
            path,
            (
                "the orchestrator protects it for this session; it is written while the "
                "session runs, by the runtime and not by any tool",
                "none",
            ),
        )
    for path in request.held_out:
        protected.setdefault(path, (HELD_OUT_REASON, "revert"))
    answer_keys = sorted({str(worktree / "corpora"), *request.answer_keys})
    for path in answer_keys:
        protected.setdefault(path, (ANSWER_KEY_REASON, "revert"))
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
            ProtectedRoot(
                path=path, reason=reason, watch=watch, exceptions=root_exceptions.get(path, ())
            )
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
        answer_keys=tuple(answer_keys),
        read_roots=tuple(sorted(request.read_roots)),
        review_material=(
            ()
            if request.profile == "reviewer"
            else tuple(
                sorted(
                    {
                        *review_material(
                            worktree, Path(request.harness_root) if request.harness_root else None
                        ),
                        *request.extra_review_material,
                    }
                )
            )
        ),
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
