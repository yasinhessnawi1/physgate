"""The indicator scan reads what the reviewer reads, normalised, and fails closed.

Each check-switching marker is looked for in the text as a reader would take it:
compatibility forms folded (a full-width ``#`` is a ``#``), invisible format
characters removed, case ignored, and spacing around a dotted name ignored. A
stream line the scan cannot read, or a tool call whose input is not an object,
is not "no hits": it raises, and the review does not run.
"""

from __future__ import annotations

import json

import pytest

from physgate.reviewers.scan import ScanUnreadableError, scan


def _write(content: str, call: str = "t1") -> str:
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": call,
                    "name": "Write",
                    "input": {"file_path": "/w/m/x.py", "content": content},
                }
            ]
        },
    }
    return json.dumps(event) + "\n"


@pytest.mark.parametrize(
    "content",
    [
        "x = 1  # noqa",
        "x = 1  # NOQA",
        "x = 1  #​noqa",
        "x = 1  ＃ noqa",
        "x = 1  # n­oqa",
        "@pytest.mark.skip",
        "@PyTest.Mark.Skip",
        "@pytest . mark . skip",
        "@pytest.mark.​skip",
        "@pytest．mark．skip",
        "x = f()  # type:ignore",
        "x = f()  # TYPE: IGNORE",
    ],
)
def test_a_marker_is_found_however_it_is_spelt(content: str) -> None:
    hits = scan(_write(content))
    assert [h.evidence for h in hits] == ["t1"], content


def test_ordinary_code_is_not_a_hit() -> None:
    assert scan(_write("gain = compute(plant)\nassert gain > 0\n")) == ()


@pytest.mark.parametrize(
    "line",
    [
        "this line is not an event",
        '{"type": "assistant", "type": "user"}',
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Write", "input": "content=# noqa"}
                    ]
                },
            }
        ),
        json.dumps(["not", "an", "object"]),
    ],
    ids=["not JSON", "a key given twice", "a tool input that is not an object", "a list"],
)
def test_a_line_the_scan_cannot_read_is_never_no_hits(line: str) -> None:
    with pytest.raises(ScanUnreadableError):
        scan(_write("clean = True") + line + "\n")
