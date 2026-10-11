"""Refuse the git operations no agent session may run.

Refused for every profile: a force push in any spelling, skipping the
repository's own hooks in any spelling, a hard reset that could move anything
but the session's own branch within its own history, a rebase, forcing or
deleting a branch, writing a ref directly, and changing git's hook path or
aliases. Refused for a role session as well: any push at all, because the
orchestrator merges and pushes; and any change to git's configuration or to where
git reads it from. A role may read its repository's configuration with the
``git config`` forms an allowlist names, and nothing else.

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
ROLE_CONFIG_WRITE = (
    "A role session does not set git's configuration, by any means. Any key it set — on the "
    "command line with -c, through a GIT_CONFIG_* variable, or with `git config` — could make "
    "a later git command run a program of the session's choosing. Reading a value "
    "(`git config --get <key>`, `--list`, or a bare key) is allowed; setting one is not."
)
ROLE_CONFIG_SOURCE = (
    "A role session reads git's configuration only from the repository's own sources, as git "
    "finds them. Pointing git at another file, blob, repository or home directory (--file, "
    "--blob, --includes, -C, --git-dir, or HOME or XDG_CONFIG_HOME set for the command) is "
    "refused: it could read a file the session may not open, or make a later git command run "
    "a program. Run `git config --get <key>` or `git config --list` as they are."
)
#: The ``git config`` forms a role session may run are the ones that read the repository's own
#: configuration sources. This is an allowlist, matched word by word, exactly as spelt: every
#: other form is refused, including an abbreviation git would accept, a short-option cluster,
#: a repeated option and a ``--`` separator, because a form that is not recognised cannot be
#: known to read. A denylist of write actions kept missing ways git can be told to set a key.
#:
#: git's subcommands (``git config list``), recognised by git only as the first word. The two
#: that read are admitted; the others set, remove, rename or open an editor on a config file.
_CONFIG_SUBCOMMANDS = frozenset(
    {"list", "get", "set", "unset", "rename-section", "remove-section", "edit"}
)
#: The older read actions, each with the fewest and most operands it takes.
_CONFIG_READ_ACTIONS = {
    "--get": (1, 2),
    "--get-all": (1, 2),
    "--get-regexp": (1, 2),
    "--get-urlmatch": (2, 2),
    "--get-color": (1, 2),
    "--get-colorbool": (1, 2),
    "--list": (0, 0),
}
#: Which configuration file is read: one of the repository's ordinary sources.
_CONFIG_SCOPES = frozenset({"--local", "--global", "--system", "--worktree"})
#: How what is read is shown or typed. None of them changes what is read or writes anything.
_CONFIG_MODIFIERS = _CONFIG_SCOPES | {
    "--null",
    "--name-only",
    "--show-origin",
    "--show-scope",
    "--show-names",
    "--bool",
    "--int",
    "--bool-or-int",
    "--bool-or-str",
    "--path",
    "--expiry-date",
}
#: The flags (no value) each form admits, by form: the older syntax, ``get`` and ``list``.
_CONFIG_FLAGS = {
    "": _CONFIG_MODIFIERS | set(_CONFIG_READ_ACTIONS) | {"--fixed-value"},
    "get": _CONFIG_MODIFIERS | {"--all", "--regexp", "--fixed-value"},
    "list": _CONFIG_MODIFIERS,
}
#: The options each form admits that take a value, as ``--opt=value`` or ``--opt value``.
_CONFIG_VALUED = {
    "": frozenset({"--type", "--default"}),
    "get": frozenset({"--type", "--default", "--value", "--url"}),
    "list": frozenset({"--type"}),
}
#: The short spellings admitted, each standing alone, by the long option it is.
_CONFIG_SHORT = {"-l": "--list", "-z": "--null", "-t": "--type"}
#: Options that read configuration from somewhere the command names instead of the
#: repository's own sources, matched spelt out or abbreviated; ``-f`` is ``--file``.
_CONFIG_ELSEWHERE = ("--file", "--blob", "--includes", "--no-includes")
#: The global options a role's ``git config`` read may carry: none of them changes which
#: repository or which configuration git reads.
_CONFIG_QUIET_GLOBALS = frozenset(
    {
        "-P",
        "--no-pager",
        "--no-replace-objects",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "--no-advice",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
    }
)
#: Variables that tell git where its user configuration file is. A ``GIT_CONFIG*`` variable
#: sets keys or names a file outright, and is refused as setting configuration.
_CONFIG_HOME_VARIABLES = frozenset({"HOME", "XDG_CONFIG_HOME"})
#: Shell builtins that set a variable named in their arguments (``export NAME=value``).
_DECLARERS = frozenset({"export", "declare", "typeset", "readonly", "local"})
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

#: git's global options whose value may be the next word. ``--attr-source`` and
#: ``--config-env`` take one too (measured, git 2.54): without them here, the value would be
#: taken for the subcommand, and the real subcommand would go unchecked.
_GLOBAL_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--attr-source",
    "--config-env",
}
#: Options whose next word is a value, not a flag: a message that is exactly a
#: forbidden flag is a message.
_VALUE_OPTIONS = {"-m", "--message", "-F", "--file", "-C", "-c", "-t", "--template", "--author"}
_VALUE_LETTERS = set("mFCctS")
_HEAD_MOVERS = {"checkout", "switch", "symbolic-ref"}
#: The forbidden long options, each matched spelt out or abbreviated (``_names``).
_SKIP_HOOKS_LONG = ("--no-verify",)
_FORCE_PUSH_LONG = ("--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete")
_HARD_LONG = ("--hard",)
_REF_WRITE_LONG = ("--force", "--delete", "--move", "--copy")
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


def _assigned(cmd: SimpleCommand) -> list[str]:
    """Every ``NAME=value`` the command sets: before it, through a wrapper, or by ``export``.

    A variable set before the command (``A=1 git …``) or alone (``A=1``) is in the parser's
    assignments; one handed to a wrapper (``env A=1 git …``) is a word ``unwrap`` steps over;
    and ``export``, ``declare`` and the like set the variables named in their arguments.
    """
    words = list(cmd.assignments)
    argv = unwrap(cmd.argv)
    words += [w for w in cmd.argv[: len(cmd.argv) - len(argv)] if _is_assignment(w)]
    if argv and argv[0] in _DECLARERS:
        words += [w for w in argv[1:] if _is_assignment(w)]
    return words


def _is_assignment(word: str) -> bool:
    """Whether ``word`` is ``NAME=value``, as the shell reads an assignment."""
    name, eq, _ = word.partition("=")
    return bool(eq) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def _role_environment_refusal(assigned: list[str]) -> str | None:
    """The reason a role session may not set these variables, or ``None``.

    A ``GIT_CONFIG*`` variable sets configuration (a key, or the file it is read from); ``HOME``
    and ``XDG_CONFIG_HOME`` move the user configuration file to one the session chose. Either
    holds for every later git command in the same shell, so it is refused wherever it is set.
    """
    names = [a.split("=", 1)[0] for a in assigned]
    if any(n.startswith("GIT_CONFIG") for n in names):
        return ROLE_CONFIG_WRITE
    if any(n in _CONFIG_HOME_VARIABLES for n in names):
        return ROLE_CONFIG_SOURCE
    return None


def _reads_elsewhere(word: str) -> bool:
    """Whether ``word`` is an option that reads configuration from a place the command names."""
    if word.startswith("-") and not word.startswith("--"):
        return "f" in word[1:]
    return _names(word, _CONFIG_ELSEWHERE)


def _without_elsewhere(words: list[str]) -> list[str]:
    """``words`` without the options that name another place to read, and their values.

    So the shape of a command can be judged apart from where it reads: a key and a value
    sent to a named file is still a write, and is refused as one.
    """
    kept: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        i += 1
        if word in ("--file", "-f", "--blob"):
            i += 1
        elif not _reads_elsewhere(word):
            kept.append(word)
    return kept


def _config_read_shape(form: str, words: list[str]) -> bool:
    """Whether ``words`` (after ``git config`` and any subcommand) is an admitted read.

    Every word is either an operand or one admitted option exactly as spelt, each option at
    most once, a value-taking option followed by its value. Then at most one read action and
    one scope, and as many operands as the form takes.
    """
    flags, valued = _CONFIG_FLAGS[form], _CONFIG_VALUED[form]
    seen: set[str] = set()
    operands: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        i += 1
        if word in _CONFIG_SUBCOMMANDS or word == "--":
            return False
        if not word.startswith("-") or word == "-":
            operands.append(word)
            continue
        name, eq, _ = word.partition("=")
        if not name.startswith("--"):
            if eq or name not in _CONFIG_SHORT:
                return False
            name = _CONFIG_SHORT[name]
        if name in seen:
            return False
        seen.add(name)
        if name in valued:
            if not eq:
                if i >= len(words) or words[i].startswith("-") or words[i] in _CONFIG_SUBCOMMANDS:
                    return False
                i += 1
        elif eq or name not in flags:
            return False
    actions = [a for a in _CONFIG_READ_ACTIONS if a in seen]
    if len(actions) > 1 or len(seen & _CONFIG_SCOPES) > 1:
        return False
    if form == "list":
        low, high = 0, 0
    elif form == "get" or not actions:
        low, high = 1, 1
    else:
        low, high = _CONFIG_READ_ACTIONS[actions[0]]
    return low <= len(operands) <= high


def _role_config_refusal(
    cmd: SimpleCommand, globals_: list[str], sub: str, rest: list[str]
) -> str | None:
    """The reason a role session may not run this git command for its configuration, or ``None``.

    Inline configuration (``-c``, ``--config-env``) sets keys, so it is refused on any
    subcommand; ``--config-env`` is already refused for every profile as a hook change and is
    named here too so the rule stands on its own. A ``git config`` command is admitted only as a
    read of the repository's own sources: a shape :func:`_config_read_shape` admits (else it is
    refused as a write, whatever it names), no variable set for it, no global option that moves
    git to another repository or file, and no option that reads a named file or blob. Anything
    else is refused, not passed.
    """
    if any(g == "-c" or _names(g, ("--config-env",)) for g in globals_):
        return ROLE_CONFIG_WRITE
    if sub != "config":
        return None
    form, words = ("", rest)
    if rest and rest[0] in ("list", "get"):
        form, words = rest[0], rest[1:]
    if not _config_read_shape(form, _without_elsewhere(words)):
        return ROLE_CONFIG_WRITE
    if (
        _assigned(cmd)
        or any(g not in _CONFIG_QUIET_GLOBALS for g in globals_)
        or any(_reads_elsewhere(w) for w in words)
    ):
        return ROLE_CONFIG_SOURCE
    return None


def _names(flag: str, options: tuple[str, ...]) -> bool:
    """True if ``flag`` is one of the long ``options``, spelt out or abbreviated.

    git accepts any unique prefix of a subcommand's long option, so
    ``git reset --har`` is a hard reset and ``git push --forc`` a force push.
    Any ``--word`` that begins one of ``options`` is taken as that option, a
    value after ``=`` ignored. That is stricter than git, which refuses a prefix
    two options share; such a command would fail in git anyway. git's global
    options, before the subcommand, take no abbreviation (measured, git 2.54).
    """
    name = flag.split("=", 1)[0]
    return name.startswith("--") and len(name) > 2 and any(o.startswith(name) for o in options)


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
    assigned = _assigned(cmd)
    if any(_mentions_hooks_path(a) for a in assigned):
        return HOOK_CONFIG
    if config.profile == "role" and (reason := _role_environment_refusal(assigned)):
        return reason
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
        _names(g, ("--config-env",)) for g in globals_
    ):
        return HOOK_CONFIG
    flags = _flags(rest)
    if any(_names(f, _SKIP_HOOKS_LONG) for f in flags):
        return SKIP_HOOKS
    if sub == "config" and any(_mentions_hooks_path(w) or w.startswith("alias.") for w in rest):
        return HOOK_CONFIG
    if config.profile == "role" and (reason := _role_config_refusal(cmd, globals_, sub, rest)):
        return reason
    if sub == "commit" and any(_short_cluster_has(f, "n") for f in flags):
        return SKIP_HOOKS
    if sub == "push":
        if (
            any(_names(f, _FORCE_PUSH_LONG) for f in flags)
            or any(_short_cluster_has(f, "f") or _short_cluster_has(f, "d") for f in flags)
            or any(w.startswith(("+", ":")) for w in rest if not w.startswith("-"))
        ):
            return FORCE_PUSH
        if config.profile == "role":
            return ROLE_PUSH
    if sub == "reset" and any(_names(f, _HARD_LONG) for f in flags):
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
            _names(f, _REF_WRITE_LONG) or any(_short_cluster_has(f, x) for x in "fdDmMcC")
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
