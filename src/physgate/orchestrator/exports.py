"""What a module's exports are, and what their bytes must be, as data and two checks.

A module keeps its exports (a part's STEP and STL files) in one folder of its own,
:data:`EXPORTS_DIR`, beside the script that wrote them. Shown as text such a file is thousands
of lines of numbers, and a binary one is a single line longer than any part of a review's diff
may hold. So the review packet may show an export as one line with its path, size, sha256 and a
summary the harness read from its bytes (``reviewers.packet``), in place of the bytes.

It does so only for a file the commit-time rule admitted with exactly those bytes, whose path is
an export's (:func:`is_export`), within :data:`MAX_EXPORT_BYTES`, and whose bytes are what its
suffix says (:func:`summary` answers ``None`` otherwise). Everything else stays in the diff.

**What a reviewer does not see in an admitted export is counted and bounded** (:class:`FreeText`):
the bytes the writer does not write (a STEP file's comments, and its strings, keywords and stray
characters outside the writer's own; a binary STL file's header and attribute bytes; an ASCII
STL file's names) are counted on the export's line, an export with more than the budget is not
summarised but shown in full, and a binary STL file with a header or attribute byte of its own
is refused at commit. What stays unseen: the numbers themselves (the low bits of every
coordinate, which numbers a STEP entity holds), where the writer's own strings and words are
placed, the spacing between tokens, and up to the budget of free text. The geometry hash
describes the shape a script built, not an export's bytes, so it bounds none of this; the
reviewer can still read the whole file in the packet's export of the commit.

A circuit's exports (the circuit helper's KiCad rules-check report, netlist, parts list and a
PDF of the schematic) are admitted the same way, each by a check of its own kind and under its
own cap (:data:`EXPORT_CAPS`). The three texts are the reviewer's evidence and almost all their
words are the role's own (net names, values, references), so they are never summarised: the
review shows them in git's diff, as every other committed file a role writes
(:data:`SHOWN_IN_FULL`), and the cap keeps that a size one review reads. The PDF is one line
(size, sha256, pages) whose text is not shown: the same circuit is in the schematic and the
netlist, in full (:data:`PDF_UNSEEN`).

The suffixes are data: adding a kind of export adds a suffix here and a check below, and the
helpers in the tool environment write the same folder and suffixes (a test holds them to it).
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import struct
from dataclasses import dataclass
from pathlib import PurePosixPath

from physgate.orchestrator.export_writer import (
    FREE_TEXT_BUDGET,
    STEP_WRITER_STRINGS,
    STEP_WRITER_WORDS,
    STL_WRITER_HEADERS,
)

#: The folder of a module that holds its exports, and nothing else.
EXPORTS_DIR = "exports"
#: The exports a circuit leaves as text, which the review shows in full in git's diff as every
#: other committed file a role writes: KiCad's rules-check report, its netlist and the parts
#: list. Their caps keep "in full" a size a reviewer reads.
SHOWN_IN_FULL: tuple[str, ...] = (".erc.json", ".net", ".csv")
#: What an export's name ends in, compared without regard to case.
EXPORT_SUFFIXES: tuple[str, ...] = (".step", ".stl", ".pdf", *SHOWN_IN_FULL)
#: The largest export of any kind a commit may hold, in bytes; past it the attempt is refused.
MAX_EXPORT_BYTES = 2_000_000
#: Each kind's largest file, in bytes; one byte past it refuses the attempt, never cuts the file.
EXPORT_CAPS: dict[str, int] = {
    ".step": MAX_EXPORT_BYTES,
    ".stl": MAX_EXPORT_BYTES,
    ".pdf": MAX_EXPORT_BYTES,
    ".erc.json": 1_000_000,
    ".net": 1_000_000,
    ".csv": 200_000,
}
#: The most bytes a module's exports may hold together after an attempt.
MAX_MODULE_EXPORT_BYTES = 16_000_000
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
    kind = suffix_of(path)
    if kind == ".step":
        return _step(body)
    if kind == ".stl":
        return _stl_binary(body) or _stl_ascii(body)
    if kind == ".pdf":
        return _pdf(body)
    if kind == ".erc.json":
        return _rules_check_report(body)
    if kind == ".net":
        return _netlist(body)
    if kind == ".csv":
        return _parts_list(body)
    return None


def suffix_of(path: str) -> str | None:
    """The export suffix ``path``'s name ends in, in lower case, or ``None``."""
    name = PurePosixPath(path).name.casefold()
    return next((suffix for suffix in EXPORT_SUFFIXES if name.endswith(suffix)), None)


def cap_of(path: str) -> int:
    """The largest file of ``path``'s kind a commit may hold (:data:`EXPORT_CAPS`)."""
    kind = suffix_of(path)
    return MAX_EXPORT_BYTES if kind is None else EXPORT_CAPS[kind]


def shown_in_full(path: str) -> bool:
    """Whether ``path``'s kind stays in the review's diff, as text (:data:`SHOWN_IN_FULL`)."""
    return suffix_of(path) in SHOWN_IN_FULL


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


# ---- the circuit's exports: KiCad's report, netlist and parts list, and a PDF ------------------

#: What the line of a PDF says in place of a free-text count: the limit a reviewer is shown.
PDF_UNSEEN = (
    "its text is not shown or counted here (the schematic and the netlist in the diff hold "
    "the same circuit in full)"
)
#: The kinds whose bytes the review shows in full, never as a line.
_TEXT_KINDS = frozenset({"text"})
_PDF_VERSION = re.compile(rb"%PDF-(1\.[0-7]|2\.0)\r?\n")
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![A-Za-z0-9])")
_PDF_END = re.compile(rb"%%EOF\s*\Z")
#: KiCad's rules-check report: its layout's name, and the fields every report holds.
ERC_SCHEMA = "https://schemas.kicad.org/erc.v1.json"
_ERC_FIELDS = frozenset({"$schema", "kicad_version", "sheets", "source", "date"})
_ERC_FINDING_TEXT = ("type", "severity", "description")
#: The parts list's header, as the circuit helper asks KiCad to write it.
PARTS_LIST_HEADER = ("Reference", "Value", "Footprint", "Quantity", "DNP")
#: A netlist's opening, and the parts of the export every netlist holds.
_NETLIST_START = re.compile(rb'\(export\s+\(version\s+"E"\)')
_NETLIST_PARTS = ("design", "components", "nets")


def _utf8(body: bytes) -> str | None:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _pdf(body: bytes) -> str | None:
    """A PDF from its header to its end marker, with at least one page: version and pages."""
    version = _PDF_VERSION.match(body)
    if version is None or _PDF_END.search(body) is None:
        return None
    pages = len(_PDF_PAGE.findall(body))
    if pages == 0:
        return None
    noun = "page" if pages == 1 else "pages"
    return f"PDF {version.group(1).decode()}, {pages} {noun}"


def _no_constant(name: str) -> object:
    msg = f"{name} is no number"
    raise ValueError(msg)


def _rules_check_report(body: bytes) -> str | None:
    """KiCad's JSON report: its schema and fields, and every finding's texts as text."""
    text = _utf8(body)
    if text is None:
        return None
    try:
        report = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(report, dict) or not report.keys() >= _ERC_FIELDS:
        return None
    sheets = report["sheets"]
    if report["$schema"] != ERC_SCHEMA or not isinstance(report["kicad_version"], str):
        return None
    if not isinstance(sheets, list) or not all(isinstance(sheet, dict) for sheet in sheets):
        return None
    findings = 0
    for sheet in sheets:
        for value in sheet.values():
            if not isinstance(value, list):
                continue
            for finding in value:
                if not isinstance(finding, dict) or not all(
                    isinstance(finding.get(key), str) for key in _ERC_FINDING_TEXT
                ):
                    return None
                findings += 1
    return f"KiCad rules-check report, {findings} findings"


def _balanced(text: str) -> bool:
    """Whether every parenthesis outside a string closes, and the text is one expression."""
    depth, quoted, escaped = 0, False, False
    closed_at = -1
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            if closed_at >= 0:
                return False
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0:
                closed_at = index
        elif closed_at >= 0 and not char.isspace():
            return False
    return depth == 0 and not quoted and closed_at >= 0


def _netlist(body: bytes) -> str | None:
    """KiCad's S-expression netlist: one balanced export with its design, components and nets."""
    text = _utf8(body)
    if text is None or not _NETLIST_START.match(body) or not _balanced(text):
        return None
    if not all(re.search(rf"\({part}\s", text) for part in _NETLIST_PARTS):
        return None
    components, nets = len(re.findall(r"\(comp\s", text)), len(re.findall(r"\(net\s", text))
    return f"KiCad netlist, {components} components, {nets} nets"


def _parts_list(body: bytes) -> str | None:
    """The parts list: the helper's header, then rows of exactly its fields."""
    text = _utf8(body)
    if text is None:
        return None
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or tuple(rows[0]) != PARTS_LIST_HEADER:
        return None
    if not all(len(row) == len(PARTS_LIST_HEADER) for row in rows[1:]):
        return None
    return f"parts list, {len(rows) - 1} rows"


# ---- free text --------------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeText:
    """The bytes of an export that its summary does not show and its writer does not write.

    Counted where they are. A STEP file: every byte of a comment (``comments``); each distinct
    string the writer does not write, by its bytes, once (``strings``); each distinct keyword or
    enumeration the writer does not write, likewise (``words``); and every byte that is none of
    the exchange structure's tokens (``other``). A binary STL file: each header byte that differs
    from the writer's header (``header``) and each attribute byte that is not zero
    (``attributes``). An ASCII STL file: each distinct name after ``solid`` or ``endsolid``, by
    its bytes (``strings``). What the writer writes is data, measured
    (:mod:`physgate.orchestrator.export_writer`).

    A distinct string or word is counted once because a repeat tells a reader nothing the first
    did not; where it repeats is the residual this count leaves, with the numbers themselves.

    A PDF's text is not read or counted: its line says so (:data:`PDF_UNSEEN`). The three text
    exports (:data:`SHOWN_IN_FULL`) are never summarised: every byte is in the diff.
    """

    kind: str
    comments: int = 0
    strings: int = 0
    words: int = 0
    other: int = 0
    header: int = 0
    attributes: int = 0

    @property
    def total(self) -> int:
        """Every byte counted."""
        return (
            self.comments + self.strings + self.words + self.other + self.header + self.attributes
        )

    @property
    def summarised(self) -> bool:
        """Whether the export may be shown as one line.

        Only with no header or attribute byte of its own, and at most
        :data:`~physgate.orchestrator.export_writer.FREE_TEXT_BUDGET` bytes in all.
        """
        if self.kind in _TEXT_KINDS:
            return False
        return self.header == 0 and self.attributes == 0 and self.total <= FREE_TEXT_BUDGET

    def described(self) -> str:
        """The counts as the reviewer's line gives them."""
        if self.kind == "PDF":
            return PDF_UNSEEN
        if self.kind == "binary STL":
            parts = f"header {self.header}, attributes {self.attributes}"
        elif self.kind == "ASCII STL":
            parts = f"names {self.strings}"
        else:
            parts = (
                f"comments {self.comments}, strings {self.strings}, words {self.words}, "
                f"other characters {self.other}"
            )
        return f"free text {self.total} bytes ({parts})"


def free_text(path: str, body: bytes) -> FreeText | None:
    """The free text in an export's bytes; ``None`` if they are not its kind (:func:`summary`)."""
    if summary(path, body) is None:
        return None
    kind = suffix_of(path)
    if kind == ".pdf":
        return FreeText(kind="PDF")
    if kind in SHOWN_IN_FULL:
        return FreeText(kind="text")
    if kind == ".step":
        return _step_free_text(body)
    if _stl_binary(body) is not None:
        return _stl_binary_free_text(body)
    return _stl_ascii_free_text(body)


#: Outside strings and comments: what carries no text (an entity's number, a number, the
#: punctuation and spaces of the structure), a keyword or an enumeration, or any other byte.
_STEP_PLAIN = re.compile(
    rb"(?P<plain>#[0-9]+|[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?|[\s()=,;*$-]+)"
    rb"|(?P<word>\.[A-Za-z_][A-Za-z0-9_]*\.|[A-Za-z_][A-Za-z0-9_]*)"
    rb"|(?P<other>.)",
    re.DOTALL,
)


def _step_free_text(body: bytes) -> FreeText:
    comments, other = 0, 0
    strings: set[bytes] = set()
    words: set[bytes] = set()
    for token in _STEP_TOKEN.finditer(body):
        text = token.group()
        if text.startswith(b"'"):
            strings.add(text[1:-1])
        elif text.startswith(b"/*"):
            comments += len(text)
        else:
            for piece in _STEP_PLAIN.finditer(text):
                if piece.lastgroup == "word":
                    words.add(piece.group())
                elif piece.lastgroup == "other":
                    other += 1
    return FreeText(
        kind="STEP",
        comments=comments,
        strings=sum(len(s) for s in strings if s.decode("ascii") not in STEP_WRITER_STRINGS),
        words=sum(len(w) for w in words if w.decode("ascii") not in STEP_WRITER_WORDS),
        other=other,
    )


def _stl_binary_free_text(body: bytes) -> FreeText:
    header = body[:_STL_HEADER]
    differing = min(
        sum(mine != writers for mine, writers in zip(header, known, strict=True))
        for known in STL_WRITER_HEADERS
    )
    # Each triangle's two attribute bytes are its last two: 48 and 49 bytes into its 50.
    first = _STL_HEADER + 4 + 48
    attributes = body[first :: _STL_TRIANGLE.size] + body[first + 1 :: _STL_TRIANGLE.size]
    return FreeText(
        kind="binary STL",
        header=differing,
        attributes=len(attributes) - attributes.count(0),
    )


def _stl_ascii_free_text(body: bytes) -> FreeText:
    lines = body.decode("latin-1").splitlines()
    names = {
        lines[0].removeprefix("solid").strip(),
        lines[-1].strip().removeprefix("endsolid").strip(),
    }
    return FreeText(kind="ASCII STL", strings=sum(len(name) for name in names))
