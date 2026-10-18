"""A canary is found in a session's stream verbatim and in the forms a read can show it in.

A canary marks material no session may read (the held-out tier, reviewer rubrics). A read
the hooks could not judge shows it in the session's own stream, as a tool's output; but
not always verbatim. Measured on the real binary, a held-out read printed through ``cut``
in two halves, ``base64``, ``rev`` or ``xxd -p`` showed the content with no verbatim
canary. Each of those forms, the upper-case one, and any 16 characters of the canary in
a row, are now found. Two are not, and are pinned here as the stated limit: a read that
shows fewer than 16 characters of it, and a read used without being printed. No hit is
therefore never evidence of no exposure.
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

import pytest

from physgate.orchestrator import dispatch

CANARY = "0123456789abcdef" + "0011223344556677"
LIVE = frozenset({CANARY})


def _stream(*outputs: str) -> bytes:
    """A stream as the runtime writes it: each tool output a JSON string in its own line."""
    lines = [
        json.dumps(
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": out}]}}
        )
        for out in outputs
    ]
    return ("\n".join(lines) + "\n").encode()


FILE = f"line one\nthe answer is 42\n<!-- {CANARY} -->\n"


def _wrapped(text: str, width: int) -> str:
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


FORMS = {
    "verbatim": FILE,
    "upper-case": FILE.upper(),
    "reversed": FILE[::-1],
    "hex": FILE.encode().hex(),
    "hex, wrapped as xxd -p wraps it": _wrapped(FILE.encode().hex(), 60),
    "hex, upper-case": FILE.encode().hex().upper(),
    "base64": base64.b64encode(FILE.encode()).decode(),
    "base64 after one byte": base64.b64encode(b"x" + FILE.encode()).decode(),
    "base64 after two bytes": base64.b64encode(b"xy" + FILE.encode()).decode(),
    "base64, wrapped at 76": _wrapped(base64.b64encode(FILE.encode()).decode(), 76),
    "a line break inside it": FILE.replace(CANARY, CANARY[:13] + "\n" + CANARY[13:]),
}


def canary_seen(data: bytes, live: frozenset[str]) -> str | None:
    """The dispatcher's own scan, over a stream file holding ``data``."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        stream = Path(directory) / "stdout.jsonl"
        stream.write_bytes(data)
        return dispatch.review_material_seen(stream, live)


@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_canary_is_found(form: str) -> None:
    assert canary_seen(_stream(FORMS[form]), LIVE) == CANARY


@pytest.mark.parametrize("cut", [12, 16, 20])
def test_a_canary_printed_in_two_halves_is_found(cut: int) -> None:
    halves = _stream("first: " + CANARY[:cut], "and then: " + CANARY[cut:])
    assert canary_seen(halves, LIVE) == CANARY


def test_a_stream_of_unrelated_hex_holds_no_canary() -> None:
    noise = " ".join(secrets.token_hex(32) for _ in range(3000))
    assert canary_seen(_stream(noise, base64.b64encode(noise.encode()).decode()), LIVE) is None


def test_no_canary_the_run_does_not_hold_is_looked_for() -> None:
    assert canary_seen(_stream(FILE), frozenset()) is None


def test_a_part_of_sixteen_characters_is_found() -> None:
    # A partial read (``head -c``, a cut line) that shows 16 of the 32 characters.
    assert canary_seen(_stream("the first part: " + CANARY[:16]), LIVE) == CANARY
    assert canary_seen(_stream("a middle part: " + CANARY[9:25]), LIVE) == CANARY


def test_the_limit_a_shorter_part_of_the_canary_is_not_found() -> None:
    # Fewer than 16 characters shown: stated, not detected.
    assert canary_seen(_stream("the first part: " + CANARY[:15]), LIVE) is None


def test_the_limit_a_read_used_but_never_printed_is_not_found() -> None:
    # ``grep -c`` over the file: the count is shown, the canary never is.
    assert canary_seen(_stream("1"), LIVE) is None
