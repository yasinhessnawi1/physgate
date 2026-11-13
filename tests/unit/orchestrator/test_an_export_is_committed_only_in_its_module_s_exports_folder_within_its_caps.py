"""An attempt's exports are in scope only in its module's exports folder, valid and within caps.

A module keeps what a tool wrote for people and later tools (a part's STEP and STL files) in one
folder of its own, ``exports/``. The commit holds everything a session left in its worktree, so
the write-scope check refuses, with each path named, before the gate and the review:

- a file with an export suffix anywhere in the module but directly in its exports folder;
- anything in the exports folder that is no export (another suffix, a subfolder, a name that
  does not print);
- an export over 2,000,000 bytes, or whose bytes are not what its suffix says (a STEP exchange
  structure; a binary or ASCII STL file);
- exports that together, after the attempt, hold more than 16,000,000 bytes in the module.

Removing an export is in scope: that is the repair. An attempt that passes is what the review
packet may later show by size, sha256 and summary in place of bytes.
"""

from __future__ import annotations

import os
import struct
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from physgate.orchestrator import exports, merge
from physgate.orchestrator.merge import write_scope_violations

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
MODULE = "modules/chassis"
EXPORTS = f"{MODULE}/exports"
OUTSIDE = getattr(merge, "EXPORT_OUTSIDE", "(the reason for an export outside is not written)")
NOT_EXPORT = getattr(merge, "NOT_AN_EXPORT", "(the reason for a stray file is not written)")
TOO_BIG = getattr(merge, "EXPORT_TOO_BIG", "(the reason for a large export is not written)")
INVALID = getattr(merge, "EXPORT_INVALID", "(the reason for an invalid export is not written)")
FILE_CAP = getattr(exports, "MAX_EXPORT_BYTES", 2_000_000)
MODULE_CAP = getattr(exports, "MAX_MODULE_EXPORT_BYTES", 16_000_000)


def _step(size: int | None = None, entities: int = 3) -> bytes:
    """A valid STEP file; with ``size``, padded by a comment to exactly that many bytes."""
    data = "".join(f"#{n}=CARTESIAN_POINT('',(0.,0.,{n}.));\n" for n in range(1, entities + 1))
    body = (
        "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\n"
        "FILE_NAME('plate','',(''),(''),'','','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\n"
        f"ENDSEC;\nDATA;\n{data}ENDSEC;\nEND-ISO-10303-21;\n"
    ).encode()
    if size is None:
        return body
    pad = size - len(body) - len(b"/**/\n")
    assert pad >= 0
    return body + b"/*" + b"x" * pad + b"*/\n"


def _stl(triangles: int = 2) -> bytes:
    body = b"part".ljust(80, b" ") + struct.pack("<I", triangles)
    for n in range(triangles):
        body += struct.pack("<12fH", 0, 0, 1, 0, 0, n, 1, 0, n, 0, 1, n, 0)
    return body


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(repo: Path, files: Mapping[str, bytes | None]) -> None:
    for name, body in files.items():
        path = repo / name
        if body is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def _found(
    tmp_path: Path,
    after: Mapping[str, bytes | None],
    before: Mapping[str, bytes | None] | None = None,
) -> list[str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "run")
    _write(repo, {f"{MODULE}/chassis.py": b"length = 110\n", **(before or {})})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, after)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "attempt")
    return write_scope_violations(repo, base, _git(repo, "rev-parse", "HEAD"), MODULE)


def test_the_cap_on_a_module_s_exports_is_sixteen_million_bytes() -> None:
    assert MODULE_CAP == 16_000_000
    assert FILE_CAP == 2_000_000


def test_valid_exports_in_the_module_s_exports_folder_are_in_scope(tmp_path: Path) -> None:
    after = {
        f"{MODULE}/chassis.py": b"length = 120\n",
        f"{EXPORTS}/plate.step": _step(),
        f"{EXPORTS}/plate.stl": _stl(),
        f"{EXPORTS}/DECK.STEP": _step(),
    }
    assert _found(tmp_path, after) == []


@pytest.mark.parametrize(
    "path",
    [
        f"{MODULE}/plate.step",
        f"{MODULE}/parts/plate.stl",
        f"{MODULE}/PLATE.STEP",
        f"{MODULE}/export/plate.step",
    ],
)
def test_an_export_outside_the_module_s_exports_folder_is_refused(
    tmp_path: Path, path: str
) -> None:
    assert _found(tmp_path, {path: _step()}) == [f"{path} ({OUTSIDE})"]


@pytest.mark.parametrize(
    "path",
    [
        f"{EXPORTS}/notes.txt",
        f"{EXPORTS}/plate.step.txt",
        f"{EXPORTS}/sub/plate.step",
        f"{EXPORTS}/a/b/c.stl",
        f"{EXPORTS}/plate\t2.step",
    ],
)
def test_anything_in_the_exports_folder_that_is_no_export_is_refused(
    tmp_path: Path, path: str
) -> None:
    assert _found(tmp_path, {path: _step()}) == [f"{path} ({NOT_EXPORT})"]


def test_an_export_of_the_cap_s_size_is_in_scope_and_one_byte_more_is_refused(
    tmp_path: Path,
) -> None:
    at_cap = _step(FILE_CAP)
    assert len(at_cap) == FILE_CAP and exports.summary("x/exports/a.step", at_cap) is not None
    assert _found(tmp_path / "at", {f"{EXPORTS}/plate.step": at_cap}) == []
    over = _step(FILE_CAP + 1)
    found = _found(tmp_path / "over", {f"{EXPORTS}/plate.step": over})
    assert found == [f"{EXPORTS}/plate.step ({TOO_BIG})"]


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("plate.step", b"#!/bin/sh\necho not a part\n"),
        ("plate.step", _step()[:-5]),
        ("plate.stl", _stl()[:-1]),
        ("plate.stl", _step()),
        ("plate.step", _stl()),
    ],
)
def test_an_export_whose_bytes_are_not_what_its_suffix_says_is_refused(
    tmp_path: Path, name: str, body: bytes
) -> None:
    assert _found(tmp_path, {f"{EXPORTS}/{name}": body}) == [f"{EXPORTS}/{name} ({INVALID})"]


def test_exports_that_together_pass_the_module_s_cap_are_refused_with_the_total(
    tmp_path: Path,
) -> None:
    each = 1_900_000
    earlier = {f"{EXPORTS}/part{n}.step": _step(each) for n in range(8)}
    # Eight, committed earlier: 15,200,000 bytes, under the cap, and this attempt adds none.
    assert _found(tmp_path / "eight", {f"{MODULE}/chassis.py": b"x = 1\n"}, earlier) == []
    # A ninth: the total counts the files the attempt did not touch.
    found = _found(tmp_path / "nine", {f"{EXPORTS}/part8.step": _step(each)}, earlier)
    assert found == [f"{EXPORTS}/ (the module's exports hold {9 * each} bytes, over {MODULE_CAP})"]


def test_removing_an_export_is_in_scope(tmp_path: Path) -> None:
    before = {f"{EXPORTS}/plate.step": _step(), f"{MODULE}/plate.step": _step()}
    after: dict[str, bytes | None] = {f"{EXPORTS}/plate.step": None, f"{MODULE}/plate.step": None}
    assert _found(tmp_path, after, before) == []


def test_a_misplaced_file_is_named_before_a_malformed_export_each_in_git_s_order(
    tmp_path: Path,
) -> None:
    after = {
        f"{EXPORTS}/bad.stl": b"solid x\n",
        f"{EXPORTS}/notes.txt": b"a note\n",
        f"{MODULE}/loose.step": _step(),
        f"{EXPORTS}/ok.step": _step(),
    }
    assert _found(tmp_path, after) == [
        f"{EXPORTS}/notes.txt ({NOT_EXPORT})",
        f"{MODULE}/loose.step ({OUTSIDE})",
        f"{EXPORTS}/bad.stl ({INVALID})",
    ]
