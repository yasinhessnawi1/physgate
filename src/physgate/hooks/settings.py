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
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import physgate
from physgate.hooks import shell_startup
from physgate.hooks.config import (
    AbsolutePath,
    ExperimentRule,
    Installation,
    Profile,
    ProtectedRoot,
    Reads,
    SessionConfig,
    Watch,
    digest,
)
from physgate.hooks.graph import COMPLETION_DIR, DISPUTES_DIR, PROPOSALS_DIR
from physgate.hooks.reasons import ANSWER_KEY_REASON as ANSWER_KEY_REASON
from physgate.hooks.reasons import CLAUDE_TEMP_REASON as CLAUDE_TEMP_REASON
from physgate.hooks.reasons import GATE_REASON as GATE_REASON
from physgate.hooks.reasons import GIT_USER_CONFIG_REASON as GIT_USER_CONFIG_REASON
from physgate.hooks.reasons import HARNESS_REASON as HARNESS_REASON
from physgate.hooks.reasons import HELD_OUT_REASON as HELD_OUT_REASON
from physgate.hooks.reasons import HOME_CLAUDE_REASON as HOME_CLAUDE_REASON
from physgate.hooks.reasons import HOOK_STATE_REASON as HOOK_STATE_REASON
from physgate.hooks.reasons import KNOWLEDGE_REASON as KNOWLEDGE_REASON
from physgate.hooks.reasons import SERIES_WRITER_REASON as SERIES_WRITER_REASON
from physgate.hooks.reasons import SESSION_TEMPS_REASON as SESSION_TEMPS_REASON
from physgate.hooks.reasons import SESSIONS_REASON as SESSIONS_REASON
from physgate.hooks.reasons import SHELL_STARTUP_REASON as SHELL_STARTUP_REASON
from physgate.hooks.reasons import STORE_REASON as STORE_REASON
from physgate.hooks.reasons import TOOL_ENVIRONMENT_REASON as TOOL_ENVIRONMENT_REASON
from physgate.hooks.reasons import WITHHELD_REASON as WITHHELD_REASON
from physgate.hooks.reasons import series_outbox_reason
from physgate.hooks.runtime import EVENTS, HookSpec
from physgate.oslayer import reaper_install
from physgate.oslayer.placement import machine_writable, placement_refusal
from physgate.oslayer.policy import NETWORK_UNENFORCED, sandbox_policy
from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs
from physgate.oslayer.session_temp import session_temps_root
from physgate.toolenv.register import load_register, server_tools

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
    # The raw agent gets exactly a role's tools: the comparison is with the same tools.
    "baseline": ("Bash", "Edit", "NotebookEdit", "Read", "Write", *_TASK_LIST),
}

#: The tool servers each profile's sessions may be offered, by their names in the register.
#: A role session and the raw agent get the identical set: the environment is the same for
#: every role, and the comparison is with the same tools. A reviewer and the orchestrator get
#: none.
_EVERY_SERVER = tuple(sorted(load_register().servers))
PROFILE_SERVERS: Mapping[Profile, tuple[str, ...]] = {
    "role": _EVERY_SERVER,
    "reviewer": (),
    "orchestrator": (),
    "baseline": _EVERY_SERVER,
}

#: The web tools, which bring in text nobody reviewed.
WEB_TOOLS = ("WebFetch", "WebSearch")
#: The tools each profile's settings deny, a second layer beside the tools hook: a deny rule
#: binds in ``bypassPermissions``, which every session runs in, and refuses the tool whether or
#: not a hook ran (measured on the pinned binary, 11.11.2026). The web tools need it: the tools
#: hook was their only layer, and ``network: none`` binds a session's shell but not its WebFetch
#: tool. Every profile denies them. A profile made to read the web (a researcher's) would be the
#: one exception, and would be listed here without them, with its own test.
#:
#: The binary's search tool is denied to every profile too. With it on (2.1.322 by default, and
#: 2.1.301 against the live API host) the binary leaves a tool server's tools out of the request
#: and tells the model to load them through that tool, which no closed list names; with it
#: denied the binary offers every server tool directly, on both pins, whatever the environment
#: says of tool search (measured, 14.11.2026). Nothing is widened: a session reaches no tool it
#: could not, and each call still reaches the tools hook by its own name.
TOOL_SEARCH = "ToolSearch"
_DENIED = (*WEB_TOOLS, TOOL_SEARCH)
PROFILE_DENIED: Mapping[Profile, tuple[str, ...]] = {
    "role": _DENIED,
    "reviewer": _DENIED,
    "orchestrator": _DENIED,
    "baseline": _DENIED,
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
    #: Paths beneath an ``extra_protected`` root that the root does not protect after all:
    #: the one place under it a session writes (a blind check's own directory inside the
    #: tier-set store, which holds its worktree). Each must lie beneath one of those roots.
    extra_protected_exceptions: tuple[AbsolutePath, ...] = ()
    #: Paths no session tool may write, but which the runtime or the spawner writes
    #: while the session runs (its captured stream, its process record), so the
    #: sentinel must not put them back. Only the layers that refuse a write before
    #: it happens protect them.
    extra_protected_refuse_only: tuple[AbsolutePath, ...] = ()
    #: The roots of the run's recorded tool environment: read and run by the session's
    #: commands, written by none. Far too large to put back, so only the layers that refuse a
    #: write before it happens protect them; the dispatcher refuses the next session if any
    #: entry changed.
    tool_environment_roots: tuple[AbsolutePath, ...] = ()
    #: The run's directory of every session's own directory (its ``sessions/``), which holds
    #: each session's login, captured stream, settings and hook records. Refused to every write;
    #: for a role or baseline session refused to every read of the hooks too, its own home
    #: included, but for what it is given to read there (the OS layer opens its home to its
    #: commands). Written by the runtime while sessions run, so never put back. Required for a
    #: role or baseline session, whose install is refused without it.
    sessions_root: AbsolutePath | None = None
    #: The run's append-only records the orchestrator holds open and appends to: no session
    #: tool may write them, and the sentinel compares them and never writes them, since a
    #: put-back by replacing would leave the orchestrator writing to a file no path names.
    extra_protected_record: tuple[AbsolutePath, ...] = ()
    #: The run's records that no session doing design work reads, by any route: the run's
    #: recorded configuration, which holds the held-out tier's canaries. Each is put back
    #: like any protected root, and refused to every read as well.
    withheld: tuple[AbsolutePath, ...] = ()
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
    #: The session's own temporary directory, set where the OS layer runs: the session's
    #: shell commands then run inside Claude Code's sandbox, writing only in the worktree,
    #: this directory and the session's home. ``None`` where the layer does not run.
    os_layer_temp_dir: AbsolutePath | None = None
    #: The session's own temporary directory where the OS layer does not run. Either this or
    #: ``os_layer_temp_dir`` is the session's own, and its binary is pointed at it
    #: (``CLAUDE_CODE_TMPDIR``): without one, Claude Code keeps the session's temporary files in
    #: the directory every session of the user shares. Required for a role, baseline or reviewer
    #: session, whose install is refused without one.
    temp_dir: AbsolutePath | None = None
    #: Claude Code's temporary directories that every session of the user on the machine shares
    #: (``/tmp/claude-<uid>``), holding the other sessions' task outputs, the operator's among
    #: them: refused to every read and write of a role, baseline or reviewer session, on every
    #: layer. Taken from the machine, never from the spawner.
    shared_claude_temp: tuple[AbsolutePath, ...] = Field(default_factory=lambda: claude_temp_dirs())
    #: The one parent every session's own temporary directory lies directly beneath: refused to
    #: every read and write of a role, baseline or reviewer session, on every layer, but for its
    #: own child there, matched exactly. Every session runs as the same user, so a directory's
    #: mode keeps no session from another's. Taken from the machine, never from the spawner.
    session_temps: AbsolutePath = Field(default_factory=lambda: session_temps_root())
    #: Further places of the session's own that its shell commands read, where they sit
    #: inside a root the OS layer keeps from them (the run's ``sessions/``): the
    #: directory holding the run's named interpreter for this session.
    os_layer_readable: tuple[AbsolutePath, ...] = ()
    #: With the OS layer: ``none`` refuses the session's shell commands every remote host,
    #: in every permission mode, and every service on the machine's loopback.
    #: ``open`` leaves the network as the layer found it. Without the OS layer nothing
    #: can enforce ``none``: the install says so (:data:`Installed.network_unenforced`).
    os_layer_network: Literal["open", "none"] = "open"
    #: Whether the spawner exports the session's own pid as the survivor reaper's canary
    #: (:data:`physgate.oslayer.reaper_install.CANARY_EXPORT`), as the dispatcher's held
    #: spawn does. A session that gets the reaper is refused without it: its reaper could
    #: never prove its fence, and every command would be refused.
    spawns_with_canary: bool = False
    #: The tool servers the session is offered, by their names in the tool-server register.
    #: Their admitted tools join the session's closed list; only a profile whose server set
    #: names them may be offered them (:data:`PROFILE_SERVERS`).
    tool_servers: tuple[str, ...] = ()


#: The longest temporary directory Claude Code takes for a sandboxed session. A longer
#: one is silently replaced by the per-user default, shared by every session of the
#: user (measured on 2.1.301: 32 characters taken, 34 and more replaced). Held for every
#: session's own temporary directory, with the OS layer or without it.
OS_LAYER_TEMP_LIMIT = 32

#: The profiles given a temporary directory of their own and refused the shared one: every
#: session under test, doing design work or judging it.
OWN_TEMP_PROFILES: tuple[Profile, ...] = ("role", "baseline", "reviewer")


@dataclass(frozen=True)
class Installed:
    """What an install wrote, and how to start the session that uses it."""

    settings_path: Path
    config_path: Path
    spawn_args: tuple[str, ...]
    spawn_env: Mapping[str, str]
    #: Set when ``none`` was asked for and no OS layer was installed to enforce it: what
    #: the session's record must carry, since its shell commands stay online.
    network_unenforced: str | None = None


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


def _is_the_installing_user_s_home(home: Path) -> bool:
    """True where a session is given the home of the user installing it, not a scratch one.

    That home's ``.claude`` is the user's own Claude Code directory, which their other
    sessions read and write: it is left to the two named files, as before.
    """
    try:
        return home.resolve() == Path.home().resolve()
    except (OSError, RuntimeError):
        return False


def _design_discipline(worktree: Path) -> tuple[str, ...]:
    """The roots that are the harness's discipline over a design worktree, not integrity."""
    return (
        str(worktree / "src" / "physgate" / "gate"),
        str(worktree / "src" / "physgate" / "hooks"),
        _knowledge_root(worktree),
        str(worktree / ".physgate" / "lib"),
        str(worktree / ".physgate" / "series"),
    )


def _tools_allowed(request: InstallRequest) -> tuple[str, ...]:
    """The profile's list, and the admitted tools of the servers the session is offered.

    Raises:
        ValueError: a server is named twice, is not in the register, or is not one the
            profile may be offered.
    """
    servers = request.tool_servers
    if len(set(servers)) != len(servers):
        msg = f"a tool server is named twice: {sorted(servers)}"
        raise ValueError(msg)
    for server in servers:
        if server not in PROFILE_SERVERS[request.profile]:
            msg = f"a {request.profile} session may not be offered the tool server {server!r}"
            raise ValueError(msg)
    return (*PROFILE_TOOLS[request.profile], *server_tools(load_register(), servers))


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
        request.state_dir: (HOOK_STATE_REASON, "none"),
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
        str(worktree / ".physgate" / "lib"): (SERIES_WRITER_REASON, "revert"),
        # Refused only, never put back: a script's own write, which no hook sees, is the one way
        # a record arrives, and the orchestrator collects and checks what arrived.
        str(worktree / ".physgate" / "series"): (
            series_outbox_reason(sys.platform, os_layer=request.os_layer_temp_dir is not None),
            "none",
        ),
    }
    if request.profile == "baseline":
        # The raw agent keeps the evaluation's two protections and the roots that keep a
        # session from undoing them; the harness's own discipline over a design worktree
        # (its gate and hook sources, the curated knowledge, the series writer and outbox)
        # is what it is measured without.
        for path in _design_discipline(worktree):
            protected.pop(path, None)
    # The one root the OS layer leaves to scripts: a record arrives by a script's own write,
    # which no OS rule can tell from any other command's, and the collector judges it.
    outbox = str(worktree / ".physgate" / "series")
    if request.profile == "role":
        # git's user configuration in the session's own home: a key written there (a hook
        # path, an alias, a program to run) holds for every later git command the session
        # runs. The session's environment is built without XDG_CONFIG_HOME, so git looks in
        # ``$HOME/.config/git``; that directory also holds git's user attributes and ignore.
        # The raw agent's stays writable: it is measured without the harness's discipline
        # over git, and what a configuration there names runs only when the session's own
        # commands run git, inside the sandbox; the binary runs none of it outside (measured
        # through the real binary, by a row of its own).
        for git_config in (home / ".gitconfig", home / ".config" / "git"):
            protected[str(git_config)] = (GIT_USER_CONFIG_REASON, "revert")
    if request.profile in ("role", "baseline"):
        # A shell startup file in the session's own home, which its commands write: a shell
        # the binary starts outside the sandbox would run it. The raw agent keeps it too, since
        # it is what keeps a session inside the layer that bounds the evaluation's protections.
        for name in shell_startup.NAMES:
            protected[str(home / name)] = (SHELL_STARTUP_REASON, "revert")
    #: Who may read each root, for the OS layer (see ``ProtectedRoot.reads``): the
    #: session's credentials are kept from its shell commands, and the hooks' records from
    #: every tool of the session (the file tools' refusal is the hooks' own, in ``paths``).
    reads: dict[str, Reads] = {
        request.state_dir: "denied",
        request.claude_config_dir: "shell_denied",
    }
    if not _is_the_installing_user_s_home(home):
        # A scratch home is the session's own to write, all but the one directory in it the
        # binary treats as a user's own: skills, mods, commands and settings a user keeps are
        # read from a directory of that name, and a file a session left there is a file a
        # later version may load. Whole, both ways, for every tool and every command.
        # Where the OS layer does not run, nothing stands behind the hooks: whatever appears
        # there is put back, and the binary makes nothing there itself (measured on 2.1.301
        # and 2.1.322). Where it runs, the layer denies the write, and the root is not put
        # back, because the runtime then makes directories there before a shell command
        # (measured on macOS, 12.11.2026: 2.1.301 makes ``.claude`` and ``bridge-spawn`` in
        # it, 2.1.322 those and ``ssh``, with other modes), as it writes its configuration
        # directory.
        watched: Watch = "revert" if request.os_layer_temp_dir is None else "none"
        protected[str(home / ".claude")] = (HOME_CLAUDE_REASON, watched)
        reads[str(home / ".claude")] = "denied"
    reaper_on = request.os_layer_temp_dir is not None and reaper_install.wanted()
    if reaper_on:
        # The reaper's front tells a hook command from a sandboxed one by whether it can
        # read the session's settings: kept from every command (its own directory is opened).
        reads[request.target_dir] = "shell_denied"
    if outbox in protected:
        # Written blind: a script's record goes in, and nothing of the session reads it back,
        # by a tool or by a command, whatever spelling of the path the command builds.
        reads[outbox] = "denied"
    #: Paths that are not protected by the root they sit under, despite the
    #: string/inode tests otherwise reaching it. Only one root needs this today.
    root_exceptions: dict[str, tuple[str, ...]] = {
        _knowledge_root(worktree): (_knowledge_staging(worktree),),
    }
    if request.harness_root is not None:
        for path, entry in _harness_roots(Path(request.harness_root)).items():
            protected.setdefault(path, entry)
            reads.setdefault(path, "denied")
    for site_packages in request.harness_site_packages:
        protected.setdefault(site_packages, (HARNESS_REASON, "revert"))
        root_exceptions[site_packages] = _startup_watch(Path(site_packages))
    for path in request.extra_protected:
        protected.setdefault(path, ("the orchestrator protects it for this session", "revert"))
        carved = tuple(e for e in request.extra_protected_exceptions if _inside(e, path))
        if carved:
            root_exceptions[path] = carved
    stray = [
        e
        for e in request.extra_protected_exceptions
        if not any(_inside(e, path) for path in request.extra_protected)
    ]
    if stray:
        msg = f"an exception lies beneath no root the session is protected from: {stray}"
        raise ValueError(msg)
    for path in request.extra_protected_record:
        protected.setdefault(
            path,
            (
                "it is one of the run's own records, which the orchestrator alone writes",
                "record",
            ),
        )
    for path in request.extra_protected_refuse_only:
        protected.setdefault(
            path,
            (
                "the orchestrator protects it for this session; it is written while the "
                "session runs, by the runtime and not by any tool",
                "none",
            ),
        )
        reads.setdefault(path, "shell_denied")
    for path in request.tool_environment_roots:
        # Refused and never put back, and left open to every read: the session's commands run
        # the interpreter and the build tools there and import its libraries.
        protected.setdefault(path, (TOOL_ENVIRONMENT_REASON, "none"))
    read_exceptions: dict[str, tuple[str, ...]] = {}
    if request.sessions_root is not None:
        sessions = request.sessions_root
        if request.profile in ("role", "baseline"):
            # Assigned, not defaulted: named as a refuse-only root too, it is still kept from
            # every read, its own home included. Only what it is given to read beneath the
            # root stays open to its tools (integration's issued state), and the directory of
            # the run's named interpreter, which its commands run from and none can write; its
            # binary reads its own configuration itself, and the OS layer opens its home to its
            # commands.
            protected[sessions] = (SESSIONS_REASON, "none")
            reads[sessions] = "denied"
            own = (*request.required_reading, *request.always_loaded, *request.os_layer_readable)
            # Never a place in its home, where its commands write: an allowance there could be a
            # link made there.
            read_exceptions[sessions] = tuple(
                sorted(
                    {p for p in own if _inside(p, sessions) and not _inside(p, request.user_home)}
                )
            )
        else:
            protected.setdefault(sessions, (SESSIONS_REASON, "none"))
            reads.setdefault(sessions, "shell_denied")
    if request.profile in OWN_TEMP_PROFILES:
        # The temporary directory every Claude Code session of the user shares, which holds the
        # other sessions' task outputs, the operator's among them. This session's binary is
        # pointed at a directory of its own, so nothing of it lies there: refused to every read
        # and write on every layer, and never put back, since the other sessions write it.
        # Assigned, not defaulted, as the run's session directories are.
        for path in request.shared_claude_temp:
            protected[path] = (CLAUDE_TEMP_REASON, "none")
            reads[path] = "denied"
        # Every session's own temporary directory, the others' as much as its own: only its own
        # child stays open, exactly as the path is spelt and resolved, never through a link.
        # Named where it really is (/var is /private/var on macOS), as the installer's own
        # temporary directory is, so the sandbox finds the session's child beneath it.
        temps = os.path.realpath(request.session_temps)
        protected[temps] = (SESSION_TEMPS_REASON, "none")
        reads[temps] = "denied"
        own_temp = request.os_layer_temp_dir or request.temp_dir
        read_exceptions[temps] = (own_temp,) if own_temp is not None else ()
    for path in request.withheld:
        # Assigned, not defaulted: a withheld record named as an ordinary protected root too
        # is withheld all the same, put back and refused to every read on every layer.
        protected[path] = (WITHHELD_REASON, "revert")
        reads[path] = "denied"
    for path in request.held_out:
        protected.setdefault(path, (HELD_OUT_REASON, "revert"))
        reads[path] = "denied"
    answer_keys = sorted({str(worktree / "corpora"), *request.answer_keys})
    for path in answer_keys:
        protected.setdefault(path, (ANSWER_KEY_REASON, "revert"))
        reads[path] = "denied"
    if request.store_root is not None:
        protected[request.store_root] = (STORE_REASON, "journal")
    for path in protected:
        # A worktree inside one of the root's own exceptions is written there, not refused.
        if _inside(request.worktree, path) and not any(
            _inside(request.worktree, e) for e in root_exceptions.get(path, ())
        ):
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
                path=path,
                reason=reason,
                watch=watch,
                exceptions=root_exceptions.get(path, ()),
                reads=reads.get(path, "open"),
                read_exceptions=read_exceptions.get(path, ()),
                shell_writes="allowed" if path == outbox else "denied",
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
        tools_allowed=tuple(sorted(_tools_allowed(request))),
        installation=installation,
        watchdog_seconds=WATCHDOG_SECONDS,
        hook_timeout_seconds=HOOK_TIMEOUT_SECONDS,
        survivor_reaper=reaper_on,
    )


#: Where :func:`protected_in_a_worktree` places the role session it asks about. Nothing is
#: read from or written to it: the configuration is only built.
_ASKED_ABOUT = PurePosixPath("/physgate-protected-roots")


def protected_in_a_worktree() -> tuple[tuple[PurePosixPath, tuple[PurePosixPath, ...]], ...]:
    """Every root the hook layer protects inside a role session's worktree, relative to it.

    Each comes with the paths beneath it a session may still write. They are read from
    the configuration :func:`build_config` gives a role session, never listed a second
    time, so a root added there is one here too. The protected roots are counted (the
    answer-carrying corpora among them), and the experiments directory, whose criteria
    and results are frozen. What lies outside the worktree (the session's settings,
    state and home, the hook installation) is left out. The orchestrator's own additions
    are left out too: they are the run's records and git's files, outside the worktree
    or its ``.git`` entry.
    """
    worktree = _ASKED_ABOUT / "worktree"
    session = _ASKED_ABOUT / "session"
    config = build_config(
        InstallRequest(
            profile="role",
            role="asked",
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(session / "state"),
            target_dir=str(session / "settings"),
            claude_config_dir=str(session / "config"),
            user_home=str(session / "home"),
            token_ceiling=1,
        ),
        Installation(
            interpreter=str(session / "python"),
            package_dir=str(session / "package"),
            environment_root=str(session / "environment"),
            base_prefix=str(session / "base"),
        ),
    )

    def inside(path: str) -> PurePosixPath | None:
        """``path`` relative to the worktree, if it lies beneath it."""
        at = PurePosixPath(path)
        if at == worktree or not at.is_relative_to(worktree):
            return None
        return at.relative_to(worktree)

    found: dict[PurePosixPath, tuple[PurePosixPath, ...]] = {}
    for root in config.protected_roots:
        at = inside(root.path)
        if at is not None:
            allowed = (inside(exception) for exception in root.exceptions)
            found[at] = tuple(sorted(a for a in allowed if a is not None))
    for rule in config.experiments:
        at = inside(rule.root)
        if at is not None:
            found.setdefault(at, ())
    return tuple(sorted(found.items()))


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
    settings: dict[str, object] = {
        "disableAllHooks": False,
        "hooks": hooks,
        "permissions": {"deny": list(PROFILE_DENIED[config.profile])},
    }
    if api_key_helper is not None:
        settings["apiKeyHelper"] = api_key_helper
    return settings


#: The rule lists of a permissions block: each a list of rule names, as the binary reads them.
RULE_LISTS = ("allow", "ask", "deny", "additionalDirectories")


def _rules(name: str, value: object) -> list[str]:
    """``value`` as the list of rule names a permissions block holds under ``name``.

    A list or a tuple of strings, which is what this module's own deny lists are. Anything else
    is refused, never written: a file whose rule list is a string, a mapping or ``null`` is not
    one the binary is known to read its deny from.

    Raises:
        ValueError: ``value`` is not a list or a tuple of strings.
    """
    if not isinstance(value, (list, tuple)) or not all(isinstance(rule, str) for rule in value):
        msg = (
            f"a settings layer's permissions.{name} is not a list of rule names "
            f"({type(value).__name__}), so it is not merged into the session's settings"
        )
        raise ValueError(msg)
    return list(value)


def _merge(settings: dict[str, object], more: Mapping[str, object]) -> None:
    """Merge ``more`` into ``settings``: a permissions block adds to theirs, its deny included.

    Never a plain update: a ``permissions`` key of ``more`` would replace the whole block, and the
    web tools' deny with it. The block is held to its form first, and what is not of it is
    refused before anything is replaced: the block a mapping, each of its rule lists
    (:data:`RULE_LISTS`) a list or a tuple of rule names. A deny is added to the session's own,
    whose rules stay, first and each once.

    Raises:
        ValueError: ``more`` carries a permissions block that is not of that form, or the
            settings it is merged into hold no deny list of their own.
    """
    for key, value in more.items():
        if key != "permissions":
            settings[key] = value
            continue
        own = settings.get(key)
        if not isinstance(value, Mapping) or not isinstance(own, dict):
            msg = (
                "a settings layer's permissions are not a mapping of rule lists "
                f"({type(value).__name__}), so they are not merged into the session's settings"
            )
            raise ValueError(msg)
        merged = {name: _rules(name, rule) for name, rule in value.items() if name in RULE_LISTS}
        held = _rules("deny", own.get("deny"))
        for name, rule in value.items():
            own[name] = merged.get(name, rule)
        own["deny"] = [*held, *(r for r in merged.get("deny", ()) if r not in held)]


def _require_denied(settings: Mapping[str, object], profile: Profile) -> None:
    """Refuse settings that do not carry ``profile``'s deny, whatever was merged into them.

    The last check before the settings are written, and independent of the merge: the deny is a
    list of rule names holding every tool the profile is denied.

    Raises:
        ValueError: it is not.
    """
    permissions = settings.get("permissions")
    deny = permissions.get("deny") if isinstance(permissions, Mapping) else None
    if (
        not isinstance(deny, list)
        or not all(isinstance(rule, str) for rule in deny)
        or not set(PROFILE_DENIED[profile]) <= set(deny)
    ):
        msg = (
            f"the session's settings do not deny {', '.join(PROFILE_DENIED[profile])} to the "
            f"{profile} profile (permissions.deny is {deny!r}), so they are not written"
        )
        raise ValueError(msg)


def _dump(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _make_file_tool_dirs(worktree: str) -> None:
    """Make the worktree's proposals, completion and disputes directories before its session starts.

    The OS layer write-denies each to every shell command, so that only the file tools, which the
    hooks check, write there. A denied path that does not exist is named only where its parent
    does, and a command could otherwise make it, or move a directory of its own into its place,
    before any file was written. Each step is made as a directory here, if missing, and never
    followed through a link a role session left.

    Raises:
        ValueError: a step of a path is there and is not a plain directory.
    """
    if not os.path.isdir(worktree):
        return
    for held in (PROPOSALS_DIR, COMPLETION_DIR, DISPUTES_DIR):
        step = worktree
        for part in Path(held).parts:
            step = os.path.join(step, part)
            if os.path.islink(step) or (os.path.lexists(step) and not os.path.isdir(step)):
                msg = f"{step} is not a directory, so the file tools' writes have no place held"
                raise ValueError(msg)
            if not os.path.lexists(step):
                os.mkdir(step)


def _make_zdotdir(target: Path, home: str) -> str:
    """Make the empty directory the session's ``ZDOTDIR`` names, in its settings directory.

    zsh reads its startup files from there and not from the home, in every shell the binary
    starts outside the sandbox; the settings directory is written by no session.

    Raises:
        ValueError: it is there already and is not an empty directory of its own, or it lies
            in the session's home.
    """
    where = target / shell_startup.ZDOTDIR_NAME
    if not os.path.lexists(where):
        where.mkdir(mode=0o755)
    refusal = shell_startup.zdotdir_refusal(str(where), home)
    if refusal is not None:
        raise ValueError(refusal)
    return str(where)


def _own_temp(request: InstallRequest) -> str | None:
    """The session's own temporary directory, refused where it is missing or unusable.

    Raises:
        ValueError: a role, baseline or reviewer session has none; two are given; or it is too
            long for the binary to take, which would replace it with the shared one.
    """
    if request.os_layer_temp_dir is not None and request.temp_dir is not None:
        msg = "a session has one temporary directory of its own: the OS layer's, or another"
        raise ValueError(msg)
    temp = request.os_layer_temp_dir or request.temp_dir
    if temp is not None and request.profile in OWN_TEMP_PROFILES:
        # Directly beneath the one parent, which every other session is refused: a directory
        # anywhere else would be open to every session of the user, all running as one uid.
        parent = os.path.realpath(request.session_temps)
        if os.path.realpath(os.path.dirname(temp.rstrip("/"))) != parent or not os.path.basename(
            temp.rstrip("/")
        ):
            msg = (
                f"the session's temporary directory ({temp}) must lie directly beneath "
                f"{request.session_temps}, the one parent no other session reads or writes"
            )
            raise ValueError(msg)
    if temp is None:
        if request.profile in OWN_TEMP_PROFILES:
            msg = (
                f"a {request.profile} session is installed only with a temporary directory of "
                "its own (os_layer_temp_dir or temp_dir): without one, Claude Code keeps its "
                "temporary files in the directory every session of the user shares, which the "
                "session may not read"
            )
            raise ValueError(msg)
        return None
    if len(temp) > OS_LAYER_TEMP_LIMIT:
        msg = (
            f"the session's temporary directory ({temp}) is longer than "
            f"{OS_LAYER_TEMP_LIMIT} characters, and Claude Code would replace it with "
            "the directory every session of the user shares"
        )
        raise ValueError(msg)
    return temp


def install(
    request: InstallRequest,
    registry: Mapping[str, HookSpec],
    installation: Installation | None = None,
) -> Installed:
    """Write the session's configuration and settings file; return how to spawn it.

    Raises:
        ValueError: among others, a role or baseline session without the run's session
            directories, or a role, baseline or reviewer session without a temporary directory
            of its own; nothing is written.
    """
    if request.profile in ("role", "baseline") and request.sessions_root is None:
        msg = (
            "a role or baseline session is installed only with the run's session directories "
            "(sessions_root): without them its tools could read every other session's login "
            "and stream"
        )
        raise ValueError(msg)
    own_temp = _own_temp(request)
    if request.profile in OWN_TEMP_PROFILES:
        # Before anything is written: the binary's snapshot step sources the home's startup
        # files outside the sandbox, once, as the session starts.
        # The harness holds a place in the home it gives a session, and judges what the
        # home holds: never in the home of whoever runs the install.
        if shell_startup.own_home_refusal(request.user_home) is not None:
            msg = (
                f"a {request.profile} session is installed only with a home of its own, and "
                f"{request.user_home} is the home of the user who runs the install"
            )
            raise ValueError(msg)
        found = shell_startup.home_refusal(request.user_home)
        if found is not None:
            raise ValueError(found)
    helper = request.api_key_helper
    if helper is not None and not any(
        _inside(helper, root) for root in (request.target_dir, request.state_dir)
    ):
        msg = "the key helper must live in the session's files or its state directory"
        raise ValueError(msg)
    if request.os_layer_temp_dir is not None:
        # Before anything is written. A worktree in a place the sandbox makes writable
        # shares the placeholders the Linux sandbox lays in its ancestors with every other
        # session there, and their commands abort each other's: refused for every
        # sandboxed session, a role's or the raw agent's.
        writable = (*machine_writable(), request.user_home, request.os_layer_temp_dir)
        misplaced = placement_refusal(Path(request.worktree), writable)
        if misplaced is not None:
            raise ValueError(misplaced)
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
    spawn_env = {"CLAUDE_CONFIG_DIR": request.claude_config_dir}
    if request.profile in OWN_TEMP_PROFILES:
        spawn_env[shell_startup.ZDOTDIR] = _make_zdotdir(target, request.user_home)
        # Every startup file a shell would run from the home: its place is held by an empty
        # directory, before the OS layer's rules name what is there.
        shell_startup.hold(request.user_home)
    if own_temp is not None:
        # The binary keeps the session's temporary files here, its background commands' output
        # among them, and not in the directory every session of the user shares (``TMPDIR`` was
        # measured to move nothing).
        spawn_env["CLAUDE_CODE_TMPDIR"] = own_temp
    if request.profile in OWN_TEMP_PROFILES:
        # No command goes to the background, by any route the binary offers (asked for, past its
        # timeout, or on its own): its output would be left in the session's own temporary
        # directory for a Read, and no file tool reads there (see ``paths._rules``).
        spawn_env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    temp = request.os_layer_temp_dir
    if temp is not None:
        readable = request.os_layer_readable
        if config.survivor_reaper:
            # Nothing a command starts outlives it: the reaper runs as each sandboxed
            # command's first process, named by the shell prefix, and must be readable there.
            if not request.spawns_with_canary:
                msg = (
                    "a session with the survivor reaper must be spawned with its canary "
                    f"exported ({reaper_install.CANARY_EXPORT.strip()} before the exec of the "
                    "binary, as the dispatcher's held spawn does); this spawner does not say so"
                )
                raise ValueError(msg)
            reaper_dir = reaper_install.place(
                target, config.installation.base_prefix, target / SETTINGS_NAME
            )
            readable = (*readable, str(reaper_dir))
            spawn_env.update(reaper_install.spawn_env(reaper_dir))
        _make_file_tool_dirs(request.worktree)
        policy = sandbox_policy(
            config,
            home=request.user_home,
            temp_dir=temp,
            readable=readable,
            shared_temp=shared_temp_dirs(),
            claude_temp=request.shared_claude_temp,
            network=request.os_layer_network,
        )
        _merge(settings, policy.settings)
    _require_denied(settings, config.profile)
    settings_path = target / SETTINGS_NAME
    settings_path.write_bytes(_dump(settings))
    unenforced = (
        f"{NETWORK_UNENFORCED}: no OS layer was installed (no --os-layer-temp was given)"
        if request.os_layer_network == "none" and temp is None
        else None
    )
    return Installed(
        settings_path=settings_path,
        config_path=config_path,
        spawn_args=("--setting-sources", "", "--settings", str(settings_path)),
        spawn_env=spawn_env,
        network_unenforced=unenforced,
    )
