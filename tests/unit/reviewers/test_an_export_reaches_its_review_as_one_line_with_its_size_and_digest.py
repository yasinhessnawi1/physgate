"""A module's export reaches its review as one line with its path, size and sha256, never as bytes.

A module keeps what a tool wrote for people and later tools (a part's STEP and STL files) in one
folder of its own, ``exports/``. Shown as text, such a file is thousands of lines of numbers no
reviewer reads, and a binary one is a single line too long for any part of the diff, so the
packet could not be issued at all. So the diff a review reads names each export once, on a line
of its own after git's change, by what was done to it, its size and its sha256; the export of
the attempt's commit still holds the file whole.

Only the shape the commit-time rule admits is shown so: a regular file with an export suffix
directly inside a folder named ``exports``. Anything else, a file of that suffix elsewhere,
another file inside the folder, a link, or a name with a line break, stays in git's diff as it
always was, so nothing an attempt names can hide bytes from the reviewer or write a line of the
diff for it. An attempt with no export has the diff git gives, byte for byte.
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator import exports
from physgate.orchestrator.protocols import IssuedSpec
from physgate.reviewers import packet
from physgate.reviewers.rubric import Rubric

REPO = Path(__file__).resolve().parents[3]
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
STEP_PATH = f"{MODULE}/exports/plate.step"
STL_PATH = f"{MODULE}/exports/plate.stl"
#: A STEP file is text: many short lines a reviewer would page through for nothing.
STEP = (
    b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
    + b"".join(b"#%d=CARTESIAN_POINT('',(0.,0.,%d.));\n" % (n, n) for n in range(400))
    + b"ENDSEC;\nEND-ISO-10303-21;\n"
)
#: A binary STL file has no line break to cut at: one line longer than any part may hold.
STL = bytes(b for b in range(256) if b not in b"\r\n") * 200
MARK = b"CARTESIAN_POINT"
HEADER = packet.EXPORTS_HEADER.encode()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(repo: Path, files: dict[str, bytes | None]) -> None:
    for name, body in files.items():
        path = repo / name
        if body is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def _change(
    tmp_path: Path, before: dict[str, bytes | None], after: dict[str, bytes | None]
) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    _write(repo, {f"{MODULE}/chassis.py": b"length = 110\n", **before})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, after)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "attempt")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _added(path: str, body: bytes) -> bytes:
    return f"exported file {path}: added, {len(body)} bytes, sha256 {_sha(body)}".encode()


def _lines(diff: bytes) -> list[bytes]:
    return diff.split(b"\n")


def _named_by_git(diff: bytes) -> list[bytes]:
    return [line for line in _lines(diff) if line.startswith(b"diff --git ")]


# ---- what an export is ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        STEP_PATH,
        STL_PATH,
        f"{MODULE}/exports/PLATE.STEP",
        f"{MODULE}/exports/mount-arm_2.Stl",
        "exports/plate.step",
    ],
)
def test_a_file_with_an_export_suffix_directly_in_an_exports_folder_is_an_export(
    path: str,
) -> None:
    assert exports.is_export(path) is True


@pytest.mark.parametrize(
    "path",
    [
        f"{MODULE}/plate.step",
        f"{MODULE}/exports/notes.txt",
        f"{MODULE}/exports/plate.step.txt",
        f"{MODULE}/exports/sub/plate.step",
        f"{MODULE}/export/plate.step",
        f"{MODULE}/Exports/plate.step",
        f"{MODULE}/exports/",
        f"{MODULE}/exports",
        "plate.step",
        f"{MODULE}/exports/a\nb.step",
        f"{MODULE}/exports/a\rb.stl",
        f"{MODULE}/exports/a\tb.stl",
        f"{MODULE}/exports/a\x1bb.stl",
        f"{MODULE}/exports/a b.stl",
    ],
)
def test_anything_else_is_no_export(path: str) -> None:
    assert exports.is_export(path) is False


def test_the_folder_and_suffixes_are_the_ones_the_design_helper_writes() -> None:
    # The helper never imports the harness, so its folder and suffixes are read from its source.
    tree = ast.parse((REPO / "toolenv" / "helpers" / "geometry.py").read_text(encoding="utf-8"))
    folder = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "EXPORTS" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert folder == [exports.EXPORTS_DIR]
    # An f-string's literal parts are constants too, so this finds the suffixes it formats.
    written = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in (".step", ".stl", ".dxf", ".svg")
    }
    assert written == set(exports.EXPORT_SUFFIXES)


# ---- what the review's diff shows -------------------------------------------------------------


def test_an_added_export_is_one_line_with_its_size_and_digest_and_none_of_its_bytes(
    tmp_path: Path,
) -> None:
    repo, base, commit = _change(
        tmp_path, {}, {f"{MODULE}/chassis.py": b"length = 120\n", STEP_PATH: STEP, STL_PATH: STL}
    )
    diff = packet._diff(repo, base, commit)
    assert b"-length = 110\n+length = 120\n" in diff
    assert MARK not in diff and STL[:64] not in diff
    assert [line for line in _named_by_git(diff) if b"/exports/" in line] == []
    # After git's own change, a header and one line per export, in path order.
    assert diff.endswith(
        b"\n".join([HEADER, _added(STEP_PATH, STEP), _added(STL_PATH, STL)]) + b"\n"
    )
    assert _lines(diff).count(HEADER) == 1


def test_a_changed_export_names_its_size_and_digest_before_and_after(tmp_path: Path) -> None:
    newer = STEP.replace(b"0.,0.,1.", b"0.,0.,1.5")
    repo, base, commit = _change(tmp_path, {STEP_PATH: STEP}, {STEP_PATH: newer})
    diff = packet._diff(repo, base, commit)
    assert MARK not in diff
    assert _named_by_git(diff) == []
    expected = (
        f"exported file {STEP_PATH}: changed from {len(STEP)} bytes, sha256 {_sha(STEP)}"
        f" to {len(newer)} bytes, sha256 {_sha(newer)}"
    ).encode()
    assert diff == HEADER + b"\n" + expected + b"\n"


def test_a_removed_export_names_what_it_was(tmp_path: Path) -> None:
    repo, base, commit = _change(tmp_path, {STL_PATH: STL}, {STL_PATH: None})
    diff = packet._diff(repo, base, commit)
    expected = f"exported file {STL_PATH}: removed, was {len(STL)} bytes, sha256 {_sha(STL)}"
    assert diff == HEADER + b"\n" + expected.encode() + b"\n"


def test_a_renamed_export_is_one_line_removed_and_one_added(tmp_path: Path) -> None:
    moved = f"{MODULE}/exports/deck.step"
    repo, base, commit = _change(tmp_path, {STEP_PATH: STEP}, {STEP_PATH: None, moved: STEP})
    diff = packet._diff(repo, base, commit)
    removed = f"exported file {STEP_PATH}: removed, was {len(STEP)} bytes, sha256 {_sha(STEP)}"
    assert diff == b"\n".join([HEADER, _added(moved, STEP), removed.encode()]) + b"\n"


def test_an_export_with_no_line_break_leaves_no_line_too_long_for_a_review(
    tmp_path: Path,
) -> None:
    repo, base, commit = _change(tmp_path, {}, {STL_PATH: STL})
    # The control: git's own diff of it holds a line no part can hold.
    plain = subprocess.run(
        ["git", "diff", "--text", base, commit], cwd=repo, env=_ENV, capture_output=True, check=True
    ).stdout
    assert packet.first_long_line(plain) is not None
    assert packet.long_line(repo, base, commit) is None
    parts = packet.split_parts(packet._diff(repo, base, commit), packet.DIFF_PART)
    assert b"".join(body for _, body in parts) == packet._diff(repo, base, commit)


@pytest.mark.parametrize(
    "path",
    [
        f"{MODULE}/plate.step",
        f"{MODULE}/exports/notes.txt",
        f"{MODULE}/exports/sub/plate.step",
        f"{MODULE}/exports/a\nexported file x: added.step",
    ],
)
def test_what_the_commit_rule_would_not_admit_as_an_export_is_shown_as_git_shows_it(
    tmp_path: Path, path: str
) -> None:
    repo, base, commit = _change(tmp_path, {}, {path: STEP})
    diff = packet._diff(repo, base, commit)
    assert MARK in diff
    assert len(_named_by_git(diff)) == 1
    assert HEADER not in diff
    assert not any(line.startswith(b"exported file") for line in _lines(diff))


def test_a_name_that_is_not_utf8_is_shown_as_git_shows_it(tmp_path: Path) -> None:
    repo, base, commit = _change(tmp_path, {}, {f"{MODULE}/chassis.py": b"length = 120\n"})
    # Written into git's index by bytes: a file system may refuse such a name.
    done = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        env=_ENV,
        input=STEP,
        capture_output=True,
        check=True,
    )
    blob = done.stdout.decode().strip()
    name = MODULE.encode() + b"/exports/plate\xff.step"
    subprocess.run(
        [
            b"git",
            b"update-index",
            b"--add",
            b"--cacheinfo",
            b"100644," + blob.encode() + b"," + name,
        ],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        check=True,
    )
    _git(repo, "commit", "-q", "-m", "a name git holds by bytes")
    named = _git(repo, "rev-parse", "HEAD")
    diff = packet._diff(repo, commit, named)
    assert MARK in diff
    assert HEADER not in diff


def test_a_link_named_like_an_export_is_shown_as_git_shows_it(tmp_path: Path) -> None:
    repo, base, commit = _change(tmp_path, {}, {f"{MODULE}/chassis.py": b"length = 120\n"})
    link = repo / MODULE / "exports" / "plate.step"
    link.parent.mkdir(parents=True)
    link.symlink_to("../chassis.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "link")
    linked = _git(repo, "rev-parse", "HEAD")
    diff = packet._diff(repo, commit, linked)
    assert b"new file mode 120000" in diff and b"+../chassis.py" in diff
    assert HEADER not in diff


def test_an_export_and_a_file_beside_it_are_each_shown_their_own_way(tmp_path: Path) -> None:
    beside = f"{MODULE}/exports/notes.txt"
    repo, base, commit = _change(tmp_path, {}, {STEP_PATH: STEP, beside: b"a note\n"})
    diff = packet._diff(repo, base, commit)
    assert b"+a note\n" in diff and MARK not in diff
    assert [line for line in _named_by_git(diff) if b"/exports/" in line] == [
        f"diff --git a/{beside} b/{beside}".encode()
    ]
    assert _lines(diff)[-2:] == [_added(STEP_PATH, STEP), b""]


def test_an_attempt_with_no_export_has_the_diff_git_gives_byte_for_byte(tmp_path: Path) -> None:
    repo, base, commit = _change(tmp_path, {}, {f"{MODULE}/chassis.py": b"length = 120\n"})
    plain = subprocess.run(
        ["git", "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--text", base, commit],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        check=True,
    ).stdout
    assert packet._diff(repo, base, commit) == plain


# ---- the packet as issued and held --------------------------------------------------------------


def test_the_issued_diff_carries_the_export_lines_and_is_held_to_them(tmp_path: Path) -> None:
    attempt = make_attempt(tmp_path, stream())
    _write(attempt.worktree, {"m/exports/plate.step": STEP, "m/exports/plate.stl": STL})
    _git(attempt.worktree, "add", "-A")
    _git(attempt.worktree, "commit", "-q", "-m", "exports")
    commit = _git(attempt.worktree, "rev-parse", "HEAD")
    artefact = artefact_of(attempt, attempt_commit=commit)
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    refused: packet.PacketError | None = None
    try:
        built = packet.build_packet(
            tmp_path / "reviews" / "r0123456789ab",
            artefact,
            repo=attempt.worktree,
            base_commit=attempt.spec_commit,
            rubric=Rubric(role="control", text=PLACEHOLDER, sha256=_sha(PLACEHOLDER.encode())),
            library=library,
            spec=IssuedSpec(commit=attempt.spec_commit, path=SPEC, sha256=_sha(ISSUED.encode())),
        )
    except packet.PacketError as exc:
        # Kept, so that a packet refused for an export's bytes fails on the assertion below.
        refused = exc
    assert refused is None, str(refused)
    read = Path(built.read_root)
    issued = b"".join((read / part.name).read_bytes() for part in built.diff_parts)
    assert _added("m/exports/plate.step", STEP) in _lines(issued)
    assert _added("m/exports/plate.stl", STL) in _lines(issued)
    assert MARK not in issued
    # The reviewer can still open each export whole, from the commit's export.
    assert (read / packet.WORKTREE_NAME / "m" / "exports" / "plate.stl").read_bytes() == STL
    packet.check_parts(built, repo=attempt.worktree, base_commit=attempt.spec_commit)
