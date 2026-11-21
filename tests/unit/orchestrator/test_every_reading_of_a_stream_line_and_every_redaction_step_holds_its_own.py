"""Each reading of a stream line, and each step of the credential's redaction, catches a case alone.

A stream line is read twice (its string values and keys, decoded; and its raw text, escapes
undone), each with every code point that shows nothing removed; a line is redacted string by
string, checked again after its rewrite, and checked against its bytes; then the stream is read
across lines. Each row here is a case only one of those catches, so none of them is dead weight:

- a credential split across two strings at a zero-width character is read only by the decoded
  reading with the invisible character removed;
- a canary written as a JSON number is read only by the raw reading (the decoded reading takes
  strings);
- a line that holds the credential only across two of its strings is replaced whole by the
  line's own redaction, not left to the pass across lines;
- a line whose bytes hold the credential where no reading does is replaced whole;
- a rewrite that still holds the credential across strings is replaced whole.
"""

from __future__ import annotations

import json

from physgate.orchestrator.canaries import canary_seen, redact_line, redact_text
from physgate.orchestrator.credentials import REDACTED_TEXT

SECRET = "sk-test-not-a-real-credential-4f2a9c"
MARK = REDACTED_TEXT


def _line(event: object) -> bytes:
    return json.dumps(event).encode()


def test_a_credential_split_across_two_strings_at_a_zero_width_character_is_redacted() -> None:
    half = len(SECRET) // 2
    event = {"type": "user", "content": [SECRET[:half], "​" + SECRET[half:]]}
    data = _line(event) + b"\n"
    redacted = redact_text(data, SECRET, MARK)
    assert redacted.split(b"\n")[0] == MARK.encode()


def test_a_canary_written_as_a_json_number_is_found() -> None:
    canary = "20261111424242"
    data = _line({"type": "user", "value": int(canary)}) + b"\n"
    assert canary_seen(data, frozenset({canary})) == canary


def test_a_line_holding_the_credential_only_across_two_strings_is_replaced_whole_by_itself() -> (
    None
):
    half = len(SECRET) // 2
    line = _line({"type": "user", "content": [SECRET[:half], SECRET[half:]]})
    assert redact_line(line, SECRET, MARK) == MARK.encode()


def test_a_line_whose_bytes_alone_hold_the_credential_is_replaced_whole() -> None:
    # The credential holds a JSON-like escape, so the raw reading (escapes undone) reads
    # something else; only the bytes hold it as written.
    secret = "tok\\u0041-not-a-real-credential"
    line = f"plain text, not an event: {secret}".encode()
    assert secret.encode() in line
    assert redact_line(line, secret, MARK) == MARK.encode()


def test_a_rewrite_that_still_holds_the_credential_across_strings_is_replaced_whole() -> None:
    half = len(SECRET) // 2
    event = {"type": "user", "content": [f"before {SECRET} after", SECRET[:half], SECRET[half:]]}
    assert redact_line(_line(event), SECRET, MARK) == MARK.encode()
