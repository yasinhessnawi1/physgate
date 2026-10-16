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
the part that matters. A word the shell expands before the command sees it (an
unquoted ``*``, ``?``, ``[`` or a ``{a,b}`` pattern) is marked expanding for the same
reason: what it becomes depends on the files present, or is not the word written.

Two expansions do not depend on anything outside the command, so they are done here
exactly rather than left as unknowns: ANSI-C quoting (``$'…'``) is decoded to the bytes
the shell would pass, and a brace pattern is expanded to every word it becomes, up to
:data:`BRACE_LIMIT` words (beyond that the word is recorded as unbounded, and a check
decides what that means for it).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from physgate.hooks.exceptions import UndecidableError

_SEPARATORS = ("&&", "||", "|&", ";;", ";", "|", "&", "\n", "(", ")")
_REDIRECTS = ("<<<", "<<-", "&>>", "<<", ">>", ">|", "<>", "&>", ">&", "<&", ">", "<")
#: Programs that run their arguments as a command.
_RUNS_ITS_ARGUMENTS = {"env", "command", "exec", "nohup", "time", "builtin", "sudo", "nice"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
#: The shells, for a check that looks for one among another program's words.
SHELLS = frozenset(_SHELLS)
#: Reserved words that may start a command and are followed by the command they govern:
#: ``{ git …; }``, ``if git …``, ``then git …``, ``! git …``, ``coproc git …``. ``function``
#: is followed by the function's name before its body.
_RESERVED_PREFIXES = {"{", "!", "if", "then", "elif", "else", "do", "while", "until", "coproc"}
#: Unquoted text that the shell turns into other words: a glob, or a brace expansion.
#: Quoted characters are blanked to NUL before this is matched, so they never count.
_EXPANDS = re.compile(r"[*?\[]|\{[^{}]*(,|\.\.)[^{}]*\}")


#: The most words one brace pattern is expanded to. Beyond it, the word is unbounded.
BRACE_LIMIT = 1024
#: The escapes of ANSI-C quoting that stand for one fixed character.
_ANSI_C_SIMPLE = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r",
    "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?",
}  # fmt: skip
_ANSI_C_NUMERIC = {"x": (16, 2), "u": (16, 4), "U": (16, 8)}
_SEQUENCE = re.compile(
    r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?|([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?"
)


class ShellSyntaxError(UndecidableError):
    """The command could not be split with confidence."""


class Redirect:
    """A redirection: the operator and its target word (a heredoc's delimiter).

    ``braces`` is every word an unquoted brace pattern in the target becomes, empty when
    it has none, or ``None`` when there are more than :data:`BRACE_LIMIT`.
    """

    __slots__ = ("braces", "op", "target")

    def __init__(self, op: str, target: str, braces: tuple[str, ...] | None = ()) -> None:
        """The operator and its target."""
        self.op = op
        self.target = target
        self.braces = braces

    def __eq__(self, other: object) -> bool:
        """Equal when operator and target are."""
        return isinstance(other, Redirect) and (self.op, self.target) == (other.op, other.target)

    def __hash__(self) -> int:
        """Hash on operator and target."""
        return hash((self.op, self.target))

    def __repr__(self) -> str:
        """For test output."""
        return f"Redirect(op={self.op!r}, target={self.target!r})"


class SimpleCommand:
    """One command as the shell would run it."""

    __slots__ = (
        "argv", "assignments", "background", "braces", "dynamic", "expanding", "redirects",
    )  # fmt: skip

    def __init__(
        self,
        argv: tuple[str, ...],
        assignments: tuple[str, ...] = (),
        redirects: tuple[Redirect, ...] = (),
        dynamic: frozenset[int] = frozenset(),
        background: bool = False,
        expanding: frozenset[int] = frozenset(),
        braces: Mapping[int, tuple[str, ...] | None] | None = None,
    ) -> None:
        """The words, and what the shell does around them.

        ``braces`` maps the index of each word with an unquoted brace pattern to every
        word it becomes, or to ``None`` when there are more than :data:`BRACE_LIMIT`.
        """
        self.argv = argv
        self.assignments = assignments
        self.redirects = redirects
        self.dynamic = dynamic
        self.background = background
        self.expanding = expanding
        self.braces: Mapping[int, tuple[str, ...] | None] = braces or {}

    def __repr__(self) -> str:
        """For test output."""
        return f"SimpleCommand(argv={self.argv!r}, background={self.background!r})"


class _Builder:
    __slots__ = ("braces", "dynamic", "expanding", "pending_redirect", "redirects", "words")

    def __init__(self) -> None:
        self.words: list[str] = []
        self.dynamic: set[int] = set()
        self.expanding: set[int] = set()
        self.braces: dict[int, tuple[str, ...] | None] = {}
        self.redirects: list[Redirect] = []
        self.pending_redirect: str | None = None

    def add(
        self,
        word: str,
        is_dynamic: bool,
        expands: bool = False,
        braces: tuple[str, ...] | None = (),
    ) -> None:
        if self.pending_redirect is not None:
            self.redirects.append(Redirect(self.pending_redirect, word, braces))
            self.pending_redirect = None
            return
        if is_dynamic:
            self.dynamic.add(len(self.words))
        if expands:
            self.expanding.add(len(self.words))
        if braces != ():
            self.braces[len(self.words)] = braces
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
        expanding = frozenset(n - i for n in self.expanding if n >= i)
        braces = {n - i: b for n, b in self.braces.items() if n >= i}
        if not argv and not assignments and not self.redirects:
            return None
        return SimpleCommand(
            argv, tuple(assignments), tuple(self.redirects), dynamic, background, expanding, braces
        )


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
    # The word as the shell sees its quoting: unquoted characters as written, every quoted,
    # escaped or substituted character blanked, so only unquoted text can count as expanding.
    bare = ""
    heredocs: list[tuple[str, bool]] = []
    i = 0

    def end_word() -> None:
        nonlocal word, word_dynamic, in_word, bare
        if in_word:
            braces: tuple[str, ...] | None = ()
            if "{" in bare:
                braces = expand_braces(word, bare)
                if braces == (word,):
                    braces = ()
            cmd.add(word, word_dynamic, _EXPANDS.search(bare) is not None, braces)
        word, word_dynamic, in_word, bare = "", False, False, ""

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
                bare += "\0"
                in_word = True
            i += 2
            continue
        if c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                msg = "an unterminated single quote"
                raise ShellSyntaxError(msg)
            word += text[i + 1 : end]
            bare += "\0" * (end - i - 1)
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
            bare += "\0" * len(inner)
            in_word, i = True, end + 1
            continue
        if c == "`":
            end = text.find("`", i + 1)
            if end < 0:
                msg = "an unterminated backtick"
                raise ShellSyntaxError(msg)
            _parse_into(text[i + 1 : end], out, depth + 1)
            word += text[i : end + 1]
            bare += "\0" * (end + 1 - i)
            word_dynamic = in_word = True
            i = end + 1
            continue
        if c == "$" and text.startswith("'", i + 1):
            # ANSI-C quoting: decoded, so the word is the one the command receives.
            end = _end_of_ansi_c(text, i + 2)
            decoded = decode_ansi_c(text[i + 2 : end])
            word += decoded
            bare += "\0" * len(decoded)
            in_word, i = True, end + 1
            continue
        if c == "$" and text.startswith("$((", i):
            close = _matching(text, i + 3, "(", ")")
            word += text[i : close + 2]
            bare += "\0" * (close + 2 - i)
            word_dynamic = in_word = True
            i = close + 2
            continue
        if c == "$" and text.startswith("$(", i) or c in "<>" and text.startswith("(", i + 1):
            close = _matching(text, i + 2, "(", ")")
            _parse_into(text[i + 2 : close], out, depth + 1)
            word += text[i : close + 1]
            bare += "\0" * (close + 1 - i)
            word_dynamic = in_word = True
            i = close + 1
            continue
        if c == "$":
            word += c
            bare += "\0"
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
                word, in_word, bare = "", False, ""
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
        bare += c
        in_word = True
        i += 1
    if heredocs:
        msg = "a heredoc with no terminating line"
        raise ShellSyntaxError(msg)
    end_command()
    # Only this level's own commands: a nested level expands its own.
    for sub in mine:
        _expand_runners(sub, out, depth)


def _end_of_ansi_c(text: str, i: int) -> int:
    """Index of the quote closing a ``$'…'`` whose body starts at ``i``."""
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "'":
            return i
        i += 1
    msg = "an unterminated $'...' quote"
    raise ShellSyntaxError(msg)


def decode_ansi_c(body: str) -> str:
    """The word a ``$'…'`` quote with this body stands for, as the shell decodes it.

    Bytes from a numeric escape are kept as the bytes they are, in the form the
    operating system's path functions take them back (:func:`os.fsdecode`).

    Raises:
        ShellSyntaxError: the body decodes to a NUL, where shells disagree on what
            the word becomes.
    """
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if c != "\\" or not nxt:
            out += c.encode("utf-8", "surrogateescape")
            i += 1
        elif nxt in _ANSI_C_SIMPLE:
            out += _ANSI_C_SIMPLE[nxt].encode()
            i += 2
        elif nxt in "01234567":
            digits = re.match(r"[0-7]{1,3}", body[i + 1 :])
            assert digits is not None  # noqa: S101 - nxt is an octal digit
            out.append(int(digits.group(), 8) & 0xFF)
            i += 1 + len(digits.group())
        elif nxt in _ANSI_C_NUMERIC:
            base, width = _ANSI_C_NUMERIC[nxt]
            digits = re.match(rf"[0-9A-Fa-f]{{1,{width}}}", body[i + 2 :])
            if digits is None:
                out += ("\\" + nxt).encode()
                i += 2
                continue
            value = int(digits.group(), base)
            if nxt == "x":
                out.append(value)
            else:
                out += chr(value).encode("utf-8", "surrogatepass")
            i += 2 + len(digits.group())
        elif nxt == "c" and i + 2 < len(body):
            out.append(ord(body[i + 2]) & 0x1F)
            i += 3
        else:
            out += ("\\" + nxt).encode("utf-8", "surrogateescape")
            i += 2
    if 0 in out:
        msg = "a $'...' quote that decodes to a NUL"
        raise ShellSyntaxError(msg)
    return os.fsdecode(bytes(out))


class _TooManyWordsError(Exception):
    """A brace pattern became more than :data:`BRACE_LIMIT` words."""


def expand_braces(word: str, bare: str) -> tuple[str, ...] | None:
    """Every word an unquoted brace pattern in ``word`` becomes, in the shell's order.

    ``bare`` is ``word`` with every quoted character blanked to NUL, so only an
    unquoted brace, comma or ``..`` is syntax. A word with no pattern becomes itself.
    ``None`` if it becomes more than :data:`BRACE_LIMIT` words.
    """
    chars = [(c, b == "\0") for c, b in zip(word, bare, strict=True)]
    try:
        return tuple("".join(c for c, _ in w) for w in _brace(chars))
    except _TooManyWordsError:
        return None


def _brace(chars: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    for start, (c, quoted) in enumerate(chars):
        if c != "{" or quoted:
            continue
        found = _brace_body(chars, start)
        if found is None:
            continue
        end, alternatives = found
        suffixes = _brace(chars[end + 1 :])
        out: list[list[tuple[str, bool]]] = []
        for alternative in alternatives:
            for middle in _brace(alternative):
                for suffix in suffixes:
                    out.append(chars[:start] + middle + suffix)
                    if len(out) > BRACE_LIMIT:
                        raise _TooManyWordsError
        return out
    return [chars]


def _brace_body(
    chars: list[tuple[str, bool]], start: int
) -> tuple[int, list[list[tuple[str, bool]]]] | None:
    """The closing index and the alternatives of the pattern opening at ``start``, if valid."""
    depth, commas = 0, list[int]()
    for n in range(start + 1, len(chars)):
        c, quoted = chars[n]
        if quoted:
            continue
        if c == "{":
            depth += 1
        elif c == "}" and depth:
            depth -= 1
        elif c == "}":
            if commas:
                edges = [start, *commas, n]
                return n, [chars[a + 1 : b] for a, b in zip(edges, edges[1:], strict=False)]
            body = chars[start + 1 : n]
            if any(q for _, q in body):
                return None
            sequence = _sequence("".join(ch for ch, _ in body))
            if sequence is None:
                return None
            return n, [[(ch, True) for ch in item] for item in sequence]
        elif c == "," and not depth:
            commas.append(n)
    return None


def _sequence(body: str) -> list[str] | None:
    """The words a ``{x..y[..step]}`` sequence becomes, or ``None`` if ``body`` is not one."""
    match = _SEQUENCE.fullmatch(body)
    if match is None:
        return None
    if match.group(1) is not None:
        first, last, step = match.group(1), match.group(2), match.group(3)
        a, b = int(first), int(last)
        padded = any(
            x.lstrip("-").startswith("0") and len(x.lstrip("-")) > 1 for x in (first, last)
        )
        width = max(len(first), len(last)) if padded else 0
    else:
        a, b, step = ord(match.group(4)), ord(match.group(5)), match.group(6)
        width = -1
    stride = abs(int(step)) if step else 1
    stride = stride or 1
    if abs(b - a) // stride + 1 > BRACE_LIMIT:
        raise _TooManyWordsError
    values = range(a, b + 1, stride) if a <= b else range(a, b - 1, -stride)
    if width < 0:
        return [chr(v) for v in values]
    return [f"{v:0{width}d}" if width else str(v) for v in values]


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
    """The command a wrapper would run: ``env A=1 git …`` is ``git …``.

    A reserved word that governs the command after it (``{``, ``if``, ``then``, ``do``,
    ``!``, ``coproc``, ``function name``) is stepped over the same way, so ``{ git …; }``
    and ``if git …`` are ``git …``.
    """
    while argv:
        if argv[0] in _RESERVED_PREFIXES:
            argv = argv[1:]
            continue
        if argv[0] == "function":
            argv = argv[2:]
            continue
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
