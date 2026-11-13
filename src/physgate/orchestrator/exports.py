"""What a module's exports are, and what their bytes must be, as data and two checks.

A module keeps its exports (a part's STEP and STL files) in one folder of its own,
:data:`EXPORTS_DIR`, beside the script that wrote them. Shown as text such a file is thousands
of lines of numbers, and a binary one is a single line longer than any part of a review's diff
may hold. So the review packet may show an export as one line with its path, size, sha256 and a
summary the harness read from its bytes (``reviewers.packet``), in place of the bytes.

It does so only for a file the commit-time rule admitted with exactly those bytes, whose path is
an export's (:func:`is_export`), within :data:`MAX_EXPORT_BYTES`, and whose bytes are what its
suffix says (:func:`summary` answers ``None`` otherwise). Everything else stays in the diff.

**What a reviewer does not see in an admitted export,** stated as a limit: a STEP file's string
fields and comments are free text inside a valid file, and a binary STL file's 80-byte header,
its two attribute bytes a triangle and the low bits of every coordinate can carry any bytes. The
summary shows counts, a bounding box and two short header fields, not that text. The geometry
hash describes the shape a script built, not an export's bytes, so it bounds none of this; the
reviewer can still read the whole file in the packet's export of the commit.

The suffixes are data: adding a kind of export adds a suffix here and a check below, and the
helpers in the tool environment write the same folder and suffixes (a test holds them to it).
"""

from __future__ import annotations

import json
import math
import re
import struct
from pathlib import PurePosixPath

#: The folder of a module that holds its exports, and nothing else.
EXPORTS_DIR = "exports"
#: What an export's name ends in, compared without regard to case.
EXPORT_SUFFIXES: tuple[str, ...] = (".step", ".stl")
#: The largest export, in bytes, whose bytes may leave a review's diff.
MAX_EXPORT_BYTES = 2_000_000
#: The longest text taken from inside an export into its summary, in characters.
MAX_FIELD_CHARS = 80


def is_export(path: str) -> bool:
    """Whether ``path``, relative to the repository, names an export.

    That is a file directly inside a folder named :data:`EXPORTS_DIR`, its name ending in one
    of :data:`EXPORT_SUFFIXES`, and every character of the path printable, so that a line
    naming it cannot be broken in two. Whether the file is regular, and whether its folder is a
    module's own, are its readers' to check.
    """
    pure = PurePosixPath(path)
    return (
        path.isprintable()
        and pure.parent.name == EXPORTS_DIR
        and pure.name.casefold().endswith(EXPORT_SUFFIXES)
    )


def summary(path: str, body: bytes) -> str | None:
    """What the reviewer is told of an export's bytes, or ``None`` if they are not its kind.

    The kind is the suffix's: a STEP file must be an exchange structure from its first
    statement to its end marker; an STL file must be binary with a count that matches its size
    exactly, or ASCII from ``solid`` to ``endsolid``. Every number is finite. Text taken from
    inside the file is cut, stripped and quoted (:func:`_field`).
    """
    name = PurePosixPath(path).name.casefold()
    if name.endswith(".step"):
        return _step(body)
    if name.endswith(".stl"):
        return _stl_binary(body) or _stl_ascii(body)
    return None


def _field(text: str) -> str:
    """Session-written text as the reviewer sees it: printable only, cut, a JSON string."""
    kept = "".join(char for char in text if char.isprintable())
    return json.dumps(kept[:MAX_FIELD_CHARS])


def _number(value: float) -> str:
    return format(value, ".6g")


def _box(corners: list[float]) -> str:
    """The bounding box of corners given as x, y, z, x, y, z, ...; the file has no unit."""
    if not corners:
        return "no bounding box"
    low = [min(corners[axis::3]) for axis in range(3)]
    high = [max(corners[axis::3]) for axis in range(3)]
    return (
        f"bounding box from ({', '.join(map(_number, low))}) to "
        f"({', '.join(map(_number, high))}), in the file's units"
    )


#: Seven-bit text: the printable characters, tab and the two line endings.
_TEXT_BYTES = re.compile(rb"[\t\n\r\x20-\x7e]*")


# ---- STEP (ISO 10303-21) ----------------------------------------------------------------------

#: A string (a quote doubled inside), a comment, a statement's end, or a run of anything else.
_STEP_TOKEN = re.compile(rb"'(?:[^']|'')*'|/\*.*?\*/|;|[^';/]+|/", re.DOTALL)
_ENTITY = re.compile(r"#[0-9]+\s*=\s*\S")
_DATA = re.compile(r"DATA(\s*\(.*\))?", re.DOTALL)
_STRING = re.compile(r"'((?:[^']|'')*)'")
_HEADER_ENTRIES = frozenset({"FILE_DESCRIPTION", "FILE_NAME", "FILE_SCHEMA"})


def _statements(body: bytes) -> list[str] | None:
    """The file's statements with comments dropped, or ``None`` if one is left open.

    Every byte belongs to a token: a quote that opens no closed string, or a comment that is
    never closed, is a token of neither kind and leaves the match short of the end.
    """
    found: list[str] = []
    current: list[bytes] = []
    end = 0
    for match in _STEP_TOKEN.finditer(body):
        if match.start() != end:
            return None
        end = match.end()
        token = match.group()
        if token == b"/" and body[end : end + 1] == b"*":
            # A comment that is closed was matched whole; this one never is.
            return None
        if token == b";":
            found.append(b"".join(current).decode("ascii").strip())
            current = []
        elif not token.startswith(b"/*"):
            current.append(token)
    rest = b"".join(current)
    if end != len(body) or rest.strip():
        return None
    return found


def _first_string(statement: str) -> str:
    found = _STRING.search(statement)
    return found.group(1).replace("''", "'") if found else ""


def _step(body: bytes) -> str | None:
    if not _TEXT_BYTES.fullmatch(body):
        return None
    statements = _statements(body)
    if not statements or statements[:2] != ["ISO-10303-21", "HEADER"]:
        return None
    if statements[-1] != "END-ISO-10303-21" or "ENDSEC" not in statements:
        return None
    close = statements.index("ENDSEC")
    header = {s.split("(", 1)[0].strip(): s for s in statements[2:close]}
    sections = statements[close + 1 : -1]
    if not set(header) >= _HEADER_ENTRIES or not sections:
        return None
    entities, opened = 0, False
    for statement in sections:
        if not opened:
            if not _DATA.fullmatch(statement):
                return None
            opened = True
        elif statement == "ENDSEC":
            opened = False
        elif _ENTITY.match(statement):
            entities += 1
        else:
            return None
    if opened:
        return None
    schema = _first_string(header.get("FILE_SCHEMA", ""))
    name = _first_string(header.get("FILE_NAME", ""))
    return f"STEP, {entities} entities; schema {_field(schema)}; file name {_field(name)}"


# ---- STL --------------------------------------------------------------------------------------

_STL_HEADER = 80
#: A triangle: its normal and three corners, twelve 32-bit floats, then two attribute bytes.
_STL_TRIANGLE = struct.Struct("<12fH")
#: A facet of an ASCII file, word by word; a number stands for that many numbers.
_FACET: tuple[str | int, ...] = (
    "facet", "normal", 3, "outer", "loop",
    "vertex", 3, "vertex", 3, "vertex", 3,
    "endloop", "endfacet",
)  # fmt: skip


def _stl_binary(body: bytes) -> str | None:
    if len(body) < _STL_HEADER + 4:
        return None
    count = int.from_bytes(body[_STL_HEADER : _STL_HEADER + 4], "little")
    end = _STL_HEADER + 4 + count * _STL_TRIANGLE.size
    if len(body) != end:
        return None
    corners: list[float] = []
    for triangle in _STL_TRIANGLE.iter_unpack(body[_STL_HEADER + 4 : end]):
        values = triangle[:12]
        if not all(math.isfinite(value) for value in values):
            return None
        corners += values[3:]
    return f"binary STL, {count} triangles; {_box(corners)}"


def _stl_ascii(body: bytes) -> str | None:
    if not body.startswith(b"solid") or not _TEXT_BYTES.fullmatch(body):
        return None
    # Seven-bit already, so this reads each byte as itself and cannot fail.
    lines = body.decode("latin-1").splitlines()
    # The name after ``solid`` and ``endsolid`` is free text, and is not shown.
    if len(lines) < 2 or lines[-1].split()[:1] != ["endsolid"]:
        return None
    words = " ".join(lines[1:-1]).split()
    corners: list[float] = []
    count, at = 0, 0
    while at < len(words):
        numbers: list[float] = []
        for expected in _FACET:
            if isinstance(expected, str):
                if words[at : at + 1] != [expected]:
                    return None
                at += 1
                continue
            # A facet cut short ends in a word it lacks, so a short read is refused there.
            read = _numbers(words[at : at + expected])
            if read is None:
                return None
            numbers += read
            at += expected
        corners += numbers[3:]
        count += 1
    return f"ASCII STL, {count} triangles; {_box(corners)}"


def _numbers(words: list[str]) -> list[float] | None:
    try:
        values = [float(word) for word in words]
    except ValueError:
        return None
    return values if all(math.isfinite(value) for value in values) else None
