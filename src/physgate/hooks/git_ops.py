"""Refuse the git operations no agent session may run.

Refused for every profile: a force push in any spelling, skipping the
repository's own hooks in any spelling, a hard reset that could move anything
but the session's own branch within its own history, a rebase, forcing or
deleting a branch, writing a ref directly, and changing git's hook path or
aliases. Refused for a role session as well: any push at all, because the
orchestrator merges and pushes.

A rebase is refused outright. The rule it implements permits a rebase only onto
the session's own branch, which rewrites nothing, and the orchestrator owns
every merge, so there is no rebase a session needs.

Only commands are matched, never text: the parser hands over each simple
command, including those inside substitutions, subshells and ``sh -c``, and a
check looks at a command only when git is in command position. A document or a
commit message that names a forbidden flag is text and passes.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import ShellSyntaxError, SimpleCommand, parse, unwrap

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

FORCE_PUSH = (
    "Force-pushing is refused: it rewrites history other sessions have built on. "
    "Push without forcing, or leave the push to the orchestrator."
)
SKIP_HOOKS = (
    "Skipping the repository's own hooks is refused: those hooks are part of what "
    "checks the work. Run the command without that flag."
)
HOOK_CONFIG = (
    "Changing git's hook path or its aliases is refused: either would change what "
    "later git commands do without the command saying so."
)
ROLE_PUSH = "A role session does not push. The orchestrator merges and pushes finished work."
HARD_RESET = (
    "A hard reset is refused unless it only moves this session's own branch within "
    "its own history (to HEAD, HEAD~n or HEAD^), with nothing earlier in the command "
    "switching branches."
)
REBASE = "Rebasing is refused: it rewrites commits, and the orchestrator owns every merge."
REF_WRITE = (
    "Forcing, deleting or moving a branch, or writing a ref directly, is refused: "
    "it moves history other sessions may depend on."
)
UNPARSEABLE = (
    "This command could not be split into the commands it would run ({detail}), "
    "so it is refused. Simplify the quoting and try again."
)
DYNAMIC_GIT = (
    "This git command takes part of itself from a variable or a substitution, so "
    "what it would do cannot be checked. Write the command out in full."
)

_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
#: Options whose next word is a value, not a flag: a message that is exactly a
#: forbidden flag is a message.
_VALUE_OPTIONS = {"-m", "--message", "-F", "--file", "-C", "-c", "-t", "--template", "--author"}
_VALUE_LETTERS = set("mFCctS")
_HEAD_MOVERS = {"checkout", "switch", "symbolic-ref"}
_WATCHED = {"push", "commit", "reset", "rebase", "config", "merge", "am", "branch", "update-ref"}


def _is_git(word: str) -> bool:
    return word.rsplit("/", 1)[-1] == "git"


def _mentions_hooks_path(text: str) -> bool:
    return "hookspath" in text.lower()


def _split_git(argv: tuple[str, ...]) -> tuple[list[str], str, list[str]]:
    """``git [globals] <sub> [rest]`` into its three parts."""
    globals_: list[str] = []
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        globals_.append(argv[i])
        if argv[i] in _GLOBAL_WITH_VALUE and i + 1 < len(argv):
            globals_.append(argv[i + 1])
            i += 1
        i += 1
    sub = argv[i] if i < len(argv) else ""
    return globals_, sub, list(argv[i + 1 :])


def _flags(rest: list[str]) -> list[str]:
    """The flag words of ``rest``, skipping the values of options that take one."""
    flags, skip = [], False
    for word in rest:
        if skip:
            skip = False
            continue
        if word == "--":
            break
        if word in _VALUE_OPTIONS:
            skip = True
        if word.startswith("-"):
            flags.append(word)
    return flags


def _short_cluster_has(flag: str, letter: str) -> bool:
    """True if a short-option cluster sets ``letter`` before any value-taking letter."""
    if not flag.startswith("-") or flag.startswith("--"):
        return False
    for ch in flag[1:]:
        if ch == letter:
            return True
        if ch in _VALUE_LETTERS:
            return False
    return False


def _current_branch(cwd: str) -> str | None:
    """The branch HEAD names in the repository containing ``cwd``, read without git."""
    directory = os.path.abspath(cwd)
    while True:
        dot_git = os.path.join(directory, ".git")
        if os.path.isfile(dot_git):
            with open(dot_git) as handle:
                pointer = handle.read().strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = pointer.removeprefix("gitdir:").strip()
            git_dir = git_dir if os.path.isabs(git_dir) else os.path.join(directory, git_dir)
        elif os.path.isdir(dot_git):
            git_dir = dot_git
        else:
            parent = os.path.dirname(directory)
            if parent == directory:
                return None
            directory = parent
            continue
        with open(os.path.join(git_dir, "HEAD")) as handle:
            head = handle.read().strip()
        return head.removeprefix("ref: refs/heads/") if head.startswith("ref: ") else None


def _head_relative(ref: str) -> bool:
    if ref in ("HEAD", "@"):
        return True
    base = ref.split("~", 1)[0].split("^", 1)[0]
    return base in ("HEAD", "@") and ref != base


def check_command(
    cmd: SimpleCommand, config: ConfigView, cwd: str, head_moved_earlier: bool
) -> str | None:
    """The reason ``cmd`` is refused, or ``None``."""
    if any(_mentions_hooks_path(a) for a in cmd.assignments):
        return HOOK_CONFIG
    argv = unwrap(cmd.argv)
    if not argv:
        return None
    offset = len(cmd.argv) - len(argv)
    if offset in cmd.dynamic:
        return DYNAMIC_GIT if any(word in _WATCHED for word in argv) else None
    if not _is_git(argv[0]):
        return None
    if any(offset + n in cmd.dynamic for n in range(1, len(argv))):
        return DYNAMIC_GIT
    globals_, sub, rest = _split_git(argv)
    if any(_mentions_hooks_path(g) for g in globals_) or any(
        g.startswith("--config-env") for g in globals_
    ):
        return HOOK_CONFIG
    flags = _flags(rest)
    if "--no-verify" in flags:
        return SKIP_HOOKS
    if sub == "config" and any(_mentions_hooks_path(w) or w.startswith("alias.") for w in rest):
        return HOOK_CONFIG
    if sub == "commit" and any(_short_cluster_has(f, "n") for f in flags):
        return SKIP_HOOKS
    if sub == "push":
        force = {"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete"}
        if (
            any(f in force or f.split("=", 1)[0] in force for f in flags)
            or any(_short_cluster_has(f, "f") or _short_cluster_has(f, "d") for f in flags)
            or any(w.startswith(("+", ":")) for w in rest if not w.startswith("-"))
        ):
            return FORCE_PUSH
        if config.profile == "role":
            return ROLE_PUSH
    if sub == "reset" and "--hard" in flags:
        refs = [w for w in rest if not w.startswith("-")]
        own = config.own_branch
        if (
            head_moved_earlier
            or any(g == "-C" for g in globals_)
            or own is None
            or _current_branch(cwd) != own
            or not all(_head_relative(r) for r in refs)
        ):
            return HARD_RESET
    if sub == "rebase" and flags != ["--abort"]:
        return REBASE
    if sub == "update-ref" or (
        sub == "branch"
        and any(
            f in ("--force", "--delete", "--move", "--copy")
            or any(_short_cluster_has(f, x) for x in "fdDmMcC")
            for f in flags
        )
    ):
        return REF_WRITE
    return None


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a Bash call that runs a forbidden git operation anywhere in it."""
    if hook_input.tool_name != "Bash":
        return ALLOW
    command = (hook_input.tool_input or {}).get("command")
    if not isinstance(command, str):
        return refuse("A Bash call without a command string cannot be checked, so it is refused.")
    try:
        commands = parse(command)
    except ShellSyntaxError as exc:
        return refuse(UNPARSEABLE.format(detail=exc))
    cwd = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    head_moved = False
    for cmd in commands:
        reason = check_command(cmd, config, cwd, head_moved)
        if reason is not None:
            return refuse(reason)
        argv = unwrap(cmd.argv)
        if argv and _is_git(argv[0]) and _split_git(argv)[1] in _HEAD_MOVERS:
            head_moved = True
    return ALLOW


HOOK = HookSpec("git_ops", {"PreToolUse": pre_tool_use})
