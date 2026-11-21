r"""The canary scan and the credential's redaction read each stream line as its decoded text.

Both scans share one reading of a session's stream: each line is decoded as the JSON event the
runtime wrote, and its text is read with every code point that shows nothing removed (the
controls, the format characters, surrogates, and the Unicode Default_Ignorable_Code_Point set,
generated from the Unicode data the interpreter is pinned to). So a value split by any of them,
however the line writes it (as itself, as a short escape such as ``\\b``, as a ``\\u`` escape or
as a surrogate pair), reads as itself. A line that does not decode is read raw, with the same
characters removed in their UTF-8 and escaped forms; a line that cannot be read even so counts as
showing every canary, and is redacted whole.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.dispatch import redact

CANARY = "0123456789abcdef0011223344556677"
TOKEN = "sk-ant-oat01-" + "stand-in-credential-0123456789-abcdefgh"
#: Each splitter the review named: three short escapes, a zero-width joiner, the word joiner,
#: the byte order mark, a variation selector, and a tag character (a surrogate pair escaped).
SPLITTERS = {
    "backspace": 0x08,
    "form-feed": 0x0C,
    "tab": 0x09,
    "zero-width-joiner": 0x200D,
    "word-joiner": 0x2060,
    "byte-order-mark": 0xFEFF,
    "variation-selector": 0xFE0F,
    "tag-character": 0xE0041,
    "variation-selector-supplement": 0xE0100,
}


def _split(value: str, ch: str) -> str:
    return ch.join(value[i : i + 8] for i in range(0, len(value), 8))


def _line(text: str, *, ascii_only: bool) -> str:
    """An event as a JSON line: characters as themselves, or every one escaped as JSON does."""
    event = {"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}
    return json.dumps(event, ensure_ascii=ascii_only)


FORMS = pytest.mark.parametrize("ascii_only", [False, True], ids=["as itself", "escaped"])
SPLIT = pytest.mark.parametrize("name", sorted(SPLITTERS))


@FORMS
@SPLIT
def test_a_split_canary_is_found(name: str, ascii_only: bool) -> None:
    line = _line(f"shown {_split(CANARY, chr(SPLITTERS[name]))}", ascii_only=ascii_only)
    assert CANARY not in line
    assert canary_seen(line.encode() + b"\n", frozenset({CANARY})) == CANARY


@FORMS
@SPLIT
def test_a_split_credential_is_redacted_and_the_line_still_reads(
    tmp_path: Path, name: str, ascii_only: bool
) -> None:
    stream = tmp_path / "s" / "stdout.jsonl"
    stream.parent.mkdir()
    first = _line("before", ascii_only=True)
    split = _line(f"token {_split(TOKEN, chr(SPLITTERS[name]))} end", ascii_only=ascii_only)
    stream.write_text(f"{first}\n{split}\n")
    redact(stream, TOKEN)
    kept, rewritten = stream.read_text().split("\n")[:2]
    assert kept == first  # a line without the credential keeps its bytes
    event = json.loads(rewritten)
    text = event["message"]["content"][0]["content"]
    shown = "".join(ch for ch in text if ord(ch) != SPLITTERS[name])
    assert TOKEN not in shown and "token " in text and " end" in text


def test_a_line_that_does_not_decode_is_still_read_for_a_canary() -> None:
    # A stream cut mid-line, its last event never closed, the canary split by escapes.
    cut = _line(f"shown {_split(CANARY, chr(0x200D))}", ascii_only=True)[:-6]
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)
    assert canary_seen(cut.encode(), frozenset({CANARY})) == CANARY


def test_a_line_that_cannot_be_read_at_all_counts_as_showing_the_canary() -> None:
    unreadable = b'{"type":"user","content":"\xff\xfe' + CANARY[:10].encode() + b'"}\n'
    assert canary_seen(unreadable, frozenset({CANARY})) == CANARY


def test_a_line_that_does_not_decode_and_holds_the_credential_is_redacted_whole(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "s" / "stdout.jsonl"
    stream.parent.mkdir()
    cut = _line(f"token {_split(TOKEN, chr(0x2060))}", ascii_only=True)[:-6]
    unreadable = b'{"content":"\xff' + TOKEN[:12].encode() + b"\n"
    stream.write_bytes(cut.encode() + b"\n" + unreadable)
    redact(stream, TOKEN)
    kept = stream.read_bytes()
    assert TOKEN.encode() not in kept and TOKEN[:12].encode() not in kept
    assert kept.count(b"\n") == 2  # each line redacted in its place
