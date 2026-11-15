"""Every program the run's tool environment installs is one the hardware rule has classed.

The rule names the programs that only ever reach a board, and holds the ones that both build
and reach one to their build-only uses; a program it names in neither is not judged at all. For
the world that list cannot be complete. For the environment the harness provisions it can be
checked: every program in its ``venv/bin`` is in one of the rule's two sets, or in the list
below of programs that reach no board, so a program a new lock adds fails this row until a
person classes it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.hooks.hardware import FLASHERS, GUARDED
from physgate.hooks.shell import command_key

pytestmark = pytest.mark.integration

#: The environment's programs that reach no board: the interpreter and the scripts that
#: activate it, the package installer, the libraries' own tools (encodings, arrays, fonts,
#: tables, an ELF reader, a listing of the serial ports that opens none), and the web servers
#: of the build tool's home screen.
REACHES_NO_BOARD = frozenset(
    {
        "python", "python3", "python3.12",
        "activate", "activate.bat", "activate.csh", "activate.fish", "activate.nu",
        "activate.ps1", "activate_this.py", "deactivate.bat", "pydoc.bat",
        "pip", "pip3", "pip3.12",
        "chardetect", "normalizer", "f2py", "numpy-config",
        "fonttools", "pyftmerge", "pyftsubset", "ttx", "tabulate", "readelf.py",
        "pyserial-ports", "bottle.py", "uvicorn", "websockets",
    }
)  # fmt: skip


def _programs() -> list[str]:
    named = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT")
    if not named:
        pytest.skip("no provisioned tool environment named (PHYSGATE_TOOL_ENVIRONMENT)")
    return sorted(entry.name for entry in (Path(named) / "venv" / "bin").iterdir())


def test_every_program_in_the_environment_is_classed() -> None:
    programs = _programs()
    judged = FLASHERS | frozenset(GUARDED)
    unclassed = [name for name in programs if command_key(name) not in judged | REACHES_NO_BOARD]
    assert programs, "the environment's venv/bin holds nothing"
    assert not unclassed, f"classed by no list: {unclassed}; every program there: {programs}"


def test_the_environment_s_debugger_and_serial_terminal_are_refused_as_flashers() -> None:
    programs = _programs()
    for name in ("piodebuggdb", "pyserial-miniterm"):
        assert name in programs, f"{name} is not in the environment: {programs}"
        assert name in FLASHERS
    assert not REACHES_NO_BOARD & (FLASHERS | frozenset(GUARDED))
