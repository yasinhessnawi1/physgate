"""Shell commands that name a protected path are refused, before they run.

A Write hook proves nothing on its own: ``cat > gate/check.py <<EOF`` reaches
the gate without ever calling the Write tool. This is the first of two layers
against that. It is deliberately coarse, because a shell cannot be modelled
completely and a layer that pretends otherwise is the one that gets bypassed.
The second layer, a sentinel that compares every protected path before and
after each call, catches what this one does not see.

What this layer refuses, for every profile that has a shell:

- a command that **names** a protected path anywhere in it, unless the command
  only reads (``cat``, ``grep``, ``ls``, ``diff``, ``git diff`` and the like),
  and a command of any kind that names the held-out tier, which nothing reads, or
  that a reviewer runs naming a corpus that carries its own answers, or that any
  other session runs naming what only reviewers read;
- any output redirection into a protected path, whatever the command;
- running anything in the background: a write that lands after the call has
  returned lands after every check that could see it;
- starting Claude Code itself, however it is invoked: a nested session can be
  started with no hooks at all (measured with the bare flag and with a
  settings source that leaves the project out).

A path is found in a word and in every path-like token inside it (a token
ends at ``=``, a quote, a comma or a bracket), so the target of ``dd of=…`` and
a path inside ``python -c "open('…')"`` are both seen. Globs are expanded, ``~`` and plain
variables such as ``$HOME`` are expanded, a brace pattern is checked as every word
it becomes, and ANSI-C quoting arrives decoded from the splitter.

``cd`` is followed to every directory the command could be in. A ``cd`` may fail
(its target does not exist), may not run (after ``&&`` or ``||``), or may run in a
subshell that the next command does not share, and the splitter does not keep
those boundaries; so after ``cd x`` both the directory before it and ``x`` are
possible, and each later command is checked from each. ``cd old new``, which zsh
reads as a substitution in the working directory, adds that directory too.

A word is read the way the shell running it reads it, so that no difference between
the two can hide a path. A variable the call assigns is never read from the hook's
own environment: it may hold the inherited value or any literal value assigned, and
each is checked. ``cd`` alone follows ``HOME``, ``cd -`` and ``~-`` follow
``OLDPWD``, ``$PWD`` and ``~+`` are the directory judged from, and a relative ``cd``
is also looked up beneath each ``CDPATH`` entry. Where one of those is set to a value
known only at run time, or a named directory or ``cdable_vars`` sends ``cd`` where no
word says, that construct alone is refused. The splitter gives every shell's reading of
ANSI-C quoting and brace sequences, and refuses what they read too differently.

A here-document's body and a here-string are the program's input, and some
programs open the paths it names (``sqlite3``'s ``.import``), so they are scanned,
as written, as the command's own words: for a command that only reads, only what
may not even be named refuses; for any other, every protected path does.

The call's working directory is the hook's input, not the agent's command: one
that is not an absolute path is refused, since no relative word could be
resolved against it.

What a command's own text decides is resolved or refused, never skipped: a quoted
``$`` is a literal character, a word whose written prefix is already inside a root
is judged by that prefix, a variable that could hold too many values is refused,
``eval``'s line runs where it stands, ``chdir`` is ``cd``, ``$"…"`` is its string,
``~N`` is a directory the call has been in, ``~name`` is a user's or a
parameter's directory (refused where only running decides it), ``NAME+=`` appends,
``$_`` is a word before, ``${#x}`` and the default and trim forms of ``${…}`` are
evaluated (replacement, substring, case change and indirection are refused), and a
script read from ``/dev/stdin`` is parsed.

What is left, because only running the command decides it, is the residual. It is
left to the sentinel for the roots it puts back, and reaches a root watched
``none``; an OS write allowlist is the proposed closing layer:

- a value known only at run time: a command substitution, ``read``, ``$$`` and
  the other special parameters, positional parameters (``set --``, a function's
  arguments), arrays, namerefs and ``IFS``, a variable neither inherited nor
  assigned a value the call writes out;
- the directory after ``cd $(…)`` or ``cd "$(pwd)/…"``;
- a script a shell reads by another route: piped in (``… | sh``), run through
  ``xargs``, or a file given to ``source``;
- a path a program builds from its input (``python -``, ``node``, ``awk``,
  ``sqlite3``);
- whatever a file given to ``source`` sets: after one, no variable value is
  complete, and a ``cd`` through ``HOME`` or ``OLDPWD`` is refused.

A command name is one key for every rule (:func:`command_key`), and a reader is
trusted by its name only while the name means the usual program. An alias, a
function named like a command a rule trusts, ``hash -p``, ``enable`` and a shell
option that changes how words are read are refused, as rare. This list is the
boundary of what parsing alone can claim; the OS layer closes the rest.
"""

from __future__ import annotations

import fnmatch
import glob
import itertools
import os
import re
import stat
from typing import TYPE_CHECKING

from physgate.hooks.paths import protection, resolve_roots_once
from physgate.hooks.reasons import ANSWER_KEY_REASON, HELD_OUT_REASON, REVIEW_MATERIAL_REASON
from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import (
    BRACE_LIMIT,
    SHELLS,
    ShellSyntaxError,
    SimpleCommand,
    command_key,
    parse,
    unwrap,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from physgate.hooks.views import ConfigView, InputView

NAMES_PROTECTED = (
    "This command names {path}, which is protected: {reason}. A shell command may read "
    "protected files (cat, grep, head, ls, diff and the like) but may not otherwise name them."
)
REDIRECT_INTO = "This command redirects output into {path}, which is protected: {reason}."
FEEDS_PROTECTED = (
    "This command is fed text (a here-document or here-string) that names {path}, which is "
    "protected: {reason}. The program reads that text as its input, so it is judged as the "
    "command's own words. To write such text to a file, use cat > <file> <<'EOF'."
)
BACKGROUND = (
    "Running a command in the background is refused: a write that lands after the call "
    "returns lands after every check that could see it. Run it in the foreground."
)
NESTED_SESSION = (
    "Starting Claude Code from a session is refused: a nested session can be started "
    "without any of these hooks."
)
COMMIT_MESSAGE_ROUTE = (
    " To mention a protected path in a commit message, write the message to a file and "
    "commit with git commit -F <file>: the file's content is not read as part of the command."
)
UNKNOWN_CWD = (
    "This call's working directory ({cwd!r}) is not an absolute path, so no relative path in "
    "the command can be resolved against it, and the call is refused. The working directory "
    "comes from the tool call itself, not from the command."
)
BRACE_UNBOUNDED = (
    "This command writes, and its word {word} is a brace pattern that becomes more than "
    "{limit} words, too many to check each one, so it is refused. Write fewer alternatives, "
    "or use a loop."
)
CWD_UNBOUNDED = (
    "This command changes directory so many times that it could be in more than {limit} "
    "directories when a later part runs, too many to check each one, so it is refused. "
    "Split it into separate calls."
)
#: The most directories a command is checked from, after the ``cd`` commands in it.
CWD_LIMIT = 1024
#: The most words one word is checked as, after the variables the call assigns.
VARIABLE_LIMIT = 1024
CD_UNKNOWN = (
    "This command changes directory through {what}, which this call sets to a value known "
    "only when it runs, so where it lands cannot be known and it is refused. Set it to a "
    "literal value, or change directory by an explicit path."
)
VARIABLE_UNBOUNDED = (
    "This command uses {word}, whose variables could hold so many values that it becomes "
    "more than {limit} words, too many to check each one, so it is refused. Split the work "
    "into smaller loops or calls."
)
PARAMETER_FORM = (
    "This command uses {word}, a parameter expansion this layer does not evaluate "
    "(replacement, substring, case change or indirection), so where it leads cannot be "
    "checked and it is refused. Write the value out, or use a separate step."
)
TILDE_UNKNOWN = (
    "This command uses {word}, which zsh reads as a named directory or as a variable "
    "holding a path, and which directory that is cannot be known before it runs, so it is "
    "refused. Write the path out."
)
SHADOWED = (
    "This command defines {what}, after which a command name can run something other than "
    "what this layer judges it by, so it is refused. Call the program by its own name."
)
OPTION_REFUSED = (
    "This command sets a shell option ({what}) that changes how later words or directories "
    "are read, which this layer does not follow, so it is refused."
)
CD_OPTION = (
    "This command sets {what}, which makes a later cd go somewhere its words do not say, "
    "so it is refused. Change directory by an explicit path."
)
UNPARSEABLE = (
    "This command could not be split into the commands it would run ({detail}), so it is "
    "refused. Simplify the quoting and try again."
)

_READERS = {
    "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "wc", "diff",
    "cmp", "ls", "stat", "file", "sha256sum", "shasum", "md5", "md5sum", "du", "tree",
    "realpath", "readlink", "basename", "dirname", "test", "[", "true", "pwd", "echo",
}  # fmt: skip
_GIT_READERS = {"diff", "log", "show", "status", "blame", "ls-files", "grep", "rev-parse"}
#: Flags that turn a reader into a writer, or into something that runs a
#: program: with one of these, a command on the reader list names its output
#: file or its program as freely as any writer would, so it is checked as one.
_WRITING_FLAGS: dict[str, tuple[str, ...]] = {
    "find": (
        "-delete", "-exec", "-execdir", "-ok", "-okdir",
        "-fprint", "-fprint0", "-fprintf", "-fls",
    ),
    "git": ("--output", "-O", "--open-files-in-pager"),
    "tree": ("-o",),
    "less": ("-o", "-O", "--log-file", "--LOG-FILE"),
    "rg": ("--pre",),
    "file": ("-C",),
}  # fmt: skip
_BACKGROUNDERS = {"nohup", "setsid", "disown", "at", "batch", "crontab", "launchctl", "daemonize"}
_BACKGROUNDERS |= {"systemd-run", "screen", "tmux"}
_PACKAGE_RUNNERS = {"npx", "bunx", "pnpx"}
_WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
_PATHLIKE = re.compile(r"[\w.~$/{}*?\[\]-]*[\w.~/*?\]}-]")
_GLOB = re.compile(r"[*?\[]")


def _name(word: str) -> str:
    return command_key(word)


def _carries(word: str, flag: str) -> bool:
    """True if ``word`` is ``flag``, ``flag=value``, or a short flag with its value attached."""
    if word == flag or word.startswith(flag + "="):
        return True
    return len(flag) == 2 and not flag.startswith("--") and word.startswith(flag)


def _on_path(name: str) -> str | None:
    """The file the shell runs for ``name``, found on ``PATH`` (``shutil.which`` is heavy)."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory or ".", name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _is_the_named_command(word: str) -> bool:
    """True if ``word`` runs the program its name says.

    That is a bare name, or the very file the shell would find by that name: ``./cat``
    or ``/tmp/x/cat`` may be anything.
    """
    if "/" not in word:
        return True
    found = _on_path(command_key(word))
    return (
        os.path.isabs(word)
        and found is not None
        and os.path.realpath(word) == os.path.realpath(found)
    )


def _only_reads(argv: tuple[str, ...]) -> bool:
    if not _is_the_named_command(argv[0]):
        return False
    head = _name(argv[0])
    flags = _WRITING_FLAGS.get(head, ())
    if any(_carries(word, flag) for word in argv[1:] for flag in flags):
        return False
    if head in _READERS or head == "find":
        return True
    if head == "git":
        subs = [w for w in argv[1:] if not w.startswith("-")]
        return bool(subs) and subs[0] in _GIT_READERS
    return False


def _commits_with_inline_message(argv: tuple[str, ...]) -> bool:
    if not argv or _name(argv[0]) != "git":
        return False
    subs = [w for w in argv[1:] if not w.startswith("-")]
    if not subs or subs[0] != "commit":
        return False
    return any(
        w in ("-m", "--message") or w.startswith("--message=") or (w.startswith("-m") and w != "-m")
        for w in argv[1:]
    )


def _starts_claude(argv: tuple[str, ...]) -> bool:
    head = _name(argv[0]).casefold()
    if head.startswith("claude") or "/claude/versions/" in argv[0]:
        return True
    if head in _PACKAGE_RUNNERS or (head in ("pnpm", "yarn") and "dlx" in argv[1:3]):
        return any("claude" in word.casefold() for word in argv[1:4])
    return head == "node" and any("claude-code" in word.casefold() for word in argv[1:])


def _expand(word: str, dynamic: bool) -> str | None:
    """The word with ``~`` and plain variables expanded, or ``None`` if unknowable."""
    if dynamic:
        if "$(" in word or "`" in word or "<(" in word:
            return None
        word = os.path.expandvars(word)
        if "$" in word:
            return None
    return os.path.expanduser(word)


def _candidates(word: str, cwd: str) -> Iterator[str]:
    """Every path ``word`` could name, relative to ``cwd``."""
    seen: set[str] = set()
    parts = {word}
    if re.match(r"^-[A-Za-z].", word):
        # A short option with its value attached (`-o<file>`): the value is a
        # path on its own, and as one token with the flag it reaches nothing.
        parts.add(word[2:])
    for part in list(parts):
        parts.update(_PATHLIKE.findall(part))
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        if _GLOB.search(part):
            pattern = part if os.path.isabs(part) else os.path.join(cwd, part)
            matches = glob.glob(pattern)
            if not matches:
                # A file that does not exist yet, under a directory the pattern
                # does match: the write would land in that directory.
                parent, leaf = os.path.split(pattern)
                matches = [os.path.join(d, leaf) for d in glob.glob(parent)]
            yield from matches
            continue
        yield part


def _protected_names(config: ConfigView) -> set[str]:
    """The last component of every protected root and rule name, folded."""
    names = {os.path.basename(r.path.rstrip("/")).casefold() for r in config.protected_roots}
    names |= {os.path.basename(h.rstrip("/")).casefold() for h in config.held_out}
    names |= {os.path.basename(k.rstrip("/")).casefold() for k in config.answer_keys}
    names |= {os.path.basename(m.rstrip("/")).casefold() for m in config.review_material}
    for rule in config.experiments:
        names |= {
            os.path.basename(rule.root.rstrip("/")).casefold(),
            rule.frozen_marker.casefold(),
            rule.always_frozen_name.casefold(),
        }
    return names


def _cannot_reach(candidate: str, cwd: str, names: set[str], cwd_protected: bool) -> bool:
    """True for a plain word that cannot name a protected path from ``cwd``.

    The full check resolves a path against every protected root, which is the
    cost of this layer, and most words in a command are flags and program names.
    A word can reach a protected root only if it is absolute, carries a
    separator, a home or a parent reference, names a symlink, or is itself the
    name of a protected root or a rule's file; or if the working directory is
    protected already, when every relative word lands inside it. Anything else
    is a name inside an unprotected directory, and is skipped.
    """
    if cwd_protected or os.path.isabs(candidate) or "/" in candidate:
        return False
    if candidate.startswith("~") or ".." in candidate or candidate.casefold() in names:
        return False
    # A link, or a file with a second name, may be a protected file under this one: judged
    # in full, exactly as the file tools judge it.
    try:
        st = os.lstat(os.path.join(cwd, candidate))
    except OSError:
        return True
    return not (stat.S_ISLNK(st.st_mode) or (stat.S_ISREG(st.st_mode) and st.st_nlink > 1))


#: What may not even be named, by any command: a mention in a reader's input is enough.
_NAMED_ANYWHERE = frozenset({HELD_OUT_REASON, ANSWER_KEY_REASON, REVIEW_MATERIAL_REASON})


def _first_protected(
    words: Iterator[tuple[str, bool]],
    cwd: str,
    config: ConfigView,
    *,
    reading: bool,
    mention: bool = False,
    env: _Env | None = None,
) -> tuple[str, str] | None:
    """The first word that reaches a protected path from ``cwd``, and why.

    ``mention`` is for text a reader takes as input rather than as paths it opens: only
    what may not even be named counts there, not a reviewer's read allowance.
    """
    names = _protected_names(config)
    cwd_protected = protection(cwd, cwd, config, writing=not reading) is not None
    for word, dynamic in words:
        if env is None:
            one = _expand(word, dynamic)
            expansions = [] if one is None else [one]
        else:
            expansions = env.expand(word, dynamic, [cwd])
        readings = [(e, mention) for e in expansions]
        if dynamic and "$" in word:
            # The word as written: a quoted or escaped ``$`` is a literal character, and a
            # word whose written prefix is already inside a root reaches it whatever the
            # rest becomes. For a reader it is only a mention.
            readings.append((word, mention or reading))
        for expansion, only_named in readings:
            for candidate in _candidates(expansion, cwd):
                if _cannot_reach(candidate, cwd, names, cwd_protected):
                    continue
                reason = protection(candidate, cwd, config, writing=not reading)
                if reason is not None and not (only_named and reason not in _NAMED_ANYWHERE):
                    return candidate, reason
    return None


def _text_words(text: str) -> Iterator[tuple[str, bool]]:
    """Every path-like token in text a program reads, as written: nothing in it is expanded.

    A glob character in such text is literal, so a token is cut back to the directory
    written before its first glob character.
    """
    for token in _PATHLIKE.findall(text):
        glob_at = _GLOB.search(token)
        if glob_at is not None:
            head = token[: glob_at.start()]
            token = head[: head.rfind("/") + 1]
        if token:
            yield token, "$" in token


def _command_words(cmd: SimpleCommand) -> Iterator[tuple[str, bool]]:
    for n, word in enumerate(cmd.argv):
        yield word, n in cmd.dynamic
        for alternative in cmd.alternatives.get(n) or ():
            yield alternative, n in cmd.dynamic
    for assignment in cmd.assignments:
        yield assignment.partition("=")[2], "$" in assignment


def check(cmd: SimpleCommand, cwd: str, config: ConfigView, env: _Env | None = None) -> str | None:
    """Why ``cmd``, run from ``cwd``, is refused, or ``None``.

    ``env`` holds the values the call gives its variables so far; without it, a
    variable is read from the hook's own environment.
    """
    if cmd.background:
        return BACKGROUND
    argv = unwrap(cmd.argv)
    wrappers = cmd.argv[: len(cmd.argv) - len(argv)]
    if any(_name(w) in _BACKGROUNDERS for w in wrappers) or (
        argv and _name(argv[0]) in _BACKGROUNDERS
    ):
        return BACKGROUND
    if argv and _starts_claude(argv):
        return NESTED_SESSION
    ambiguous = _ambiguous_cd(cmd, cwd)
    if ambiguous is not None:
        return AMBIGUOUS_CD.format(path=ambiguous)
    # A reader is trusted by its name only while the name means the usual program: not
    # once the call has changed PATH, for this command or before it.
    path_set = any(
        w.partition("=")[0].removesuffix("+") in ("PATH", "path")
        for w in (*cmd.assignments, *wrappers)
    )
    trusted = not path_set and not (env is not None and env.path_changed())
    reads_only = bool(argv) and trusted and _only_reads(argv)
    for redirect in cmd.redirects:
        # A here-document's body and a here-string are the program's input: judged as its
        # own words, so a reader's input may still not name the held-out tier.
        fed = redirect.target if redirect.op == "<<<" else redirect.body
        if fed is not None:
            found = _first_protected(
                _text_words(fed), cwd, config, reading=reads_only, mention=reads_only, env=env
            )
            if found is not None:
                return FEEDS_PROTECTED.format(path=found[0], reason=found[1])
        writing = redirect.op in _WRITE_REDIRECTS or (
            redirect.op == ">&" and not redirect.target.isdigit() and redirect.target != "-"
        )
        if writing and redirect.alternatives is None:
            return BRACE_UNBOUNDED.format(word=redirect.target, limit=BRACE_LIMIT)
        dynamic = "$" in redirect.target
        targets = [(t, dynamic) for t in (redirect.target, *(redirect.alternatives or ()))]
        found = _first_protected(iter(targets), cwd, config, reading=not writing, env=env)
        if found is not None:
            template = REDIRECT_INTO if writing else NAMES_PROTECTED
            return template.format(path=found[0], reason=found[1])
    # Every word is resolved against the working directory, the command's own
    # name included, so a writing command run from inside a protected directory
    # is refused here without a separate rule for it.
    unbounded = next((n for n, b in cmd.alternatives.items() if b is None), None)
    if unbounded is not None and not reads_only:
        return BRACE_UNBOUNDED.format(word=cmd.argv[unbounded], limit=BRACE_LIMIT)
    found = _first_protected(_command_words(cmd), cwd, config, reading=reads_only, env=env)
    if found is not None:
        reason = NAMES_PROTECTED.format(path=found[0], reason=found[1])
        if _commits_with_inline_message(argv):
            reason += COMMIT_MESSAGE_ROUTE
        return reason
    return None


AMBIGUOUS_CD = (
    "This command changes directory to {path}, which is a different directory depending on "
    "whether the shell reads '..' after a symlink as written or as resolved; that cannot be "
    "known before it runs. Change directory by a path without a symlink before '..'."
)


def _cd_target(cmd: SimpleCommand) -> tuple[str, bool] | None:
    """The word a ``cd`` or ``pushd`` moves to, with whether it is dynamic, if ``cmd`` is one."""
    argv = unwrap(cmd.argv)
    if not argv or _name(argv[0]) not in _CHANGES_DIRECTORY:
        return None
    offset = len(cmd.argv) - len(argv)
    targets = [
        (w, offset + n + 1 in cmd.dynamic) for n, w in enumerate(argv[1:]) if not w.startswith("-")
    ]
    return targets[0] if targets else None


def _ambiguous_cd(cmd: SimpleCommand, cwd: str) -> str | None:
    """The destination of a ``cd`` whose written and resolved readings differ, if ``cmd`` is one."""
    found = _cd_target(cmd)
    if found is None:
        return None
    target = _expand(*found)
    if target is None:
        return None
    joined = target if os.path.isabs(target) else os.path.join(cwd, target)
    if os.path.realpath(os.path.normpath(joined)) != os.path.realpath(joined):
        return target
    return None


_ASSIGNERS = {"export", "declare", "typeset", "local", "readonly"}
_STDIN_SCRIPTS = {"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
#: ``set`` options that change nothing about which paths a command reaches.
_HARMLESS_SET_LETTERS = set("euxvCfanBhmbTE")
_HARMLESS_SET_NAMES = {
    "errexit", "nounset", "xtrace", "verbose", "noclobber", "noglob", "allexport", "noexec",
    "pipefail", "braceexpand", "hashall", "monitor", "notify", "errtrace", "functrace",
    "emacs", "vi", "history", "histexpand", "ignoreeof", "onecmd",
}  # fmt: skip
#: Commands that change the working directory: ``chdir`` is ``cd`` in zsh and dash.
_CHANGES_DIRECTORY = ("cd", "chdir", "pushd")
_READS_INTO = {"read", "mapfile", "readarray", "select"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _UnboundedError(Exception):
    """A word could become more than :data:`VARIABLE_LIMIT` words."""


class _UnknownTildeError(Exception):
    """A ``~name`` whose directory is known only at run time."""


class _UnresolvedParameterError(Exception):
    """A ``${…}`` form this layer does not evaluate, and which agents rarely write."""


#: Variables the shell sets itself: the hook's own value of one is never the shell's.
_SHELL_SET = frozenset(
    {
        "_", "RANDOM", "SRANDOM", "SECONDS", "EPOCHSECONDS", "EPOCHREALTIME", "LINENO",
        "BASHPID", "PPID", "SHLVL", "HISTCMD", "BASH_COMMAND", "BASH_SUBSHELL", "OPTIND",
        "OPTARG", "REPLY", "PIPESTATUS", "FUNCNAME", "BASH_SOURCE", "BASH_LINENO",
    }
)  # fmt: skip
#: ``${name<op>operand}`` for the operators this layer evaluates.
_PARAMETER_OP = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(:?[-=+?]|##?|%%?)(.*)", re.DOTALL)
#: Positional and special parameters, and arrays: values only running decides (the residual).
_PARAMETER_OPAQUE = re.compile(r"#?(?:[0-9]+|[@*#?$!-]|[A-Za-z_][A-Za-z0-9_]*\[.*\])", re.DOTALL)


def _trim(value: str, pattern: str, op: str) -> str:
    """``${value<op>pattern}`` for ``#``, ``##``, ``%`` and ``%%``, as bash trims."""
    n = len(value)
    if op in ("#", "##"):
        for i in range(n + 1) if op == "#" else range(n, -1, -1):
            if fnmatch.fnmatchcase(value[:i], pattern):
                return value[i:]
    else:
        for i in range(n, -1, -1) if op == "%" else range(n + 1):
            if fnmatch.fnmatchcase(value[i:], pattern):
                return value[:i]
    return value


class _Env:
    """The values a call could give each variable it assigns, as far as they are known.

    A variable the call never assigns is read from the hook's own environment, as the
    shell inherits it, except one the shell sets itself. One it assigns could hold the
    inherited value (the assignment may not run) or any value assigned; one assigned a
    value known only at run time (a substitution, ``read``) is incomplete: its known
    values are still checked, the rest is not known. One that could hold too many values
    to check is unbounded, and any word that uses it is refused. ``PWD`` is also every
    directory being judged from; ``OLDPWD`` is also every directory a ``cd`` left; ``_``
    is the last word of any command before.
    """

    __slots__ = ("drifted", "known", "unbounded", "unknown")

    def __init__(self) -> None:
        self.known: dict[str, set[str]] = {}
        self.unknown: set[str] = set()
        self.unbounded: set[str] = set()
        #: Set once the call runs something that can change any variable unseen (a file
        #: given to ``source``): no value is then complete, and no guess is kept.
        self.drifted = False

    def path_changed(self) -> bool:
        """True if the call may have changed which program a command name runs."""
        return any(n in self.known or n in self.unknown for n in ("PATH", "path"))

    def _holds(self, name: str) -> bool:
        """True if ``name`` has any value this layer knows of."""
        if name in self.known or name in self.unknown or name in self.unbounded:
            return True
        return name not in _SHELL_SET and name in os.environ

    def values(self, name: str, cwds: list[str]) -> tuple[list[str], bool]:
        """Every known value ``name`` could hold, and whether those are all of them.

        Raises:
            _UnboundedError: it could hold more values than can be checked.
        """
        if name in self.unbounded:
            raise _UnboundedError(name)
        known = set(self.known.get(name, set()))
        if name == "PWD":
            return sorted(known | set(cwds)), name not in self.unknown
        inherited = None if name in _SHELL_SET else os.environ.get(name)
        if inherited is not None:
            known.add(inherited)
        complete = name not in self.unknown and (inherited is not None or name in self.known)
        return sorted(known), complete and not self.drifted

    def cd_values(self, name: str) -> list[str] | None:
        """As :meth:`values` for a variable ``cd`` reads, where unset means unset: ``[]``.

        ``None`` if one of its values is known only at run time.
        """
        if name in self.unknown or (self.drifted and name in ("HOME", "OLDPWD")):
            return None
        if name in self.unbounded:
            raise _UnboundedError(name)
        inherited = os.environ.get(name)
        return sorted(self.known.get(name, set()) | ({inherited} if inherited else set()))

    def expand(self, word: str, dynamic: bool, cwds: list[str]) -> list[str]:
        """Every word ``word`` could become, as far as its parts are known.

        A part known only at run time (a substitution, ``$$``, a positional parameter, a
        variable with no known value) contributes nothing: what is returned is checked,
        the rest is the residual. Raises :class:`_UnboundedError` for more than
        :data:`VARIABLE_LIMIT` words, :class:`_UnknownTildeError` for a ``~name`` whose
        directory cannot be known, and :class:`_UnresolvedParameterError` for a ``${…}``
        form this layer does not evaluate.
        """
        return self._expand(word, dynamic, cwds)[0]

    def _expand(self, word: str, dynamic: bool, cwds: list[str]) -> tuple[list[str], bool]:
        if not dynamic:
            return self._tilde(word, cwds), True
        parts = self._parts(word, cwds)
        if parts is None:
            return [], False
        choices, complete = parts
        count = 1
        for choice in choices:
            count *= len(choice)
        if count > VARIABLE_LIMIT:
            raise _UnboundedError(word)
        out: list[str] = []
        for combination in itertools.product(*choices):
            out += self._tilde("".join(combination), cwds)
        return out, complete

    def _parts(self, word: str, cwds: list[str]) -> tuple[list[list[str]], bool] | None:
        """The word as a sequence of choices: literal text, and each reference's values.

        ``None`` if a part is a substitution, or a parameter only running decides.
        """
        if any(m in word for m in ("`", "$(", "<(", ">(")):
            return None
        choices: list[list[str]] = []
        complete = True
        text = ""
        i = 0
        while i < len(word):
            if word[i] != "$" or i + 1 == len(word):
                text += word[i]
                i += 1
                continue
            if word[i + 1] == "{":
                close = word.find("}", i + 2)
                if close < 0:
                    return None
                found = self._braced(word[i + 2 : close], cwds)
                i = close + 1
            elif match := _NAME.match(word, i + 1):
                found = self.values(match.group(), cwds)
                i = match.end()
            elif word[i + 1].isdigit() or word[i + 1] in "@*#?$!-":
                return None
            else:
                text += "$"  # a ``$`` before nothing a parameter can be named by is itself
                i += 1
                continue
            if found is None:
                return None
            choices += [[text], found[0]]
            complete = complete and found[1]
            text = ""
        return [*choices, [text]], complete

    def _braced(self, inner: str, cwds: list[str]) -> tuple[list[str], bool] | None:
        """``${inner}``'s possible values, ``None`` if only running decides them."""
        if _NAME.fullmatch(inner):
            return self.values(inner, cwds)
        if inner.startswith("#") and _NAME.fullmatch(inner[1:]):
            values, complete = self.values(inner[1:], cwds)
            return sorted({str(len(v)) for v in values}), complete
        if _PARAMETER_OPAQUE.fullmatch(inner):
            return None
        match = _PARAMETER_OP.fullmatch(inner)
        if match is None or "${" in inner:
            raise _UnresolvedParameterError("${" + inner + "}")
        name, op, operand = match.groups()
        values, complete = self.values(name, cwds)
        operands, known = self._expand(operand, "$" in operand, cwds)
        operands = sorted({*operands, operand})
        if op in (":-", "-", ":=", "="):
            if op in (":=", "="):
                self.known.setdefault(name, set()).update(operands)
            return sorted({*values, *operands}), complete and known
        if op in (":+", "+"):
            return sorted({*operands, ""}), known
        if op in (":?", "?"):
            return values, complete
        trimmed = {
            _trim(v, pattern, op)
            for v in values
            for o in operands
            for pattern in (o, re.sub(r"([*?\[])", r"[\1]", o))
        }
        return sorted(trimmed), complete and known

    def _tilde(self, word: str, cwds: list[str]) -> list[str]:
        head, sep, rest = word.partition("/")
        if not head.startswith("~"):
            return [word]
        if head == "~":
            return [h + sep + rest for h in self.values("HOME", cwds)[0]]
        if head == "~-":
            return [d + sep + rest for d in self.values("OLDPWD", cwds)[0]]
        if head == "~+" or re.fullmatch(r"~[+-]?\d+", head):
            # ``~+`` is the directory itself; ``~N``, ``~+N`` and ``~-N`` are entries of the
            # directory stack, each a directory this call has been in: every one is counted.
            return [d + sep + rest for d in self.values("PWD", cwds)[0]]
        name = head[1:]
        found: list[str] = []
        user = os.path.expanduser(head)
        if user != head:
            found.append(user)
        if _NAME.fullmatch(name) and self._holds(name):
            # zsh reads ``~name`` as the directory a parameter holds, before a user's.
            values, complete = self.values(name, cwds)
            if not complete:
                raise _UnknownTildeError(head)
            found += [v for v in values if v.startswith("/")]
        if not found:
            if re.fullmatch(r"[A-Za-z_][\w.-]*", name):
                raise _UnknownTildeError(head)  # a zsh named directory, or nothing
            return [word]
        if user == head:
            found.append(head)  # bash reads a name that is no user as written
        return [f + sep + rest for f in found]

    def _assignment_tildes(self, value: str, cwds: list[str]) -> list[str]:
        """``value`` with a ``~`` after each ``:`` expanded, as an assignment expands it."""
        segments = [self._tilde(s, cwds) if s.startswith("~") else [s] for s in value.split(":")]
        count = 1
        for segment in segments:
            count *= len(segment)
        if count > VARIABLE_LIMIT:
            raise _UnboundedError(value)
        return [":".join(c) for c in itertools.product(*segments)]

    def assign(self, name: str, value: str, dynamic: bool, cwds: list[str]) -> None:
        """Record that ``name`` may now hold ``value`` (appended to, for ``name+``)."""
        append = name.endswith("+")
        name = name.removesuffix("+")
        if name.casefold() == "cdpath" and name != "CDPATH":
            # zsh's array tied to CDPATH: its value is not this word.
            self.unknown.add("CDPATH")
            return
        try:
            found, complete = self._expand(value, dynamic, cwds)
            found = [t for f in found for t in self._assignment_tildes(f, cwds)]
            if dynamic:
                found = [*found, value]  # a quoted ``$`` is a literal character
            if append:
                before, known = self.values(name, cwds)
                complete = complete and known
                found = [b + f for b in (before or [""]) for f in found]
                if len(found) > VARIABLE_LIMIT:
                    raise _UnboundedError(name)
        except _UnboundedError:
            self.unbounded.add(name)
            return
        if not complete:
            self.unknown.add(name)
        self.known.setdefault(name, set()).update(found)

    def record(self, cmd: SimpleCommand, cwds: list[str]) -> None:
        """Every variable ``cmd`` may assign, and what it may assign."""
        for assignment in cmd.assignments:
            name, _, value = assignment.partition("=")
            self.assign(name, value, "$" in value, cwds)
        argv = unwrap(cmd.argv)
        if not argv:
            return
        head = _name(argv[0])
        if head in ("source", ".") and len(argv) > 1 and argv[1] not in _STDIN_SCRIPTS:
            self.drifted = True
        offset = len(cmd.argv) - len(argv)
        last = len(cmd.argv) - 1
        for word in (cmd.argv[last], *(cmd.alternatives.get(last) or ())):
            self.assign("_", word, last in cmd.dynamic, cwds)
        if head in _ASSIGNERS:
            for n, word in enumerate(argv[1:], offset + 1):
                name, eq, value = word.partition("=")
                if eq and _NAME.fullmatch(name.removesuffix("+")):
                    self.assign(name, value, n in cmd.dynamic, cwds)
        elif head == "for" and len(argv) > 1:
            name = argv[1]
            if len(argv) > 2 and argv[2] == "in":  # noqa: PLR2004 - `for NAME in ...`
                for n, word in enumerate(argv[3:], offset + 3):
                    if n in cmd.alternatives and cmd.alternatives[n] is None:
                        self.unbounded.add(name)
                        continue
                    for alternative in (word, *(cmd.alternatives.get(n) or ())):
                        self.assign(name, alternative, n in cmd.dynamic, cwds)
            else:
                self.unknown.add(name)
        elif head in _READS_INTO or head in ("getopts", "printf"):
            names = [w for w in argv[1:] if _NAME.fullmatch(w)]
            if head == "printf":
                names = [argv[k + 1] for k in range(1, len(argv) - 1) if argv[k] == "-v"]
            self.unknown.update(names)


def _registered_names() -> frozenset[str]:
    """Every command name a rule of this layer, or the splitter, gives a meaning to."""
    return frozenset(
        {
            *_READERS, *_WRITING_FLAGS, *_CHANGES_DIRECTORY, *_ASSIGNERS, *_READS_INTO,
            *_BACKGROUNDERS, *_PACKAGE_RUNNERS, *SHELLS, "git", "eval", "source", ".", "trap",
            "alias", "hash", "shopt", "setopt", "unsetopt", "set", "builtin", "command",
            "env", "exec", "nice", "time", "sudo", "for", "printf", "getopts", "popd",
            "enable", "unset", "claude", "node", "pnpm", "yarn",
        }
    )  # fmt: skip


def _changes_how_words_are_read(argv: tuple[str, ...]) -> str | None:
    """The shell option ``argv`` sets, if it changes how a later word or ``cd`` is read."""
    head = _name(argv[0])
    if head in ("setopt", "unsetopt") and len(argv) > 1:
        return f"{head} {' '.join(argv[1:])}"
    if head == "shopt" and any(w in ("-s", "-u") for w in argv[1:]):
        return f"shopt {' '.join(argv[1:])}"
    if head != "set":
        return None
    words = list(argv[1:])
    while words:
        word = words.pop(0)
        if word == "--":
            return None
        if word[:1] not in ("-", "+") or len(word) < 2:  # noqa: PLR2004 - a sign and a letter
            return None  # the positional parameters follow
        letters = word[1:]
        if not set(letters.replace("o", "")) <= _HARMLESS_SET_LETTERS:
            return f"set {word}"
        for _ in range(letters.count("o")):  # each ``o`` takes an option name
            name = words.pop(0) if words else ""
            if name and name.replace("_", "").casefold() not in _HARMLESS_SET_NAMES:
                return f"set {word} {name}"
    return None


def _refused_construct(cmd: SimpleCommand) -> str | None:
    """Why ``cmd`` is refused for changing how later words are read in a way not followed.

    A ``cd`` could then go where no word says (a named directory, ``cdable_vars``), a name
    could run another program (an alias, a function named like a command a rule trusts,
    a hashed path, a builtin turned off), or a word could expand otherwise (a shell
    option). Each is rare in an agent's commands; a guess would let a write through.
    """
    if cmd.argv[:1] == ("function",) and len(cmd.argv) > 1:
        name = _name(cmd.argv[1].removesuffix("()"))
        if name in _registered_names():
            return SHADOWED.format(what=f"a function named {name}")
    argv = unwrap(cmd.argv)
    if not argv:
        return None
    head = _name(argv[0])
    if head == "hash" and "-d" in argv[1:]:
        return CD_OPTION.format(what="a zsh named directory (hash -d)")
    if head == "hash" and "-p" in argv[1:]:
        return SHADOWED.format(what="a hashed path for a command (hash -p)")
    if head == "alias" and any("=" in w for w in argv[1:]):
        return SHADOWED.format(what="an alias")
    if head == "enable":
        return SHADOWED.format(what="enable, which turns builtins on or off")
    if any("cdablevars" in w.casefold().replace("_", "") for w in argv[1:]) and head in (
        "shopt", "setopt", "unsetopt", "set",
    ):  # fmt: skip
        return CD_OPTION.format(what="the cdable_vars option")
    option = _changes_how_words_are_read(argv)
    if option is not None:
        return OPTION_REFUSED.format(what=option)
    return None


class _UnknownDirectoryError(Exception):
    """A ``cd`` reads a variable whose value this call sets at run time."""


def _next_cwds(cmd: SimpleCommand, cwds: list[str], env: _Env | None = None) -> list[str]:
    """Every directory a later command could run in, after ``cmd`` from any of ``cwds``.

    Nothing is ever removed: a ``cd`` may fail, may not run, or may run in a subshell.
    ``cd`` alone goes to every value ``HOME`` could hold, ``cd -`` to every value of
    ``OLDPWD``, and a relative target is also looked up beneath every ``CDPATH`` entry,
    as bash and zsh do. ``popd`` and a ``pushd`` that only rotates the stack return to a
    directory already in the list. A target that cannot be expanded adds nothing.

    Raises:
        _UnknownDirectoryError: ``cd`` reads ``HOME``, ``OLDPWD`` or ``CDPATH`` and this
            call set it to a value known only at run time.
    """
    env = env if env is not None else _Env()
    argv = unwrap(cmd.argv)
    if not argv or _name(argv[0]) not in _CHANGES_DIRECTORY:
        return cwds
    offset = len(cmd.argv) - len(argv)
    # `pushd +2` rotates the stack; for cd, only a leading dash is an option.
    stack_flags = ("-", "+") if _name(argv[0]) == "pushd" else ("-",)
    words = [
        (n, w)
        for n, w in enumerate(argv[1:], offset + 1)
        if w == "-" or not w.startswith(stack_flags)
    ]
    found: list[str] = []
    if any(w == "-" for _, w in words):
        found = [os.path.join(cwd, v) for v in _cd_values(env, "OLDPWD") for cwd in cwds]
    elif not words and _name(argv[0]) == "cd":
        found = [os.path.join(cwd, v) for v in _cd_values(env, "HOME") for cwd in cwds]
    elif words:
        n, first = words[0]
        for alternative in (first, *(cmd.alternatives.get(n) or ())):
            for target in env.expand(alternative, n in cmd.dynamic, cwds):
                found += [os.path.join(cwd, target) for cwd in cwds]
                if not _cdpath_skips(target):
                    for entry in (e for v in _cd_values(env, "CDPATH") for e in v.split(":")):
                        found += [os.path.join(cwd, entry or ".", target) for cwd in cwds]
        if len(words) == 2:  # noqa: PLR2004 - zsh's `cd old new`
            old = _expand(words[0][1], words[0][0] in cmd.dynamic)
            new = _expand(words[1][1], words[1][0] in cmd.dynamic)
            if old and new is not None:
                found += [c.replace(old, new, 1) for c in cwds if old in c]
    env.known.setdefault("OLDPWD", set()).update(cwds)
    return list(dict.fromkeys([*cwds, *(os.path.normpath(f) for f in found)]))


def _cd_values(env: _Env, name: str) -> list[str]:
    values = env.cd_values(name)
    if values is None:
        raise _UnknownDirectoryError(name)
    return values


def _cdpath_skips(target: str) -> bool:
    """True for a target bash and zsh never look up in ``CDPATH``: absolute, or ``.``-led."""
    first = target.split("/", 1)[0]
    return target.startswith("/") or first in (".", "..")


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a Bash call that names a protected path, backgrounds, or starts Claude Code."""
    if hook_input.tool_name != "Bash":
        return ALLOW
    tool_input = hook_input.tool_input or {}
    if tool_input.get("run_in_background"):
        return refuse(BACKGROUND)
    command = tool_input.get("command")
    if not isinstance(command, str):
        return refuse("A Bash call without a command string cannot be checked, so it is refused.")
    try:
        commands = parse(command)
    except ShellSyntaxError as exc:
        return refuse(UNPARSEABLE.format(detail=exc))
    if not os.path.isabs(hook_input.cwd):
        return refuse(UNKNOWN_CWD.format(cwd=hook_input.cwd))
    cwds = [os.path.normpath(hook_input.cwd)]
    env = _Env()
    with resolve_roots_once():
        for cmd in commands:
            construct = _refused_construct(cmd)
            if construct is not None:
                return refuse(construct)
            try:
                env.record(cmd, cwds)
                for cwd in cwds:
                    reason = check(cmd, cwd, config, env)
                    if reason is not None:
                        return refuse(reason)
                cwds = _next_cwds(cmd, cwds, env)
            except _UnknownDirectoryError as exc:
                return refuse(CD_UNKNOWN.format(what=f"${exc.args[0]}"))
            except _UnboundedError as exc:
                return refuse(VARIABLE_UNBOUNDED.format(word=exc.args[0], limit=VARIABLE_LIMIT))
            except _UnknownTildeError as exc:
                return refuse(TILDE_UNKNOWN.format(word=exc.args[0]))
            except _UnresolvedParameterError as exc:
                return refuse(PARAMETER_FORM.format(word=exc.args[0]))
            if len(cwds) > CWD_LIMIT:
                return refuse(CWD_UNBOUNDED.format(limit=CWD_LIMIT))
    return ALLOW


HOOK = HookSpec("shell_paths", {"PreToolUse": pre_tool_use})
