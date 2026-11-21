"""Against every pinned binary: what a compaction carries of the files read before it, per pin.

A reviewer whose conversation is compacted must read its rubric again in full before its verdict,
and the reading hook records a read only from the ``file`` object of the Read tool's result. These
rows measure, at the scripted endpoint, what each pin does with the files the session read before
its compaction trigger, and what a Read of one of them returns afterwards, and hold each pin to
it. No model is called and no credential is loaded; every file is a stand-in written here, and
the endpoint counts a text's tokens as its bytes over four unless a row says otherwise.

- The first request after the compaction carries the last file read before the trigger as its
  own call and result, and again, each whole, at most five other files read before it: those
  most recently modified, not those most recently read.
- A file the endpoint counts at more than 5,000 tokens is not carried; the request names it as
  too large to include. At 5,000 or fewer it is carried whole, whatever its size in bytes.
- A Read with no range of a carried file returns ``file_unchanged`` with no ``file`` object on
  2.1.301, and the file in full on 2.1.322. A Read with no range of a file not carried, and a
  Read from line 1 whose limit covers the file, return it in full on both pins.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from compaction_session import Ran, Session, usage_of
from scripted_endpoint import tool

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

#: A context past the trigger on every pin, as the last message reports it.
PAST = 999_000
#: A context well short of it.
SHORT = 10_000
#: Bytes per line of a stand-in file, its newline included.
WIDTH = 80
#: What a Read with no range returns for a carried file, as measured on each pin.
READ_OF_A_CARRIED_FILE = {"2.1.301": "file_unchanged", "2.1.322": "text"}
#: The note a request carries for a file read before the compaction but not carried.
TOO_LARGE = "was read before the last conversation was summarized, but the contents are too large"
ANSWER = tool("StructuredOutput", answer=7)


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _stand_in(path: Path, tag: str, size: int, modified: float) -> int:
    """Write ``size`` bytes of numbered lines tagged ``tag``; set when it was modified."""
    count = max(1, size // WIDTH)
    lines = []
    for n in range(1, count + 1):
        head = f"{tag}-L{n:05d} "
        lines.append(head + ("abcdefghij" * 8)[: WIDTH - 1 - len(head)] + "\n")
    path.write_text("".join(lines))
    os.utime(path, (modified, modified))
    return count


def _strings(value: Any, into: list[str]) -> list[str]:  # noqa: ANN401 - a request body's own shape
    if isinstance(value, str):
        into.append(value)
    elif isinstance(value, dict):
        for inner in value.values():
            _strings(inner, into)
    elif isinstance(value, list):
        for inner in value:
            _strings(inner, into)
    return into


def _quarter(body: dict[str, Any]) -> int:
    """A count request's tokens as the bytes of its message text over four."""
    return max(1, sum(len(s.encode()) for s in _strings(body.get("messages", []), [])) // 4)


def _first_after(ran: Ran) -> str:
    assert ran.compaction_requests, "the session did not compact"
    body = ran.bodies[ran.compaction_requests[0] + 1]
    return "\n".join(_strings(body.get("messages", []), []))


def _carried(text: str, path: Path) -> int:
    """How many of ``path``'s lines ``text`` holds."""
    return sum(1 for line in path.read_text().splitlines() if line in text)


def _read(path: Path, context: int = SHORT, **ranged: int) -> dict[str, Any]:
    return {**tool("Read", file_path=str(path), **ranged), "usage": usage_of(context)}


def _reading_session(
    binary: str, work: Path, *, rubric_newest: bool, rubric_size: int = 5_000
) -> tuple[Session, Path, list[Path], int]:
    """A rubric read first, then twelve parts, each part modified after the one before."""
    session = Session(binary, work, read_probe=True)
    cwd = work / "cwd"
    start = time.time() - 3_600
    parts = [cwd / f"part-{n:02d}.md" for n in range(1, 13)]
    for n, part in enumerate(parts, start=1):
        _stand_in(part, f"P{n:02d}X", 12_000, start + 10 * n)
    rubric = cwd / "rubric.md"
    lines = _stand_in(rubric, "RUBR", rubric_size, start + (1_000 if rubric_newest else 0))
    return session, rubric, parts, lines


def test_the_files_carried_after_a_compaction_are_the_last_read_and_the_five_last_modified(
    binary: str, tmp_path: Path
) -> None:
    for newest in (True, False):
        session, rubric, parts, _ = _reading_session(
            binary, tmp_path / str(newest), rubric_newest=newest
        )
        steps = [_read(rubric), *(_read(p) for p in parts[:-1]), _read(parts[-1], PAST), ANSWER]
        ran = session.run(steps, count_tokens=_quarter)
        assert ran.version in READ_OF_A_CARRIED_FILE, f"nothing was measured on {ran.version}"
        text = _first_after(ran)
        whole = {
            p.name for p in [rubric, *parts] if _carried(text, p) == len(p.read_text().splitlines())
        }
        touched = {p.name for p in [rubric, *parts] if _carried(text, p)}
        # Every file carried is carried whole.
        assert touched == whole
        # The last read, and the five others last modified: the rubric, read first, among them
        # only when it was modified last.
        if newest:
            assert whole == {"rubric.md", *(f"part-{n:02d}.md" for n in range(8, 13))}
        else:
            assert whole == {f"part-{n:02d}.md" for n in range(7, 13)}
        assert (ran.result or {}).get("structured_output") == {"answer": 7}


def test_a_file_counted_over_five_thousand_tokens_is_not_carried_but_named(
    binary: str, tmp_path: Path
) -> None:
    for counted, carried in ((5_000, True), (5_001, False), (None, False)):
        work = tmp_path / str(counted)
        session = Session(binary, work)
        rubric = work / "cwd" / "rubric.md"
        lines = _stand_in(rubric, "RUBR", 55_000, time.time() - 60)

        def count(body: dict[str, Any], counted: int | None = counted) -> int:
            if counted is None:
                return _quarter(body)
            return counted if "RUBR-L" in json.dumps(body) else 1

        ran = session.run([_read(rubric, PAST), ANSWER], count_tokens=count)
        assert ran.version in READ_OF_A_CARRIED_FILE, f"nothing was measured on {ran.version}"
        text = _first_after(ran)
        # 55,000 bytes, carried whole at a count of 5,000 and not at 5,001 or at its bytes over
        # four; where it is not carried, the request names it.
        assert _carried(text, rubric) == (lines if carried else 0)
        assert (TOO_LARGE in text and str(rubric) in text) is (not carried)


def test_a_read_after_the_compaction_returns_what_was_measured_on_each_pin(
    binary: str, tmp_path: Path
) -> None:
    session, rubric, parts, lines = _reading_session(binary, tmp_path, rubric_newest=True)
    large = tmp_path / "cwd" / "large.md"
    _stand_in(large, "LRGX", 55_000, time.time())
    before = [_read(rubric), _read(large), *(_read(p) for p in parts[:-1]), _read(parts[-1], PAST)]
    after = [
        _read(rubric),
        _read(rubric, offset=1, limit=lines),
        _read(large),
        _read(parts[0]),
        ANSWER,
    ]
    ran = session.run([*before, *after], count_tokens=_quarter)
    expected = READ_OF_A_CARRIED_FILE.get(ran.version)
    assert expected is not None, f"nothing was measured on {ran.version}"
    text = _first_after(ran)
    # The rubric is carried; the large file and the first part are not.
    assert _carried(text, rubric) == lines
    assert _carried(text, large) == 0 and TOO_LARGE in text and str(large) in text
    assert _carried(text, parts[0]) == 0
    results = session.read_results()
    assert len(results) == len(before) + len(after) - 1
    plain, ranged, of_large, of_part = results[len(before) :]
    # With no range, a carried file: no ``file`` object on 2.1.301, the file in full on 2.1.322.
    assert plain["type"] == expected
    if expected == "file_unchanged":
        assert plain["keys"] == ["file", "type"] and plain["file"] == {"filePath": str(rubric)}
    else:
        assert (plain["file"]["startLine"], plain["file"]["numLines"]) == (1, lines + 1)
    # From line 1 with a limit that covers it: the file in full on both pins.
    assert ranged["type"] == "text"
    assert (ranged["file"]["startLine"], ranged["file"]["numLines"]) == (1, lines)
    # With no range, a file not carried: in full on both pins.
    for result, path in ((of_large, large), (of_part, parts[0])):
        count = len(path.read_text().splitlines())
        assert result["type"] == "text"
        assert (result["file"]["startLine"], result["file"]["numLines"]) == (1, count + 1)
    assert (ran.result or {}).get("structured_output") == {"answer": 7}
