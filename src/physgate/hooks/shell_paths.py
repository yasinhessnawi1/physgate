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
  and a command of any kind that names the held-out tier, which nothing reads;
- any output redirection into a protected path, whatever the command;
- any command run from inside a protected directory, unless it only reads;
- running anything in the background: a write that lands after the call has
  returned lands after every check that could see it;
- starting Claude Code itself, however it is invoked: a nested session can be
  started with no hooks at all (measured with the bare flag and with a
  settings source that leaves the project out).

A path is found in a word and in every path-like token inside it (a token
ends at ``=``, a quote, a comma or a bracket), so the target of ``dd of=…`` and
a path inside ``python -c "open('…')"`` are both seen. Globs are expanded, ``~`` and plain
variables such as ``$HOME`` are expanded, and ``cd`` is followed. A word built
from a command substitution cannot be known before it runs; that is left to
the sentinel.
"""

from __future__ import annotations

import glob
import os
import re
from collections.abc import Iterator

from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import protection
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, refuse
from physgate.hooks.shell import ShellSyntaxError, SimpleCommand, parse, unwrap

NAMES_PROTECTED = (
    "This command names {path}, which is protected: {reason}. A shell command may read "
    "protected files (cat, grep, head, ls, diff and the like) but may not otherwise name them."
)
REDIRECT_INTO = "This command redirects output into {path}, which is protected: {reason}."
INSIDE_PROTECTED = (
    "This command runs inside {path}, which is protected: {reason}. Only commands that read "
    "may run there."
)
BACKGROUND = (
    "Running a command in the background is refused: a write that lands after the call "
    "returns lands after every check that could see it. Run it in the foreground."
)
NESTED_SESSION = (
    "Starting Claude Code from a session is refused: a nested session can be started "
    "without any of these hooks."
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
_FIND_WRITERS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}
_BACKGROUNDERS = {"nohup", "setsid", "disown", "at", "batch", "crontab", "launchctl", "daemonize"}
_BACKGROUNDERS |= {"systemd-run", "screen", "tmux"}
_PACKAGE_RUNNERS = {"npx", "bunx", "pnpx"}
_WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
_PATHLIKE = re.compile(r"[\w.~$/{}*?\[\]-]*[\w.~/*?\]}-]")
_GLOB = re.compile(r"[*?\[]")


def _name(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _only_reads(argv: tuple[str, ...]) -> bool:
    head = _name(argv[0])
    if head in _READERS:
        return True
    if head == "find":
        return not any(word in _FIND_WRITERS for word in argv[1:])
    if head == "git":
        subs = [w for w in argv[1:] if not w.startswith("-")]
        return bool(subs) and subs[0] in _GIT_READERS
    return False


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


def _first_protected(
    words: Iterator[tuple[str, bool]], cwd: str, config: SessionConfig, *, reading: bool
) -> tuple[str, str] | None:
    for word, dynamic in words:
        expanded = _expand(word, dynamic)
        if expanded is None:
            continue
        for candidate in _candidates(expanded, cwd):
            reason = protection(candidate, cwd, config, writing=not reading)
            if reason is not None:
                return candidate, reason
    return None


def _command_words(cmd: SimpleCommand) -> Iterator[tuple[str, bool]]:
    for n, word in enumerate(cmd.argv):
        yield word, n in cmd.dynamic
    for assignment in cmd.assignments:
        yield assignment.partition("=")[2], "$" in assignment


def check(cmd: SimpleCommand, cwd: str, config: SessionConfig) -> str | None:
    """Why ``cmd``, run from ``cwd``, is refused, or ``None``."""
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
    for redirect in cmd.redirects:
        writing = redirect.op in _WRITE_REDIRECTS or (
            redirect.op == ">&" and not redirect.target.isdigit() and redirect.target != "-"
        )
        found = _first_protected(
            iter([(redirect.target, "$" in redirect.target)]), cwd, config, reading=not writing
        )
        if found is not None:
            template = REDIRECT_INTO if writing else NAMES_PROTECTED
            return template.format(path=found[0], reason=found[1])
    reads_only = bool(argv) and _only_reads(argv)
    if argv and not reads_only:
        inside = protection(cwd, cwd, config, writing=True)
        if inside is not None:
            return INSIDE_PROTECTED.format(path=cwd, reason=inside)
    found = _first_protected(_command_words(cmd), cwd, config, reading=reads_only)
    if found is not None:
        return NAMES_PROTECTED.format(path=found[0], reason=found[1])
    return None


def _next_cwd(cmd: SimpleCommand, cwd: str | None) -> str | None:
    """The working directory after ``cmd``: ``cd`` is followed, anything unknowable is None."""
    argv = unwrap(cmd.argv)
    if not argv or _name(argv[0]) not in ("cd", "pushd"):
        return cwd
    targets = [(w, n + 1 in cmd.dynamic) for n, w in enumerate(argv[1:]) if not w.startswith("-")]
    if not targets:
        return os.path.expanduser("~")
    target = _expand(*targets[0])
    if target is None or cwd is None:
        return None
    return os.path.normpath(os.path.join(cwd, target))


def pre_tool_use(hook_input: HookInput, config: SessionConfig) -> Decision:
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
    start = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    cwd: str | None = start
    for cmd in commands:
        # After a cd the shell cannot follow, relative words are still checked
        # against the directory the call started in; what that misses is the
        # sentinel's.
        reason = check(cmd, cwd or start, config)
        if reason is not None:
            return refuse(reason)
        cwd = _next_cwd(cmd, cwd)
    return ALLOW


HOOK = HookSpec("shell_paths", {"PreToolUse": pre_tool_use})
