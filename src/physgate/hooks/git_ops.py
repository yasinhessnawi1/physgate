"""Refuse the git operations no agent session may run.

A role session runs no git at all: the orchestrator commits, merges and pushes
its work. Any git the hook can see in a role's command is refused, under
whatever name or wrapper it is run.

Refused for every profile: a force push in any spelling, skipping the
repository's own hooks in any spelling, a hard reset that could move anything
but the session's own branch within its own history, a rebase, forcing or
deleting a branch, writing a ref directly, and changing git's hook path, its
aliases or its includes.

A rebase is refused outright. The rule it implements permits a rebase only onto
the session's own branch, which rewrites nothing, and the orchestrator owns
every merge, so there is no rebase a session needs.

Only commands are matched, never text: the parser hands over each simple
command, including those inside substitutions, subshells and ``sh -c``, and a
check looks at a command only when git is in command position. A document or a
commit message that names a forbidden flag is text and passes.

A git that another program runs is still a command: behind a reserved word
(``{``, ``if``, ``then``, ``!``), behind a program that runs its arguments
(``timeout 5 git …``, ``sudo -u x git …``), handed over as a string (``trap``,
``watch``, ``su -c``), by its dashed name (``git-push``) or by zsh's ``=git``.
Among the words of a program that may only be printing them (``grep git …``) it
is held to the forms refused outright, and for a role to naming a git command.
A word the shell expands into others (a glob, ``{a,b}``) is refused in a git
command, because git would not get the word that was checked.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import (
    SHELLS,
    ShellSyntaxError,
    SimpleCommand,
    command_key,
    parse,
    unwrap,
)

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
ROLE_NO_GIT = (
    "A role session does not run git: the orchestrator commits, merges and pushes the work "
    "a role leaves in its worktree. Leave the files as they should be committed."
)
ROLE_GIT_VARIABLE = (
    "A role session does not set the variables that tell git what to read (GIT_CONFIG*, "
    "HOME, XDG_CONFIG_HOME, GIT_DIR or another repository variable): a role runs no git, and "
    "the value would hold for whatever ran git later in the same shell."
)
#: Variables that tell git where its user configuration file is. A ``GIT_CONFIG*`` variable
#: sets keys or names a file outright.
_CONFIG_HOME_VARIABLES = frozenset({"HOME", "XDG_CONFIG_HOME"})
#: Variables that point git at another repository, or at another index or object store.
_REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }
)
#: Global options that point git at another repository (each also spelt ``--opt=value``).
_REPOSITORY_GLOBALS = ("-C", "--git-dir", "--work-tree", "--bare", "--namespace")
#: Configuration keys that make git run something, or read more configuration, for every
#: profile: the hook path, an alias, and an include (whose file can set either). Matched in
#: any case, as git matches section and key names.
_EXEC_CONFIG = re.compile(r"hookspath|(?<![a-z0-9_-])(alias|include|includeif)\.")
#: git's own commands (builtins and those it ships), measured with
#: ``git --list-cmds=builtins,main`` on git 2.54. Among another program's words, ``git``
#: followed by one of these is taken as a git command for a role, not as text.
_GIT_COMMANDS = frozenset(
    """
    add am annotate apply archimport archive backfill bisect blame branch bugreport bundle
    cat-file check-attr check-ignore check-mailmap check-ref-format checkout checkout--worker
    checkout-index cherry cherry-pick clean clone column commit commit-graph commit-tree config
    count-objects credential credential-cache credential-cache--daemon credential-netrc
    credential-osxkeychain credential-store cvsexportcommit cvsimport cvsserver daemon describe
    diagnose diff diff-files diff-index diff-pairs diff-tree difftool difftool--helper
    fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref
    for-each-repo format-patch fsck fsck-objects fsmonitor--daemon gc get-tar-commit-id grep
    hash-object help history hook http-backend http-fetch http-push imap-send index-pack init
    init-db instaweb interpret-trailers jump last-modified log ls-files ls-remote ls-tree
    mailinfo mailsplit maintenance merge merge-base merge-file merge-index merge-octopus
    merge-one-file merge-ours merge-recursive merge-recursive-ours merge-recursive-theirs
    merge-resolve merge-subtree merge-tree mergetool mktag mktree multi-pack-index mv name-rev
    notes p4 pack-objects pack-redundant pack-refs patch-id pickaxe prune prune-packed pull
    push quiltimport range-diff read-tree rebase receive-pack reflog refs remote remote-ext
    remote-fd remote-ftp remote-ftps remote-http remote-https repack replace replay repo
    request-pull rerere reset restore rev-list rev-parse revert rm send-email send-pack
    sh-i18n--envsubst shell shortlog show show-branch show-index show-ref sparse-checkout stage
    stash status stripspace submodule submodule--helper subtree switch symbolic-ref tag
    unpack-file unpack-objects update-index update-ref update-server-info upload-archive
    upload-archive--writer upload-pack var verify-commit verify-pack verify-tag version
    web--browse whatchanged worktree write-tree
    """.split()  # noqa: SIM905 - git's own listing, kept in the layout git prints it
)
#: Programs that run the command they are given, beyond the wrappers the parser steps over.
#: A git, a shell or a wrapper found among their words is checked as a command in its own
#: right. Among any other program's words it is checked only for the forms refused outright,
#: since it may as well be text (``grep git …``).
_RUNNERS = frozenset(
    {
        "timeout", "xargs", "parallel", "find", "stdbuf", "setsid", "ionice", "taskset",
        "chrt", "caffeinate", "flock", "watch", "unbuffer", "script", "doas", "chroot", "su",
        "runuser", "strace", "ltrace", "uv", "uvx", "npx", "pipx", "poetry", "pdm", "hatch",
    }
)  # fmt: skip
#: Words that start a command a check must look at, wherever they appear among another's words.
_STARTS = frozenset({"git", "env", "eval", "command", "exec", "nohup", "time", "builtin"})
#: Programs that run a command given to them as one string: after ``-c`` (``su``,
#: ``runuser``, ``script``, ``flock``), as all their words (``watch``), or as their first
#: (``trap``, which runs it later in the same shell).
_C_STRING_RUNNERS = frozenset({"su", "runuser", "script", "flock"})
#: Commands that change the directory later commands in the same shell run in.
_DIRECTORY_MOVERS = frozenset({"cd", "pushd", "popd"})
#: Shell builtins that set a variable named in their arguments (``export NAME=value``).
_DECLARERS = frozenset({"export", "declare", "typeset", "readonly", "local"})
ROLE_OPAQUE_ENV = (
    "A role session runs `env` only to set or unset variables for a command. Its other options "
    "(-S, -C, an emptied environment with variables set, or one this cannot read) change what "
    "runs in a way that cannot be checked, so they are refused. Write the command out in full."
)
ROLE_SHELL_STDIN = (
    "A role session does not hand a shell its commands on standard input (`… | sh`, `bash -s`, "
    "a shell with no script or -c): what it would run cannot be checked. Write the commands "
    "out, or use `sh -c '…'`."
)
ROLE_SHELL_ALIAS = (
    "A role session does not define shell aliases: an alias turns a later word into a command "
    "that cannot be checked. Write the command out in full."
)
EXPANDING_GIT = (
    (
        "This git command has a word the shell expands before git sees it (an unquoted *, ?, [ or "
        "{{a,b}} pattern), so what git would run cannot be checked: a file name or an expansion "
        "could become an option or a subcommand. Quote the word, or write the names out."
    )
    .replace("{{", "{")
    .replace("}}", "}")
)
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
#: Options whose next word is a value, not a flag, in the subcommands checked here: a message
#: that is exactly a forbidden flag is a message. Per subcommand, because the same letter is a
#: flag elsewhere (``git am -m`` and ``git branch -t`` take no value), and a word skipped as a
#: value that git reads as a flag is a flag the checks never see. An option missing here only
#: makes a check stricter.
_VALUE_OPTIONS = {
    "commit": frozenset(
        {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message"}
        | {"-t", "--template", "--author"}
    ),
    "merge": frozenset({"-m", "--message", "-F", "--file", "-s", "--strategy", "-X"}),
    "push": frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"}),
    "branch": frozenset({"-u", "--set-upstream-to"}),
}
#: The short options of each subcommand whose value may follow in the same word (``-mtext``).
_VALUE_LETTERS = {"commit": "mFCctS", "merge": "mFsXS", "push": "o", "branch": "u"}
_HEAD_MOVERS = {"checkout", "switch", "symbolic-ref"}
#: Subcommands that push: ``send-pack`` and ``http-push`` are the plumbing under ``push``.
_PUSHERS = frozenset({"push", "send-pack", "http-push"})
#: Configuration that makes a plain push a forcing or deleting one.
_PUSH_CONFIG = re.compile(r"remote\.[^=\s]*\.(push|mirror)\b|^push\.default\b")
#: The forbidden long options, each matched spelt out or abbreviated (``_names``).
_SKIP_HOOKS_LONG = ("--no-verify",)
_FORCE_PUSH_LONG = (
    *("--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete"),
    "--prune",
)
#: Reset modes that move the branch and rewrite the working tree to match: ``--keep`` and
#: ``--merge`` move it as ``--hard`` does, keeping only local changes.
_HARD_LONG = ("--hard", "--keep", "--merge")
_REF_WRITE_LONG = ("--force", "--delete", "--move", "--copy")
_WATCHED = {"push", "commit", "reset", "rebase", "config", "merge", "am", "branch", "update-ref"}


def _is_git(word: str) -> bool:
    return command_key(word) == "git"


def _as_git(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """``argv`` as a ``git …`` command, or ``None`` if it runs no git.

    git's own programs can be run by their dashed names (``git-config edit``, from git's
    program directory or the path), and are the same commands as ``git config edit``; and
    zsh runs ``=git`` as the ``git`` found on the path.
    """
    if not argv:
        return None
    # zsh replaces a word ``=name`` with the path of the command ``name``.
    name = command_key(argv[0].removeprefix("="))
    if name == "git":
        return argv
    if name.startswith("git-") and len(name) > 4:
        return ("git", name[4:], *argv[1:])
    return None


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


def _flags(sub: str, rest: list[str]) -> list[str]:
    """The flag words of ``rest``, skipping the values of ``sub``'s options that take one."""
    values = _VALUE_OPTIONS.get(sub, frozenset())
    flags, skip = [], False
    for word in rest:
        if skip:
            skip = False
            continue
        if word == "--":
            break
        if word in values:
            skip = True
        if word.startswith("-"):
            flags.append(word)
    return flags


def _assigned(cmd: SimpleCommand) -> list[str]:
    """Every ``NAME=value`` the command sets: before it, through a wrapper, or by ``export``.

    A variable set before the command (``A=1 git …``) or alone (``A=1``) is in the parser's
    assignments; one handed to a wrapper (``env A=1 git …``) is a word ``unwrap`` steps over;
    and ``export``, ``declare`` and the like set the variables named in their arguments.

    Not seen, and left so knowingly: a variable set by ``read``, ``printf -v``, ``mapfile``,
    or by a file run with ``source``/``.``, and a name built at run time
    (``export "$NAME=…"``). These are not refused, because no check here can read them.
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
    and ``XDG_CONFIG_HOME`` move the user configuration file; the repository variables point
    git at another repository. A role runs no git, but a value set here would hold for any git
    run later in the same shell by a means no check sees (a script), so it is refused.
    """
    names = [a.split("=", 1)[0] for a in assigned]
    if any(
        n.startswith("GIT_CONFIG") or n in _CONFIG_HOME_VARIABLES or n in _REPOSITORY_VARIABLES
        for n in names
    ):
        return ROLE_GIT_VARIABLE
    return None


def _sets_exec_config(assigned: list[str]) -> bool:
    """Whether a variable sets the hook path (any variable), or an alias or include (git's own)."""
    for word in assigned:
        name, _, value = word.partition("=")
        if "hookspath" in word.lower():
            return True
        if name.startswith("GIT_CONFIG") and _EXEC_CONFIG.search(value.lower()):
            return True
    return False


def _sets_push_config(assigned: list[str]) -> bool:
    """Whether a ``GIT_CONFIG*`` variable sets a push refspec or mirroring for a remote."""
    return any(
        w.split("=", 1)[0].startswith("GIT_CONFIG") and _PUSH_CONFIG.search(w.lower())
        for w in assigned
    )


def _opaque_env(argv: tuple[str, ...]) -> bool:
    """Whether an ``env`` among the wrapper words uses an option whose effect is not visible.

    ``-u NAME`` and ``--unset=NAME`` remove a variable, and ``-i`` empties the environment;
    those are read. ``-S`` (a string split into a command), ``-C`` (another directory), ``-i``
    together with variables, and every other option are not.
    """
    i = 0
    while i < len(argv):
        if command_key(argv[i]) != "env":
            i += 1
            continue
        i += 1
        cleared = assigns = False
        while i < len(argv):
            word = argv[i]
            if word in ("-u", "--unset"):
                i += 2
            elif word.startswith("--unset="):
                i += 1
            elif word in ("-i", "--ignore-environment", "-"):
                cleared, i = True, i + 1
            elif _is_assignment(word):
                assigns, i = True, i + 1
            elif word.startswith("-"):
                return True
            else:
                break
        if cleared and assigns:
            return True
    return False


def _reads_stdin(argv: tuple[str, ...]) -> bool:
    """Whether a shell in command position takes its commands from standard input."""
    if not argv or command_key(argv[0]) not in SHELLS:
        return False
    words, operands, i = argv[1:], [], 0
    while i < len(words):
        word = words[i]
        i += 1
        if word in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 1  # its value is an option name or a file, not a script
        elif word.startswith(("-", "+")):
            if not word.startswith("--") and "c" in word[1:]:
                return False
            if not word.startswith("--") and "s" in word[1:]:
                return True
        else:
            operands.append(word)
    return not operands


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


def _short_cluster_has(sub: str, flag: str, letter: str) -> bool:
    """True if a short-option cluster sets ``letter`` before any of ``sub``'s value letters."""
    if not flag.startswith("-") or flag.startswith("--"):
        return False
    values = _VALUE_LETTERS.get(sub, "")
    for ch in flag[1:]:
        if ch == letter:
            return True
        if ch in values:
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
    cmd: SimpleCommand,
    config: ConfigView,
    cwd: str,
    head_moved_earlier: bool,
    *,
    position: str = "command",
) -> str | None:
    """The reason ``cmd`` is refused, or ``None``.

    ``position`` says how ``cmd`` was found: ``"command"`` where the shell runs it,
    ``"runner"`` among the words of a program that runs its arguments (``timeout 5 git …``),
    ``"text"`` among any other program's words, where it may be text (``grep git …``) and is
    held only to the forms refused outright, and for a role to naming a git command.
    """
    role = config.profile == "role"
    seen = position != "text"
    assigned = _assigned(cmd)
    if _sets_exec_config(assigned):
        return HOOK_CONFIG
    if _sets_push_config(assigned):
        return FORCE_PUSH
    if role and (reason := _role_environment_refusal(assigned)):
        return reason
    argv = unwrap(cmd.argv)
    offset = len(cmd.argv) - len(argv)
    if role and seen and _opaque_env(cmd.argv[: offset + 1]):
        return ROLE_OPAQUE_ENV
    if not argv:
        return None
    if role and seen and _reads_stdin(argv):
        return ROLE_SHELL_STDIN
    if role and seen and argv[0] == "alias" and any("=" in w for w in argv[1:]):
        return ROLE_SHELL_ALIAS
    if offset in cmd.dynamic:
        # A command named at run time may be git. A role runs none, so one whose first
        # word after its options is a git command is refused as git.
        if role and _split_git(argv)[1] in _GIT_COMMANDS:
            return ROLE_NO_GIT
        return DYNAMIC_GIT if any(word in _WATCHED for word in argv) else None
    as_git = _as_git(argv)
    if as_git is None:
        return None
    globals_, sub, rest = _split_git(as_git)
    if role and (seen or sub in _GIT_COMMANDS):
        return ROLE_NO_GIT
    if seen and any(offset + n in cmd.dynamic for n in range(1, len(argv))):
        return DYNAMIC_GIT
    if seen and any(offset + n in cmd.expanding for n in range(1, len(argv))):
        return EXPANDING_GIT
    redirected = any(g.split("=", 1)[0] in _REPOSITORY_GLOBALS for g in globals_) or any(
        a.split("=", 1)[0] in _REPOSITORY_VARIABLES for a in assigned
    )
    if any(_EXEC_CONFIG.search(g.lower()) for g in globals_) or any(
        _names(g, ("--config-env",)) for g in globals_
    ):
        return HOOK_CONFIG
    if any(_PUSH_CONFIG.search(g.lower()) for g in globals_):
        return FORCE_PUSH
    flags = _flags(sub, rest)
    if any(_names(f, _SKIP_HOOKS_LONG) for f in flags):
        return SKIP_HOOKS
    if sub == "config" and _config_changes_exec(rest):
        return HOOK_CONFIG
    if sub == "config" and any(_PUSH_CONFIG.search(w.lower()) for w in rest):
        return FORCE_PUSH
    if sub == "commit" and any(_short_cluster_has(sub, f, "n") for f in flags):
        return SKIP_HOOKS
    if sub in _PUSHERS and (
        any(_names(f, _FORCE_PUSH_LONG) for f in flags)
        or any(_short_cluster_has(sub, f, "f") or _short_cluster_has(sub, f, "d") for f in flags)
        or any(w.startswith(("+", ":")) for w in rest if not w.startswith("-"))
    ):
        return FORCE_PUSH
    if sub == "reset" and any(_names(f, _HARD_LONG) for f in flags):
        refs = [w for w in rest if not w.startswith("-")]
        own = config.own_branch
        if (
            head_moved_earlier
            or redirected
            or own is None
            or _current_branch(cwd) != own
            or not all(_head_relative(r) for r in refs)
        ):
            return HARD_RESET
    if sub == "rebase" and flags != ["--abort"]:
        return REBASE
    if sub == "update-ref" or _forces_a_branch(sub, rest, flags):
        return REF_WRITE
    return None


def _forces_a_branch(sub: str, rest: list[str], flags: list[str]) -> bool:
    """Whether a command forces, deletes, moves or copies a branch, by any subcommand.

    ``git branch`` with a forcing or deleting option; ``checkout -B``, ``switch -C`` and
    ``worktree add -B``, which reset a branch that exists to another commit; and a ``fetch``
    whose refspec forces (``+``) an update of a local branch.
    """
    if sub == "branch":
        return any(
            _names(f, _REF_WRITE_LONG) or any(_short_cluster_has(sub, f, x) for x in "fdDmMcC")
            for f in flags
        )
    if sub == "checkout":
        return any(_short_cluster_has(sub, f, "B") for f in flags)
    if sub == "switch":
        return any(_names(f, ("--force-create",)) or _short_cluster_has(sub, f, "C") for f in flags)
    if sub == "worktree":
        return any(_short_cluster_has(sub, f, "B") for f in flags)
    if sub == "fetch":
        return any(w.startswith("+") for w in rest if not w.startswith("-"))
    return False


def _config_changes_exec(rest: list[str]) -> bool:
    """Whether a ``git config`` names the hook path, an alias or an include, in any case.

    Renaming a section to (or from) ``core`` is counted too: it moves a section's keys, a
    hook path among them, into place without naming the key.
    """
    words = [w.lower() for w in rest]
    if any(_EXEC_CONFIG.search(w) or w in ("alias", "include", "includeif") for w in words):
        return True
    renames = any(w in ("rename-section", "--rename-section") for w in words)
    return renames and any(w.split(".", 1)[0] == "core" for w in words)


def _found_in(cmd: SimpleCommand, position: str) -> list[tuple[SimpleCommand, str]]:
    """Commands ``cmd`` runs that the parser did not hand over, each with how it was found.

    The string a shell found among another program's words runs (``timeout 5 sh -c '…'``),
    and the first git, shell or wrapper among ``cmd``'s own words (``timeout 5 git …``,
    ``sudo -u x git …``, ``{ git …; }`` is already stepped over by ``unwrap``). Each is checked
    in turn, and is searched the same way.
    """
    argv = unwrap(cmd.argv)
    offset = len(cmd.argv) - len(argv)
    found: list[tuple[SimpleCommand, str]] = []
    if not argv:
        return found
    head = command_key(argv[0])
    strings: list[str] = []
    if position != "command" and head == "eval":
        strings.append(" ".join(argv[1:]))
    elif position != "command" and head in SHELLS:
        for n, arg in enumerate(argv[1:], 1):
            if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
                strings += argv[n + 1 : n + 2]
                break
    elif head == "trap":
        strings += [w for w in argv[1:2] if not w.startswith("-")]
    elif head == "watch":
        strings.append(" ".join(w for w in argv[1:] if not w.startswith("-")))
    elif head in _C_STRING_RUNNERS:
        for n, arg in enumerate(argv[1:], 1):
            if arg in ("-c", "--command"):
                strings += argv[n + 1 : n + 2]
                break
            if arg.startswith("--command="):
                strings.append(arg.split("=", 1)[1])
                break
    for text in strings:
        found += [(c, "command") for c in parse(text)]
    inner = "runner" if head in _RUNNERS or position == "runner" else "text"
    for k in range(1, len(argv)):
        word = command_key(argv[k]).removeprefix("=")
        if word in _STARTS or word in SHELLS or word in _RUNNERS or word.startswith("git-"):
            start = offset + k
            tail = SimpleCommand(
                cmd.argv[start:],
                dynamic=frozenset(n - start for n in cmd.dynamic if n >= start),
                expanding=frozenset(n - start for n in cmd.expanding if n >= start),
            )
            found.append((tail, inner))
            break
    return found


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
    pending: list[tuple[SimpleCommand, str]] = [(c, "command") for c in commands]
    while pending:
        cmd, position = pending.pop(0)
        reason = check_command(cmd, config, cwd, head_moved, position=position)
        if reason is not None:
            return refuse(reason)
        argv = unwrap(cmd.argv)
        if argv and argv[0] in _DIRECTORY_MOVERS:
            # A reset is held to the branch checked out where the call started; after a
            # directory change it may act on another, so it is refused as a moved head is.
            head_moved = True
        as_git = _as_git(argv)
        if as_git is not None and _moves_head(as_git):
            head_moved = True
        try:
            pending[0:0] = _found_in(cmd, position)
        except ShellSyntaxError as exc:
            return refuse(UNPARSEABLE.format(detail=exc))
    return ALLOW


def _moves_head(argv: tuple[str, ...]) -> bool:
    """Whether a git command may leave HEAD, or the branch it names, somewhere else.

    Switching branches, and a reset of any mode to anything but HEAD's own history: a
    ``reset --soft main`` followed by ``reset --hard HEAD`` would otherwise move the branch
    to another history in two steps that each pass.
    """
    _, sub, rest = _split_git(argv)
    if sub in _HEAD_MOVERS:
        return True
    if sub == "reset":
        refs = [w for w in rest if not w.startswith("-")]
        return not all(_head_relative(r) for r in refs)
    return False


HOOK = HookSpec("git_ops", {"PreToolUse": pre_tool_use})
