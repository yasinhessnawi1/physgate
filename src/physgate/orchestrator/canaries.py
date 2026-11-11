"""Whether a session's stream shows a canary: verbatim, or in a form a read can show it in.

A canary marks material no session may read (the held-out tier, reviewer rubrics). The
hooks refuse every read of that material they can judge; a read whose path is built
while the command runs is judged by nothing, and shows the canary in the session's own
stream, as a tool's output. Not always verbatim: a read printed in two halves, in
upper case, reversed, as hex or as base64, wrapped or not, shows the content with no
verbatim canary (measured on the real binary). Each of those forms is looked for, and
so is any run of :data:`PART` of a canary's characters, which a partial read shows.

**The limit, stated:** a read that shows less than :data:`PART` characters of a canary
(or a part of one encoded), or that uses the material without printing it (a count, a
comparison, a value carried into a computation), shows no canary in any form looked
for. So a hit proves the session displayed the marked material; no hit proves
nothing, and is never evidence of no exposure.
"""

from __future__ import annotations

import base64
import functools
import json
import re
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from physgate.orchestrator.default_ignorable import RANGES as DEFAULT_IGNORABLE

#: The shortest run of a canary's characters taken as the canary shown. A canary is 32
#: random hex characters; a given 16-character run of one turns up by chance about once
#: in 10**19 positions. So a canary printed in two halves, or a partial read that shows
#: at least this much of it, is found.
PART = 16

_SQUEEZE = re.compile(r"\\[nrt]|\s")

#: The JSON escapes a raw line can hold: a surrogate pair, a ``\\u`` escape, a short escape.
_JSON_ESCAPE = re.compile(
    r"\\(?:u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    r"|u([0-9a-fA-F]{4})|([bfnrt\"\\\\/]))"
)
_SHORT = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}


@functools.cache
def _unseen() -> dict[int, None]:
    """Every code point that shows nothing, as a table that removes it.

    The controls, the format characters and surrogates (by category, from the interpreter's
    ``unicodedata``), and the Default_Ignorable_Code_Point set (generated from the same Unicode
    version's data).
    """
    drop: dict[int, None] = {cp: None for lo, hi in DEFAULT_IGNORABLE for cp in range(lo, hi + 1)}
    for cp in range(sys.maxunicode + 1):
        if unicodedata.category(chr(cp)) in ("Cc", "Cf", "Cs"):
            drop[cp] = None
    return drop


def unseen_removed(text: str) -> str:
    """``text`` without any code point that shows nothing: what it reads as."""
    return text.translate(_unseen())


def _unescaped(raw: str) -> str:
    def one(m: re.Match[str]) -> str:
        if m.group(1):
            high, low = int(m.group(1), 16), int(m.group(2), 16)
            return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00))
        if m.group(3):
            return chr(int(m.group(3), 16))
        return _SHORT[m.group(4)]

    return _JSON_ESCAPE.sub(one, raw)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def line_text(line: bytes) -> str | None:
    """One stream line as the scans read it, or ``None`` if it cannot be read at all.

    A line that decodes as JSON is read as its strings (keys and values), decoded; one that does
    not (a stream cut mid-line, a note) is read raw, its escapes undone. Either way every code
    point that shows nothing is removed, so a value split by one reads as itself. A line that is
    not UTF-8 cannot be read.
    """
    try:
        event = json.loads(line)
    except (ValueError, RecursionError):
        try:
            raw = line.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return unseen_removed(_unescaped(raw))
    if isinstance(event, (dict, list, str)):
        return unseen_removed("\n".join(_strings(event)))
    return unseen_removed(line.decode("utf-8"))


def _redacted(value: object, secret: str, mark: str) -> tuple[object, bool]:
    if isinstance(value, str):
        seen = unseen_removed(value)
        return (seen.replace(secret, mark), True) if secret in seen else (value, False)
    if isinstance(value, dict):
        out: dict[str, object] = {}
        hit = False
        for key, item in value.items():
            new_key, key_hit = _redacted(str(key), secret, mark)
            new_item, item_hit = _redacted(item, secret, mark)
            out[str(new_key)] = new_item
            hit = hit or key_hit or item_hit
        return out, hit
    if isinstance(value, list):
        items = [_redacted(item, secret, mark) for item in value]
        return [i for i, _ in items], any(h for _, h in items)
    return value, False


def redact_line(line: bytes, secret: str, mark: str) -> bytes:
    """``line`` with ``secret`` replaced by ``mark`` wherever the line reads as holding it.

    A line that decodes as JSON is rewritten, re-serialised, only if one of its strings reads
    as holding the secret; the strings that do are kept as they read, the secret replaced. A line
    that does not decode, and holds the secret as read raw or cannot be read at all, is replaced
    whole by ``mark``. Any other line keeps its bytes.
    """
    if not line.strip():
        return line
    try:
        event = json.loads(line)
    except (ValueError, RecursionError):
        text = line_text(line)
        return mark.encode() if text is None or secret in text else line
    rewritten, hit = _redacted(event, secret, mark)
    if hit:
        return json.dumps(rewritten, ensure_ascii=False, separators=(",", ":")).encode()
    return line.replace(secret.encode(), mark.encode())


def _base64_cores(canary: str) -> list[str]:
    """The base64 runs a canary always becomes, wherever it falls in the encoded bytes.

    Base64 encodes three bytes as four characters, so the canary's encoding depends on
    its offset modulo three; the groups at its two ends also hold neighbouring bytes,
    and are dropped.
    """
    cores = []
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + canary.encode()).decode()
        cores.append(encoded[4 if offset else 0 : -4])
    return cores


def canary_seen(data: bytes, live: frozenset[str]) -> str | None:
    """The first of ``live`` that ``data`` shows, in any form looked for, if any.

    ``data`` is a session's stream as the runtime wrote it: JSON lines, in which a tool's
    output is a JSON string, so a line break in the output is a backslash and an ``n``.
    """
    if not live:
        return None
    # Each line read as its decoded text, every code point that shows nothing removed: a canary
    # split by one, however the line writes it, is the canary shown. A line that cannot be read
    # at all counts as showing the canary: nothing is known of what it shows.
    texts: list[str] = []
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        read = line_text(line)
        if read is None:
            return sorted(live)[0]
        texts.append(read)
    text = "\n".join(texts)
    squeezed = _SQUEEZE.sub("", text)
    lowered = (text.lower(), squeezed.lower())
    for canary in sorted(live):
        plain = canary.lower()
        forms = (plain, plain[::-1], canary.encode().hex())
        if any(form in view for form in forms for view in lowered):
            return canary
        if any(core in view for core in _base64_cores(canary) for view in (text, squeezed)):
            return canary
        runs = {plain[i : i + PART] for i in range(len(plain) - PART + 1)}
        if any(run in view for run in runs for view in lowered):
            return canary
    return None


@dataclass(frozen=True)
class CanaryCheck:
    """Whether a text shows a held-out canary or a rubric's, in any form looked for.

    The text a person or a reviewer wrote for a role session (a note, a quoted verdict) is held
    to the same canaries as a session's own stream, with the same limit: a hit proves the text
    shows the marked material, and no hit proves nothing.
    """

    held_out: frozenset[str]
    review_material: frozenset[str]

    def seen(self, text: str) -> Literal["held_out", "review_material"] | None:
        """The held-out tier first, since its exposure is the one that is counted (ARCH-141)."""
        data = text.encode()
        if canary_seen(data, self.held_out) is not None:
            return "held_out"
        if canary_seen(data, self.review_material) is not None:
            return "review_material"
        return None
