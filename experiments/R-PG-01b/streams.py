"""R-PG-01b, CRITERIA.md §5.5 and L10: every review's reads of the parts sheet, as received.

Usage, in the run checkout (``uv run --frozen python -I``)::

    streams.py round --arm I|F --run <run dir> --root <review root> [--out <file>]
    streams.py stream --arm I|F <stdout.jsonl> [--out <file>]

**What is read.** For each Read call on ``parts_sheet.json``, the text the model received: the
tool-result content returned to the model for that call, in the review's captured stream
(``<root>/<session id>/session/stdout.jsonl``). Never the copy of the file, and never a line
count the stream reports beside the result.

**What each read is expected to return.** Arm F's sheet reads as 1,225 numbered lines, arm I's as
984, and both end with the same last row id (:data:`common.LAST_ROW_ID`). A read asks for the
lines from its offset (line 1 if none is given) up to its limit (the rest of the file if none).

**How each read is classed** (§5.5, with the reading of 23.10.2026 the README discloses):

- ``cut``: it returned fewer numbered lines than it asked for, whatever its offset or limit, or
  it asked for the file's end and the last row id is absent; or its result is the binary's
  token-limit error (a page counted above the limit); or it is one of the binary's
  "unchanged" stubs with no earlier read in the session that returned the range it asked for;
- ``whole``: it asked for the whole file and returned every line, last row included;
- ``part``: it asked for a range smaller than the file and returned all of it;
- ``unchanged``: one of the binary's own stubs for a read it did not repeat (2.1.301's three
  texts, :data:`UNCHANGED`), where an earlier read in the same session, of the same path,
  returned every line of the range this one asked for;
- ``error``: any other result the binary marked an error (a path that does not exist);
- ``no_result``: the call's result never came.

A cut can only come from the service's counting (§5.5): a stub or an error the service's count
did not make is not a cut. ``unchanged``, ``error`` and ``no_result`` are reported per arm and
side and void nothing; anything not recognised as one of them fails closed, as a cut.

The numbered lines returned are the run of consecutive line numbers the text gives from the
read's first line: a text that numbers its lines from another line returned none of them.

``round`` reads every review session of a run (both logs, every try, and any session under the
root the logs do not name) and prints, per side: the reviews, those that read the sheet at least
once and those that never did, the Read calls on it, the whole, part, cut, unchanged, error and
no-result reads, the reviews whose reads together covered every line, and the reviews whose
stream is missing (unknown). It exits 3 if any read is cut: the round is void (§12). ``stream``
classes one session's reads (L10). Counts only: no verdict, finding or row is read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

SHEET_NAME = "parts_sheet.json"
STREAM = ("session", "stdout.jsonl")
_NUMBERED = re.compile(r"^(\d+)\t")
_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: The pinned binary's (2.1.301) own texts for a Read it did not repeat, as its own check of them
#: reads them: a result that starts with one of these is a stub, not the file.
UNCHANGED = (
    "File unchanged since last read. The content from the earlier Read tool_result in this "
    "conversation is still current",
    "Wasted call \u2014 file unchanged since your last Read. Refer to that earlier tool_result "
    "instead.",
    "<system-reminder>This file is already in your context",
)
#: The pinned binary's error for a Read whose text the service counts above the limit.
TOKEN_LIMIT = re.compile(r"File content \([\d,]+ tokens\) exceeds maximum allowed tokens \(")
#: The classes a read can take; a cut alone voids a round.
CLASSES = ("whole", "part", "cut", "unchanged", "error", "no_result")


@dataclass(frozen=True)
class SheetRead:
    """One Read call on the sheet: what it asked for and the text the model got back."""

    tool_use_id: str
    offset: int | None
    limit: int | None
    text: str | None
    is_error: bool = False
    #: The path the call named, made absolute against the session's working directory.
    path: str = ""


@dataclass
class Classed:
    """One read, classed against the pinned sheet."""

    cls: str
    asked: int
    returned: int
    to_end: bool
    last_row: bool
    lines: frozenset[int] = field(default_factory=frozenset)


def _events(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _content_text(content: Any) -> str:  # noqa: ANN401 - the stream's own content shape
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _int(value: Any) -> int | None:  # noqa: ANN401 - a tool input's own value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _absolute(path: str, cwd: str) -> str:
    """``path`` as the binary resolves it: against the session's working directory if relative."""
    return os.path.normpath(path if os.path.isabs(path) or not cwd else os.path.join(cwd, path))


def sheet_reads(stream: str) -> list[SheetRead]:
    """Every Read call on the sheet in one stream, in order, each with the text returned for it.

    A call whose result never came is kept with no text (it returned nothing).
    """
    asked: dict[str, tuple[int | None, int | None, str]] = {}
    order: list[str] = []
    got: dict[str, tuple[str, bool]] = {}
    cwd = ""
    for event in _events(stream):
        if event.get("type") == "system" and event.get("subtype") == "init":
            cwd = str(event.get("cwd") or "")
        message: dict[str, Any] = event["message"] if isinstance(event.get("message"), dict) else {}
        content: list[Any] = message["content"] if isinstance(message.get("content"), list) else []
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                tool_input: dict[str, Any] = (
                    block["input"] if isinstance(block.get("input"), dict) else {}
                )
                path = str(tool_input.get("file_path", ""))
                if block.get("name") == "Read" and Path(path).name == SHEET_NAME:
                    tid = str(block.get("id"))
                    asked[tid] = (
                        _int(tool_input.get("offset")),
                        _int(tool_input.get("limit")),
                        _absolute(path, cwd),
                    )
                    order.append(tid)
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                tid = str(block.get("tool_use_id"))
                if tid in asked and tid not in got:
                    got[tid] = (_content_text(block.get("content")), bool(block.get("is_error")))
    return [
        SheetRead(
            tid,
            asked[tid][0],
            asked[tid][1],
            got[tid][0] if tid in got else None,
            got[tid][1] if tid in got else False,
            asked[tid][2],
        )
        for tid in order
    ]


def returned_lines(text: str | None, first: int) -> frozenset[int]:
    """The numbered lines a text returned: consecutive numbers from ``first``, as given."""
    if not text:
        return frozenset()
    numbers = [int(m.group(1)) for line in text.split("\n") if (m := _NUMBERED.match(line))]
    found: list[int] = []
    expected = first
    for n in numbers:
        if n != expected:
            break
        found.append(n)
        expected += 1
    return frozenset(found)


def classify(
    read: SheetRead,
    total: int,
    last_row_id: str = C.LAST_ROW_ID,
    earlier: Sequence[tuple[SheetRead, Classed]] = (),
) -> Classed:
    """§5.5's class of one read of a sheet of ``total`` numbered lines.

    ``earlier`` holds the same session's reads before this one, each with its class: a stub is
    ``unchanged`` only where one of them, of the same path, returned every line it asks for.
    """
    start = read.offset if read.offset is not None and read.offset > 1 else 1
    end = total if read.limit is None else min(start + max(read.limit, 0) - 1, total)
    asked = max(0, end - start + 1)
    to_end = asked > 0 and end >= total
    if read.text is None:
        return Classed("no_result", asked, 0, to_end, False)
    if TOKEN_LIMIT.search(read.text):
        return Classed("cut", asked, 0, to_end, False)
    if read.text.startswith(UNCHANGED):
        wanted = frozenset(range(start, end + 1))
        held = any(
            e.path == read.path and c.cls in ("whole", "part") and wanted <= c.lines
            for e, c in earlier
        )
        return Classed("unchanged" if held else "cut", asked, 0, to_end, False)
    if read.is_error:
        return Classed("error", asked, 0, to_end, False)
    lines = returned_lines(read.text, start)
    returned = len(lines)
    last_row = read.text is not None and f'"{last_row_id}"' in read.text
    if returned < asked or (to_end and not last_row):
        cls = "cut"
    elif start == 1 and to_end:
        cls = "whole"
    else:
        cls = "part"
    return Classed(cls, asked, returned, to_end, last_row, lines)


def classify_all(
    reads: Sequence[SheetRead], total: int, last_row_id: str = C.LAST_ROW_ID
) -> list[Classed]:
    """Every read of one session, in order, each classed against the reads before it."""
    done: list[tuple[SheetRead, Classed]] = []
    for read in reads:
        done.append((read, classify(read, total, last_row_id, done)))
    return [c for _, c in done]


def session_reads_text(text: str, total: int, last_row_id: str = C.LAST_ROW_ID) -> dict[str, Any]:
    """One stream's reads of the sheet, classed, with their counts."""
    reads = classify_all(sheet_reads(text), total, last_row_id)
    covered: frozenset[int] = frozenset().union(*(c.lines for c in reads)) if reads else frozenset()
    return {
        "missing": False,
        "reads": len(reads),
        **{cls: sum(c.cls == cls for c in reads) for cls in CLASSES},
        "covered_every_line": covered >= frozenset(range(1, total + 1)),
        "classes": [c.cls for c in reads],
    }


def session_reads(stream_path: Path, total: int) -> dict[str, Any]:
    """One session's reads of the sheet, classed; ``missing`` if its stream is not there."""
    if not stream_path.is_file():
        return {"missing": True}
    return session_reads_text(stream_path.read_text(errors="replace"), total)


def _sessions(run: Path) -> dict[str, list[str | None]]:
    """Every review session a run's two logs name, by side: one per try."""
    found: dict[str, list[str | None]] = {}
    for side, log in (
        ("injected", run / "events.jsonl"),
        ("twin", run / "controls" / "events.jsonl"),
    ):
        ids: list[str | None] = []
        for line in C.read_log(log)[0]:
            if line.get("kind") == "review_ran":
                ids.append((line.get("result") or {}).get("session_id"))
            elif line.get("kind") == "review_unavailable":
                ids.append(line.get("session_id"))
        found[side] = ids
    return found


def round_counts(run: Path, root: Path, arm: str) -> dict[str, Any]:
    """§5.5's counts for one run, per side, and the sessions under the root no log names."""
    total = C.SHEET_LINES[arm]
    logged = _sessions(run)
    named = {sid for ids in logged.values() for sid in ids if sid}
    on_disk = (
        sorted(p.name for p in root.iterdir() if p.is_dir() and _SESSION_ID.match(p.name))
        if root.is_dir()
        else []
    )
    out: dict[str, Any] = {"arm": arm, "numbered_lines": total, "sides": {}}
    groups = {**logged, "not_in_a_log": [s for s in on_disk if s not in named]}
    for side, ids in groups.items():
        rows = [
            session_reads(root / sid / STREAM[0] / STREAM[1], total) if sid else {"missing": True}
            for sid in ids
        ]
        present = [r for r in rows if not r["missing"]]
        out["sides"][side] = {
            "reviews": len(rows),
            "stream_missing_unknown": len(rows) - len(present),
            "read_the_sheet": sum(r["reads"] > 0 for r in present),
            "never_read_it": sum(r["reads"] == 0 for r in present),
            "read_calls": sum(r["reads"] for r in present),
            **{cls: sum(r[cls] for r in present) for cls in CLASSES},
            "covered_every_line": sum(r["covered_every_line"] for r in present),
        }
    out["cut"] = sum(s["cut"] for s in out["sides"].values())
    return out


def main(argv: list[str] | None = None) -> int:
    """Print the counts; exit 3 if any read is cut, 2 on a usage error."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("round")
    r.add_argument("--arm", choices=C.ARMS, required=True)
    r.add_argument("--run", type=Path, required=True)
    r.add_argument("--root", type=Path, required=True)
    r.add_argument("--out", type=Path)
    s = sub.add_parser("stream")
    s.add_argument("--arm", choices=C.ARMS, required=True)
    s.add_argument("stream", type=Path)
    s.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "round":
        found = round_counts(args.run.resolve(), args.root.resolve(), args.arm)
        cut = found["cut"]
    else:
        found = session_reads(args.stream.resolve(), C.SHEET_LINES[args.arm])
        found.pop("classes", None)
        cut = found.get("cut", 0)
    text = json.dumps(found, sort_keys=True)
    if args.out is not None:
        args.out.write_text(text + "\n")
    print(text)
    return 3 if cut else 0


def as_dict(c: Classed) -> dict[str, Any]:
    """A classed read without its line set, for a record."""
    d = asdict(c)
    d.pop("lines")
    return d


if __name__ == "__main__":
    sys.exit(main())
