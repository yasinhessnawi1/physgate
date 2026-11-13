"""A stream's, a log's or a record's lines: split at a newline and nowhere else.

The binary writes one JSON event per line, and the harness one record per line. A JSON string
may hold U+2028, U+2029 or U+0085 as themselves, and ``str.splitlines`` also splits at each of
them (and at the other line breaks Unicode names), which cuts one event in two. Every reader of
such a file splits it here instead, as its bytes split at the newline byte: UTF-8 writes no other
character with that byte, so the decoded text's lines are the bytes' lines.
"""

from __future__ import annotations


def split_lines(text: str) -> list[str]:
    """``text`` split at each newline only; the empty piece after a last newline is dropped."""
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    return parts
