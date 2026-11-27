"""On macOS a sandboxed command's mktemp and diff write in the session's own temporary directory.

The shared temporary directories are denied to every command, and on macOS two ordinary programs
write there whatever ``TMPDIR`` says: a plain ``mktemp`` makes its file in the per-user directory,
and ``diff`` copies an operand that is no regular file (a process substitution, a pipe, standard
input) into ``/tmp`` (measured on macOS 27). The survivor reaper's front, which runs every
sandboxed command on macOS, puts a directory of the session's own programs first on the command's
search path; these rows hold what is there and what each does, run as written.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from physgate.oslayer import reaper_install


def _placed(base: Path) -> Path:
    target = base / "session"
    target.mkdir()
    settings = target / "settings.json"
    settings.write_text("{}\n")
    return reaper_install.place(target, sys.base_prefix, settings)


def test_the_front_puts_the_session_s_programs_first_for_a_sandboxed_command_alone(
    tmp_path: Path,
) -> None:
    directory = _placed(tmp_path)
    programs = directory / reaper_install.BIN_DIRNAME
    assert sorted(p.name for p in programs.iterdir()) == ["diff", "mktemp"]
    assert all(os.access(p, os.X_OK) for p in programs.iterdir())
    front = (directory / reaper_install.FRONT).read_text()
    hook_branch, sandboxed = front.split("fi\n", 1)
    assert "PATH" not in hook_branch
    assert f"PATH='{programs}':\"$PATH\"" in sandboxed


macos = pytest.mark.skipif(sys.platform != "darwin", reason="the system's programs measured here")


def _run(program: Path, line: str, cwd: Path, own: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/zsh", "-f", "-c", f"PATH={program.parent}:/usr/bin:/bin; {line}"],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(own)},
        capture_output=True,
        text=True,
        check=False,
    )


@macos
@pytest.mark.parametrize("line", ["mktemp", "mktemp -d", "mktemp -t note", "mktemp -q"])
def test_a_plain_mktemp_makes_its_file_in_tmpdir(tmp_path: Path, line: str) -> None:
    own = tmp_path / "own"
    own.mkdir()
    programs = _placed(tmp_path) / reaper_install.BIN_DIRNAME
    done = _run(programs / "mktemp", line, tmp_path, own)
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()).parent == own


@macos
def test_a_mktemp_given_its_template_or_directory_is_the_system_s_own(tmp_path: Path) -> None:
    own, elsewhere = tmp_path / "own", tmp_path / "elsewhere"
    own.mkdir()
    elsewhere.mkdir()
    programs = _placed(tmp_path) / reaper_install.BIN_DIRNAME
    here = _run(programs / "mktemp", "mktemp note.XXXX", tmp_path, own)
    assert Path(here.stdout.strip()).parent == Path(".") or "/" not in here.stdout.strip()
    there = _run(programs / "mktemp", f"mktemp -p {elsewhere}", tmp_path, own)
    assert Path(there.stdout.strip()).parent == elsewhere


@macos
@pytest.mark.parametrize(
    ("line", "status", "said"),
    [
        ("diff <(echo a) <(echo a)", 0, ""),
        ("diff <(echo a) <(echo b)", 1, "< a"),
        ("echo a | diff - a.txt", 0, ""),
        ("diff -u a.txt <(echo b)", 1, "+b"),
        ("diff a.txt b.txt", 1, "> b"),
    ],
)
def test_diff_of_a_pipe_is_answered_as_the_system_s_and_leaves_nothing(
    tmp_path: Path, line: str, status: int, said: str
) -> None:
    own = tmp_path / "own"
    own.mkdir()
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "b.txt").write_text("b\n")
    programs = _placed(tmp_path) / reaper_install.BIN_DIRNAME
    done = _run(programs / "diff", line, tmp_path, own)
    assert done.returncode == status, done.stderr
    assert said in done.stdout
    assert not list(own.iterdir())


def test_the_diff_stand_in_hands_the_system_s_diff_a_copy_of_a_pipe_beneath_tmpdir(
    tmp_path: Path,
) -> None:
    # The stand-in as written, the system's diff in its place a recorder of what it is given: an
    # operand that is a pipe reaches it as a copy in the session's own temporary directory.
    own = tmp_path / "own"
    own.mkdir()
    (tmp_path / "a.txt").write_text("a\n")
    seen = tmp_path / "seen.txt"
    recorder = tmp_path / "recording-diff"
    recorder.write_text(f'#!/bin/sh\nfor a in "$@"; do echo "$a" >> \'{seen}\'; done\nexit 0\n')
    recorder.chmod(0o700)
    stand_in = tmp_path / "diff"
    mktemp = reaper_install.SYSTEM_MKTEMP
    stand_in.write_text(reaper_install._DIFF_TEXT.format(diff=recorder, mktemp=mktemp))
    stand_in.chmod(0o700)
    done = subprocess.run(
        ["/bin/sh", "-c", f"echo a | '{stand_in}' - a.txt"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(own)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    given = seen.read_text().splitlines()
    assert "-" not in given and "a.txt" in given, given
    copies = [g for g in given if g != "a.txt"]
    assert copies and all(Path(g).is_relative_to(own) for g in copies), given
    assert not list(own.iterdir()), "the copy was left behind"
