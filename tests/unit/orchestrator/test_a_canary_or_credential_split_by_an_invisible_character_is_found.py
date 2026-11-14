"""A canary or a credential split by an invisible character is found in the raw stream.

The scans that read a session's stream as the runtime wrote it (the canary scan, the credential's
redaction) match its raw text. A session can print a marked value with an invisible character
every few characters: a control character (C0, DEL, C1) or a Unicode format character (a soft
hyphen, the zero-width and direction marks, the word joiner and invisible operators, the
direction isolates, the byte order mark). Earlier pins write such a character as itself, 2.1.311
and later write it as a JSON unicode escape, and the C0 controls are escaped on every pin. In
either form the value is still read back as itself, so in either form it is still found.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.dispatch import redact

CANARY = "0123456789abcdef0011223344556677"
TOKEN = "sk-ant-oat01-" + "stand-in-credential-0123456789-abcdefgh"
#: Every class, by its ends where it is a range; built at run time.
CODES = (
    0x01, 0x1F, 0x7F, 0x80, 0x85, 0x9F, 0xAD, 0x200B, 0x200F, 0x202A, 0x202E,
    0x2060, 0x2064, 0x2066, 0x2069, 0xFEFF,
)  # fmt: skip


def _split(value: str, ch: str) -> str:
    return ch.join(value[i : i + 8] for i in range(0, len(value), 8))


#: The characters 2.1.311 and later write as escapes; JSON escapes the C0 controls everywhere.
_ESCAPED = re.compile(
    "[\x00-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


def _line(text: str, *, escaped: bool) -> str:
    """One stream line carrying ``text``, its invisible characters as itself or escaped."""
    line = json.dumps({"type": "user", "content": text}, ensure_ascii=False)
    if not escaped:
        return line
    return _ESCAPED.sub(lambda m: f"\\u{ord(m.group()):04x}", line)


@pytest.mark.parametrize("escaped", [False, True], ids=["as itself", "escaped"])
@pytest.mark.parametrize("code", CODES, ids=[f"U+{c:04X}" for c in CODES])
def test_a_split_canary_is_found(code: int, escaped: bool) -> None:
    line = _line(f"shown: {_split(CANARY, chr(code))}", escaped=escaped)
    assert CANARY not in line
    assert canary_seen(line.encode(), frozenset({CANARY})) == CANARY


@pytest.mark.parametrize("escaped", [False, True], ids=["as itself", "escaped"])
@pytest.mark.parametrize("code", CODES, ids=[f"U+{c:04X}" for c in CODES])
def test_a_split_credential_is_redacted(tmp_path: Path, code: int, escaped: bool) -> None:
    ch = chr(code)
    stream = tmp_path / "s" / "stdout.jsonl"
    stream.parent.mkdir()
    stream.write_text(_line(f"token {_split(TOKEN, ch)} end", escaped=escaped) + "\n")
    redact(stream, TOKEN)
    kept = stream.read_text()
    visible = re.sub(rf"\\u{code:04x}", "", kept.replace(ch, ""), flags=re.IGNORECASE)
    assert TOKEN not in visible
    assert "token " in kept and " end" in kept  # nothing else is touched
