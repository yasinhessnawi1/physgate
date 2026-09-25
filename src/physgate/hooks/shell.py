"""Split a shell command into the simple commands it would run.

This is not a shell. It exists so that a check can look at *commands* — the word
in command position and its arguments — and never at text. A hook that matches
text refuses documents about the thing it forbids: this machine's own
commit-flag hook refused a heredoc that wrote a spec mentioning the flag.
So the body of a heredoc, a quoted argument to another program and a comment
are never words a check sees as a command, while a command substitution, a
subshell and the string handed to ``sh -c`` or ``eval`` are parsed as the
commands they are.

What it cannot model it refuses to guess about: an unterminated quote, a
substitution with no end, a heredoc with no terminator all raise, and the caller
refuses the call. A word whose value is only known at run time (a variable, a
substitution) is marked dynamic, so a check can refuse when the dynamic part is
the part that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from physgate.hooks.exceptions import UndecidableError

_SEPARATORS = ("&&", "||", "|&", ";;", ";", "|", "&", "\n", "(", ")")
_REDIRECTS = ("<<<", "<<-", "&>>", "<<", ">>", ">|", "<>", "&>", ">&", "<&", ">", "<")
#: Programs that run their arguments as a command.
_RUNS_ITS_ARGUMENTS = {"env", "command", "exec", "nohup", "time", "builtin", "sudo", "nice"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


class ShellSyntaxError(UndecidableError):
    """The command could not be split with confidence."""


@dataclass(frozen=True)
class Redirect:
    """A redirection: the operator and its target word (a heredoc's delimiter)."""

    op: str
    target: str


@dataclass(frozen=True)
class SimpleCommand:
    """One command as the shell would run it."""

    argv: tuple[str, ...]
    assignments: tuple[str, ...] = ()
    redirects: tuple[Redirect, ...] = ()
    dynamic: frozenset[int] = field(default_factory=frozenset)
    background: bool = False


@dataclass
class _Builder:
    words: list[str] = field(default_factory=list)
    dynamic: set[int] = field(default_factory=set)
    redirects: list[Redirect] = field(default_factory=list)
    pending_redirect: str | None = None

    def add(self, word: str, is_dynamic: bool) -> None:
        if self.pending_redirect is not None:
            self.redirects.append(Redirect(self.pending_redirect, word))
            self.pending_redirect = None
            return
        if is_dynamic:
            self.dynamic.add(len(self.words))
        self.words.append(word)

    def finish(self, background: bool) -> SimpleCommand | None:
        if self.pending_redirect is not None:
            msg = f"a redirection {self.pending_redirect!r} with no target"
            raise ShellSyntaxError(msg)
        assignments: list[str] = []
        i = 0
        while i < len(self.words) and _is_assignment(self.words[i]):
            assignments.append(self.words[i])
            i += 1
        argv = tuple(self.words[i:])
        dynamic = frozenset(n - i for n in self.dynamic if n >= i)
        if not argv and not assignments and not self.redirects:
            return None
        return SimpleCommand(argv, tuple(assignments), tuple(self.redirects), dynamic, background)


def _is_assignment(word: str) -> bool:
    name, eq, _ = word.partition("=")
    return bool(eq) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def _matching(text: str, start: int, open_: str, close: str) -> int:
    """Index of the ``close`` matching the ``open_`` before ``start``, quote-aware."""
    depth, i = 1, start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                break
            i = end + 1
            continue
        if c == '"':
            i = _end_of_double(text, i + 1) + 1
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    msg = f"no closing {close!r}"
    raise ShellSyntaxError(msg)


def _end_of_double(text: str, i: int) -> int:
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i
        if text.startswith("$(", i):
            i = _matching(text, i + 2, "(", ")") + 1
            continue
        i += 1
    msg = "an unterminated double quote"
    raise ShellSyntaxError(msg)


def parse(command: str) -> list[SimpleCommand]:
    """Every simple command ``command`` would run, nested ones included.

    Raises:
        ShellSyntaxError: the command cannot be split with confidence.
    """
    out: list[SimpleCommand] = []
    _parse_into(command, out, depth=0)
    return out


def _parse_into(text: str, out: list[SimpleCommand], depth: int) -> None:
    if depth > 8:
        msg = "nesting too deep to follow"
        raise ShellSyntaxError(msg)
    cmd = _Builder()
    mine: list[SimpleCommand] = []
    word, word_dynamic, in_word = "", False, False
    heredocs: list[tuple[str, bool]] = []
    i = 0

    def end_word() -> None:
        nonlocal word, word_dynamic, in_word
        if in_word:
            cmd.add(word, word_dynamic)
        word, word_dynamic, in_word = "", False, False

    def end_command(background: bool = False) -> None:
        nonlocal cmd
        end_word()
        done = cmd.finish(background)
        if done is not None:
            out.append(done)
            mine.append(done)
        cmd = _Builder()

    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            if text[i + 1] != "\n":
                word += text[i + 1]
                in_word = True
            i += 2
            continue
        if c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                msg = "an unterminated single quote"
                raise ShellSyntaxError(msg)
            word += text[i + 1 : end]
            in_word, i = True, end + 1
            continue
        if c == '"':
            end = _end_of_double(text, i + 1)
            inner = text[i + 1 : end]
            for start in _substitution_starts(inner):
                close = _matching(inner, start + 2, "(", ")")
                _parse_into(inner[start + 2 : close], out, depth + 1)
                word_dynamic = True
            if "`" in inner or "$" in inner:
                word_dynamic = True
            word += inner
            in_word, i = True, end + 1
            continue
        if c == "`":
            end = text.find("`", i + 1)
            if end < 0:
                msg = "an unterminated backtick"
                raise ShellSyntaxError(msg)
            _parse_into(text[i + 1 : end], out, depth + 1)
            word += text[i : end + 1]
            word_dynamic = in_word = True
            i = end + 1
            continue
        if c == "$" and text.startswith("$((", i):
            close = _matching(text, i + 3, "(", ")")
            word += text[i : close + 2]
            word_dynamic = in_word = True
            i = close + 2
            continue
        if c == "$" and text.startswith("$(", i) or c in "<>" and text.startswith("(", i + 1):
            close = _matching(text, i + 2, "(", ")")
            _parse_into(text[i + 2 : close], out, depth + 1)
            word += text[i : close + 1]
            word_dynamic = in_word = True
            i = close + 1
            continue
        if c == "$":
            word += c
            word_dynamic = in_word = True
            i += 1
            continue
        if c == "#" and not in_word:
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
            continue
        if c in " \t":
            end_word()
            i += 1
            continue
        redirect = _redirect_at(text, i, word if in_word else "")
        if redirect is not None:
            op, length, fd_in_word = redirect
            if fd_in_word:
                word, in_word = "", False
            end_word()
            cmd.pending_redirect = op
            i += length
            if op in ("<<", "<<-"):
                while i < len(text) and text[i] in " \t":
                    i += 1
                delimiter_start = i
                while i < len(text) and text[i] not in " \t\n;&|<>()":
                    i += 1
                raw = text[delimiter_start:i]
                if not raw:
                    msg = "a heredoc with no delimiter"
                    raise ShellSyntaxError(msg)
                delimiter = raw.replace("'", "").replace('"', "").replace("\\", "")
                cmd.add(delimiter, False)
                heredocs.append((delimiter, op == "<<-"))
            continue
        sep = next((s for s in _SEPARATORS if text.startswith(s, i)), None)
        if sep is not None:
            end_command(background=sep == "&")
            i += len(sep)
            if sep == "\n" and heredocs:
                i = _skip_heredoc_bodies(text, i, heredocs)
                heredocs = []
            continue
        word += c
        in_word = True
        i += 1
    if heredocs:
        msg = "a heredoc with no terminating line"
        raise ShellSyntaxError(msg)
    end_command()
    # Only this level's own commands: a nested level expands its own.
    for sub in mine:
        _expand_runners(sub, out, depth)


def _substitution_starts(text: str) -> list[int]:
    starts, i = [], 0
    while (i := text.find("$(", i)) >= 0:
        if not text.startswith("$((", i):
            starts.append(i)
        i += 2
    return starts


def _redirect_at(text: str, i: int, word: str) -> tuple[str, int, bool] | None:
    for op in _REDIRECTS:
        if text.startswith(op, i):
            # "2>" arrives with the digit already in the word being built.
            return op, len(op), word.isdigit()
    return None


def _skip_heredoc_bodies(text: str, i: int, heredocs: list[tuple[str, bool]]) -> int:
    for delimiter, strip_tabs in heredocs:
        while True:
            if i >= len(text):
                msg = f"a heredoc whose terminator {delimiter!r} never comes"
                raise ShellSyntaxError(msg)
            newline = text.find("\n", i)
            line = text[i:] if newline < 0 else text[i:newline]
            i = len(text) if newline < 0 else newline + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return i


def unwrap(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The command a wrapper would run: ``env A=1 git …`` is ``git …``."""
    while argv:
        head = argv[0].rsplit("/", 1)[-1]
        if head not in _RUNS_ITS_ARGUMENTS:
            return argv
        rest = list(argv[1:])
        while rest and (rest[0].startswith("-") or _is_assignment(rest[0])):
            flag = rest.pop(0)
            if head == "env" and flag in ("-u", "-C", "-S") and rest:
                rest.pop(0)
            if head == "nice" and flag == "-n" and rest:
                rest.pop(0)
        argv = tuple(rest)
    return argv


def _expand_runners(sub: SimpleCommand, out: list[SimpleCommand], depth: int) -> None:
    """Parse the string handed to ``sh -c`` or ``eval`` as the commands it runs."""
    argv = unwrap(sub.argv)
    if not argv:
        return
    head = argv[0].rsplit("/", 1)[-1]
    if head == "eval":
        _parse_into(" ".join(argv[1:]), out, depth + 1)
    elif head in _SHELLS:
        for n, arg in enumerate(argv[1:], 1):
            if arg.startswith("-") and "c" in arg[1:] and not arg.startswith("--"):
                if n + 1 < len(argv):
                    _parse_into(argv[n + 1], out, depth + 1)
                break
