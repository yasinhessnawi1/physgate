"""The reaper runs a command in a shell that reads no user's startup file.

The reaper is the harness's own wrapper around every sandboxed command, and it starts the
command's shell itself. Where it controls how, the shell is told to read no startup file:
``-f`` for zsh, ``--noprofile --norc`` for bash; plain sh reads none for a command string and
takes no such option. Held on both ways it starts the shell: the hand-over when it is not
sandboxed, and the child it waits for when it is.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from physgate.oslayer import reaper
from physgate.oslayer.reaper import SHELL, Info, Reaper

EXPECTED = {
    "zsh": ["-f", "-c", "true"],
    "bash": ["--noprofile", "--norc", "-c", "true"],
    "sh": ["-c", "true"],
}


class _Unsandboxed:
    def sandboxed(self, pid: int) -> bool:
        return False

    def pids(self) -> list[int]:
        return []

    def info(self, pid: int) -> Info | None:
        return None

    def kill(self, pid: int, sig: int) -> None:
        raise AssertionError("nothing is signalled")


def test_the_hand_over_starts_the_shell_with_no_startup_file() -> None:
    ran: list[tuple[str, list[str]]] = []
    reaper.run(
        ["reaper", "true"],
        kernel=_Unsandboxed(),
        environ={},
        execv=lambda path, argv: ran.append((path, argv)),
    )
    ((path, argv),) = ran
    assert path == argv[0] == SHELL
    assert argv[1:] == EXPECTED[os.path.basename(SHELL)]


@pytest.mark.parametrize(
    ("shell", "name"),
    [("/bin/zsh", "zsh"), ("/bin/bash", "bash"), ("/usr/bin/bash", "bash"), ("/bin/sh", "sh")],
)
def test_each_shell_is_told_in_its_own_words_to_read_no_startup_file(shell: str, name: str) -> None:
    assert reaper.shell_argv("true", shell) == [shell, *EXPECTED[name]]


def test_the_child_it_waits_for_is_started_with_no_startup_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[str]] = []

    class _Child:
        def __init__(self, argv: list[str], **_: Any) -> None:  # noqa: ANN401
            started.append(argv)

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", _Child)
    monkeypatch.setattr(reaper, "_say", lambda _line: None)
    unarmed = Reaper(_Unsandboxed(), 500, 400, 0)
    assert reaper._run_and_reap("true", unarmed, "not proven", [], [False]) == 0
    (argv,) = started
    assert argv[0] == SHELL
    assert argv[1:] == EXPECTED[os.path.basename(SHELL)]


@pytest.mark.skipif(sys.platform != "darwin", reason="the reaper is installed on macOS only")
def test_the_shell_it_starts_runs_no_zshenv_from_the_home_or_from_zdotdir(tmp_path: Path) -> None:
    ran: list[tuple[str, list[str]]] = []
    command = "echo command-ran"
    reaper.run(
        ["reaper", command],
        kernel=_Unsandboxed(),
        environ={},
        execv=lambda path, argv: ran.append((path, argv)),
    )
    ((_, argv),) = ran
    home, zdotdir = tmp_path / "home", tmp_path / "zdotdir"
    for place in (home, zdotdir):
        place.mkdir()
        (place / ".zshenv").write_text(f"echo startup-ran-from-{place.name}\n")
    for env in ({"HOME": str(home)}, {"HOME": str(home), "ZDOTDIR": str(zdotdir)}):
        done = subprocess.run(  # noqa: S603
            argv, env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True, check=True
        )
        assert done.stdout == "command-ran\n", env
