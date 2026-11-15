"""KiCad's three text exports are admitted at commit by their own checks, under caps, in the diff.

A module's circuit is evidence in three files the circuit helper writes into ``exports/``:
KiCad's rules-check report (``.erc.json``), its netlist (``.net``) and the parts list
(``.csv``). Read here:

- each kind has its own check of the bytes: the report is KiCad's JSON report (its schema, its
  version, its sheets of findings); the netlist KiCad's S-expression export, balanced, with its
  design, components and nets; the parts list a CSV with the helper's fixed header and every
  row of that many fields. A file of another kind under the right suffix is refused, and so is
  one no reader can parse: a check never raises, whatever the bytes;
- each kind has a stated cap, checked at commit: one byte over is refused, never cut;
- in the review packet the three stay in git's diff, as every other committed file a role
  writes does, byte for byte, and nothing names them on a line of their own;
- a role commits no PDF: a reviewer is not shown a PDF's text, so a ``.pdf`` in ``exports/`` is
  no export and refused, as it was before these kinds.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

import pytest

from physgate.orchestrator import apply, exports, merge
from physgate.orchestrator.merge import admitted_exports, write_scope_violations
from physgate.reviewers import packet

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
MODULE = "modules/board"
EXPORTS = f"{MODULE}/exports"
INVALID = getattr(merge, "EXPORT_INVALID", "(the reason for an invalid export is not written)")
#: The caps this step states: each kind's largest file, in bytes.
CAPS = {
    ".erc.json": 1_000_000,
    ".net": 1_000_000,
    ".csv": 200_000,
}

REPORT = (
    json.dumps(
        {
            "$schema": "https://schemas.kicad.org/erc.v1.json",
            "coordinate_units": "mm",
            "date": "2000-01-01T00:00:00",
            "ignored_checks": [],
            "included_severities": ["error", "warning"],
            "kicad_version": "10.0.8",
            "sheets": [
                {
                    "path": "/",
                    "uuid_path": "/00000000-0000-0000-0000-000000000001",
                    "violations": [
                        {
                            "description": "Pin not connected",
                            "items": [
                                {
                                    "description": "Symbol R1 Pin 2 [Passive, Line]",
                                    "pos": {"x": 1.0, "y": 2.0},
                                    "uuid": "00000000-0000-0000-0000-000000000010",
                                }
                            ],
                            "severity": "error",
                            "type": "pin_not_connected",
                        }
                    ],
                }
            ],
            "source": "board.kicad_sch",
        },
        indent=2,
    )
    + "\n"
).encode()
#: As KiCad 10 writes it (tabs, one expression per line), cut short.
NETLIST = (
    b'(export\n\t(version "E")\n'
    b"\t(design\n"
    b'\t\t(source "board.kicad_sch")\n'
    b'\t\t(date "2000-01-01T00:00:00")\n'
    b'\t\t(tool "Eeschema 10.0.8")\n'
    b'\t\t(sheet\n\t\t\t(number "1")\n\t\t\t(name "/")\n\t\t\t(tstamps "/")\n\t\t)\n'
    b"\t)\n"
    b"\t(components\n"
    b'\t\t(comp\n\t\t\t(ref "R1")\n\t\t\t(value "10k")\n'
    b'\t\t\t(footprint "Resistor_SMD:R_0603_1608Metric")\n\t\t)\n'
    b"\t)\n"
    b'\t(libraries\n\t\t(library\n\t\t\t(logical "Device")\n'
    b'\t\t\t(uri "${KICAD10_SYMBOL_DIR}/Device.kicad_symdir")\n\t\t)\n\t)\n'
    b"\t(nets\n"
    b'\t\t(net\n\t\t\t(code "1")\n\t\t\t(name "/A")\n\t\t\t(class "Default")\n'
    b'\t\t\t(node\n\t\t\t\t(ref "R1")\n\t\t\t\t(pin "1")\n\t\t\t\t(pintype "passive")\n'
    b"\t\t\t)\n\t\t)\n\t)\n)\n"
)
PARTS = (
    b'"Reference","Value","Footprint","Quantity","DNP"\n'
    b'"J1","Conn_01x02","Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical","1",""\n'
    b'"R1","10k","Resistor_SMD:R_0603_1608Metric","1",""\n'
)


KINDS = {".erc.json": REPORT, ".net": NETLIST, ".csv": PARTS}
NOT_EXPORT = getattr(merge, "NOT_AN_EXPORT", "(the reason for a stray file is not written)")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(tmp_path: Path, after: Mapping[str, bytes]) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "run")
    (repo / MODULE).mkdir(parents=True)
    (repo / MODULE / "board.kicad_sch").write_bytes(b"(kicad_sch (version 20250114))\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    for name, body in after.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "attempt")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _answer(call: Callable[[], object]) -> object:
    """What ``call`` answered, or what it raised: a check that raises fails an assertion here."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc


def _found(tmp_path: Path, after: Mapping[str, bytes]) -> list[str]:
    repo, base, commit = _commit(tmp_path, after)
    return write_scope_violations(repo, base, commit, MODULE)


# ---- the kinds, their checks and their caps -----------------------------------------------------


def test_the_three_ecad_kinds_are_exports_beside_the_cad_ones() -> None:
    assert set(exports.EXPORT_SUFFIXES) == {".step", ".stl", *CAPS}
    for suffix in CAPS:
        assert exports.is_export(f"{EXPORTS}/board{suffix}"), suffix


def test_each_kind_s_cap_is_stated() -> None:
    caps = getattr(exports, "EXPORT_CAPS", {})
    for suffix, cap in CAPS.items():
        assert caps.get(suffix) == cap, suffix
    assert caps.get(".step") == caps.get(".stl") == exports.MAX_EXPORT_BYTES == 2_000_000


@pytest.mark.parametrize("suffix", list(KINDS))
def test_each_kind_s_check_accepts_what_the_helper_writes(tmp_path: Path, suffix: str) -> None:
    path = f"{EXPORTS}/board{suffix}"
    assert exports.summary(path, KINDS[suffix]) is not None, suffix
    assert _found(tmp_path, {path: KINDS[suffix]}) == []


def test_all_three_are_admitted_together_in_one_attempt(tmp_path: Path) -> None:
    after = {f"{EXPORTS}/board{suffix}": body for suffix, body in KINDS.items()}
    assert _found(tmp_path, after) == []


WRONG = [
    (".erc.json", PARTS),
    (".erc.json", b'{"sheets": []}\n'),
    (".erc.json", REPORT.replace(b"erc.v1.json", b"drc.v1.json")),
    (".erc.json", REPORT.replace(b'"severity": "error"', b'"severity": 7')),
    (".erc.json", REPORT[:-10]),
    (".net", NETLIST[:-2]),
    (".net", NETLIST.replace(b"(nets", b"(nots")),
    (".net", PARTS),
    (".net", b"(kicad_sch (version 20250114))\n"),
    (".csv", PARTS.replace(b'"Quantity",', b"")),
    (".csv", PARTS + b'"R2","1k"\n'),
    (".csv", NETLIST),
    (".csv", b"\xff\xfe" + PARTS),
    # Bytes no reader parses: each check answers "not this kind" and raises nothing.
    (".erc.json", b"[" * 100_000 + b"]" * 100_000),
    (".erc.json", b"\xff" + REPORT),
    (".net", b"\xc3\x28" + NETLIST),
    (".net", NETLIST.replace(b'"10k"', b'"10k')),
    (".csv", PARTS + b'"R2","' + b"9" * 131_073 + b'","x","1",""\n'),
    (".csv", PARTS + b'"R2","unclosed\n'),
]


@pytest.mark.parametrize(("suffix", "body"), WRONG)
def test_another_kind_under_the_right_suffix_is_refused(
    tmp_path: Path, suffix: str, body: bytes
) -> None:
    path = f"{EXPORTS}/board{suffix}"
    told = _answer(lambda: exports.summary(path, body))
    assert told is None, told
    found = _answer(lambda: _found(tmp_path, {path: body}))
    assert found == [f"{path} ({INVALID})"]


def _at_size(suffix: str, size: int) -> bytes:
    """A valid export of ``suffix`` padded to exactly ``size`` bytes."""
    if suffix == ".csv":
        row, last = b'"R9","1k","R_0603","1",""\n', b'"R0","","x","1",""\n'
        rows = (size - len(PARTS) - 2 * len(last)) // len(row)
        value = b"9" * (size - len(PARTS) - rows * len(row) - len(last))
        body = PARTS + row * rows + last.replace(b'"",', b'"' + value + b'",', 1)
    elif suffix == ".net":
        # Spaces between expressions, on lines of their own: the same netlist to any reader.
        filler = size - len(NETLIST)
        lines = b"".join(b" " * 99 + b"\n" for _ in range(filler // 100))
        lines += b" " * (filler % 100)
        body = NETLIST.replace(b"\t(nets\n", b"\t(nets\n" + lines, 1)
    else:
        # One field more, after the opening line it replaces the line break of.
        filler = size - len(REPORT) - len(b'  "x": "",')
        body = REPORT.replace(b"\n", b'\n  "x": "' + b"y" * filler + b'",', 1)
    assert len(body) == size, (suffix, len(body), size)
    return body


@pytest.mark.parametrize("suffix", list(CAPS))
def test_a_file_of_its_cap_is_admitted_and_one_byte_more_is_refused_not_cut(
    tmp_path: Path, suffix: str
) -> None:
    path = f"{EXPORTS}/board{suffix}"
    at_cap = _at_size(suffix, CAPS[suffix])
    assert exports.summary(path, at_cap) is not None
    assert _found(tmp_path / "at", {path: at_cap}) == []
    over = _at_size(suffix, CAPS[suffix] + 1)
    assert exports.summary(path, over) is not None
    found = _found(tmp_path / "over", {path: over})
    assert found == [f"{path} (an export over {CAPS[suffix]} bytes)"]
    repo, base, commit = _commit(tmp_path / "admit", {path: over})
    assert admitted_exports(repo, base, commit, MODULE) == ()


# ---- what the review packet shows of each kind --------------------------------------------------


def test_the_packet_shows_the_three_texts_as_git_s_diff_and_names_none_on_a_line(
    tmp_path: Path,
) -> None:
    after = {f"{EXPORTS}/board{suffix}": body for suffix, body in KINDS.items()}
    repo, base, commit = _commit(tmp_path, after)
    # The commit-time rule admits none of them to leave the diff.
    admitted = admitted_exports(repo, base, commit, MODULE)
    assert admitted == ()
    every = frozenset((path, hashlib.sha256(body).hexdigest()) for path, body in after.items())
    plain = subprocess.run(
        ["git", "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--text", base, commit],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        check=True,
    ).stdout
    # Each text exactly as git's diff gives every committed file: nothing marked, folded, cut
    # or named on a line of its own, even were the packet handed all three as admitted.
    for given in (frozenset(), every):
        shown = packet._diff(repo, base, commit, given)
        assert shown == plain
        assert packet.EXPORTS_HEADER.encode() not in shown
    for body in (REPORT, NETLIST, PARTS):
        for text_line in body.splitlines():
            assert b"+" + text_line in plain.splitlines(), text_line


@pytest.mark.parametrize(
    "body", [b"%PDF-1.5\n1 0 obj\n<< /Type /Page >>\nendobj\ntrailer\n%%EOF\n", b"anything"]
)
def test_a_pdf_in_the_exports_folder_is_no_export_and_is_refused(
    tmp_path: Path, body: bytes
) -> None:
    path = f"{EXPORTS}/board.pdf"
    assert not exports.is_export(path)
    assert exports.summary(path, body) is None
    assert _found(tmp_path, {path: body}) == [f"{path} ({NOT_EXPORT})"]


def test_no_check_raises_whatever_the_bytes() -> None:
    for suffix in KINDS:
        for body in (b"", b"\x00" * 64, b'"' * 200_000, b"(" * 100_000, b"{" * 100_000):
            told = _answer(partial(exports.summary, f"{EXPORTS}/board{suffix}", body))
            assert told is None, (suffix, told)


@pytest.mark.parametrize("suffix", [".erc.json", ".net", ".csv"])
def test_a_text_export_s_line_too_long_is_refused_as_any_file_s_without_the_free_text_advice(
    suffix: str,
) -> None:
    path = f"{EXPORTS}/board{suffix}"
    told = apply.too_long(packet.LongLine(path=path, line=3, before=False, bytes=30_000))
    plain = apply.too_long(packet.LongLine(path=f"{MODULE}/board.py", line=3, before=False,
                                           bytes=30_000))  # fmt: skip
    assert told == plain.replace(f"{MODULE}/board.py", path)
    assert "free text" not in told
