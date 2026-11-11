"""The credential's redaction fails closed, and reads the stream exactly as the canary scan does.

One reading serves both: each line decoded strictly as UTF-8, then as JSON, every code point that
shows nothing removed. Whatever the scan would read as holding the credential is redacted, and
whatever cannot be read, or rewritten safely, is redacted whole: a lone surrogate the rewrite
cannot encode, a line in another encoding, a credential split across two of a line's strings, or
across two lines.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import physgate.orchestrator.canaries as canaries
from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.credentials import REDACTED_TEXT
from physgate.orchestrator.dispatch import redact

CANARY = "0123456789abcdef0011223344556677"
TOKEN = "sk-ant-oat01-" + "stand-in-credential-0123456789-abcdefgh"
BEFORE = json.dumps({"type": "user", "content": "before"})


def _redacted(tmp_path: Path, data: bytes) -> bytes:
    stream = tmp_path / "s" / "stdout.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_bytes(data)
    redact(stream, TOKEN)
    return stream.read_bytes()


def _gone(kept: bytes) -> bool:
    """No part of the credential long enough to name it is left, in any encoding."""
    pieces = (TOKEN[13:29], TOKEN[29:])
    encodings = ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
    return not any(p.encode(e) in kept for p in pieces for e in encodings)


def test_a_credential_beside_a_lone_surrogate_is_redacted_and_nothing_raises(
    tmp_path: Path,
) -> None:
    line = json.dumps({"type": "user", "content": f"\ud800 {TOKEN}"})  # escaped as \\ud800
    kept = _redacted(tmp_path, f"{BEFORE}\n{line}\n".encode())
    assert _gone(kept)
    assert kept.split(b"\n")[0] == BEFORE.encode()


def _encoded(text: str, encoding: str) -> bytes:
    return text.encode(encoding)


ENCODINGS = ("utf-16", "utf-16-le", "utf-32", "utf-32-be")


def test_a_canary_in_a_line_of_another_encoding_is_seen() -> None:
    for encoding in ENCODINGS:
        line = _encoded(json.dumps({"type": "user", "content": f"shown {CANARY}"}), encoding)
        assert canary_seen(line + b"\n", frozenset({CANARY})) == CANARY, encoding


def test_a_line_of_another_encoding_holding_the_credential_is_redacted_whole(
    tmp_path: Path,
) -> None:
    for n, encoding in enumerate(ENCODINGS):
        line = _encoded(json.dumps({"type": "user", "content": f"token {TOKEN}"}), encoding)
        kept = _redacted(tmp_path / str(n), BEFORE.encode() + b"\n" + line + b"\n")
        assert _gone(kept), encoding
        # Never decoded by a guess at its encoding: read strictly as UTF-8, or redacted whole.
        assert kept.split(b"\n")[:2] == [BEFORE.encode(), REDACTED_TEXT.encode()], encoding


def test_a_credential_split_across_two_strings_of_a_line_is_redacted(tmp_path: Path) -> None:
    line = json.dumps({"type": "user", "a": TOKEN[:24], "b": TOKEN[24:]})
    assert TOKEN not in line
    kept = _redacted(tmp_path, f"{BEFORE}\n{line}\n".encode())
    assert TOKEN[:24].encode() not in kept and TOKEN[24:].encode() not in kept
    assert REDACTED_TEXT.encode() in kept
    assert kept.split(b"\n")[0] == BEFORE.encode()


def test_a_credential_split_across_two_lines_is_redacted(tmp_path: Path) -> None:
    # One event cut by a raw line break inside the credential: neither line decodes, and
    # neither holds the credential alone.
    event = json.dumps({"type": "user", "content": f"x {TOKEN} y"})
    at = event.index(TOKEN) + 24
    first, second = event[:at], event[at:]
    kept = _redacted(tmp_path, f"{BEFORE}\n{first}\n{second}\n".encode())
    assert TOKEN[:24].encode() not in kept and TOKEN[24:].encode() not in kept
    assert kept.split(b"\n") == [
        BEFORE.encode(),
        REDACTED_TEXT.encode(),
        REDACTED_TEXT.encode(),
        b"",
    ]


def test_a_rewrite_that_fails_for_any_reason_redacts_the_line_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fails(*_: object, **__: object) -> str:
        raise ValueError("cannot serialise")

    line = json.dumps({"type": "user", "content": f"token {TOKEN}"})
    data = BEFORE.encode() + b"\n" + line.encode()
    monkeypatch.setattr(canaries.json, "dumps", fails)
    try:
        kept = _redacted(tmp_path, data)
    except ValueError as exc:
        pytest.fail(f"the redaction raised instead of redacting: {exc}")
    assert _gone(kept)
    assert kept.split(b"\n") == [BEFORE.encode(), REDACTED_TEXT.encode()]


def test_a_line_with_a_duplicate_key_holding_the_credential_is_redacted_whole(
    tmp_path: Path,
) -> None:
    # A decoder keeps only the last of two equal keys: the first value is never read by it.
    line = '{"type":"user","content":"token ' + TOKEN + '","content":"clean"}'
    kept = _redacted(tmp_path, f"{BEFORE}\n{line}\n".encode())
    assert _gone(kept)
    assert kept.split(b"\n")[:2] == [BEFORE.encode(), REDACTED_TEXT.encode()]


def test_a_line_with_a_duplicate_key_counts_as_showing_a_canary() -> None:
    line = '{"type":"user","content":"shown ' + CANARY + '","content":"clean"}\n'
    assert canary_seen(line.encode(), frozenset({CANARY})) == CANARY
    hidden = '{"type":"user","content":"clean","content":"clean"}\n'
    assert canary_seen(hidden.encode(), frozenset({CANARY})) == CANARY  # unread: counted
