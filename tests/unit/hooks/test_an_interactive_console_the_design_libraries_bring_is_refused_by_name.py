"""An interactive console the design libraries bring is refused by name, in every use.

The CAD library's dependencies put three interpreters in the environment's ``venv/bin``:
``ipython``, ``ipython3`` and ``isympy``; on macOS the simulation library adds a fourth,
``mjpython``, its trampoline that runs CPython off the main thread for its viewer. The hardware
rule reads what ``python`` runs as a module or a script; it does not read these. Listed as
reaching no board they would let ``ipython -m <flasher module>`` through, so they are guarded with
no allowed form: every use is refused, bare included, in every profile. The two other programs
those libraries bring, the DXF tool and the highlighter, reach no board, and their ordinary uses
pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import hardware
from physgate.hooks.config import HookInput

H = hardware

CONSOLES = ("ipython", "ipython3", "isympy", "mjpython")
PROFILES = ("role", "baseline", "orchestrator", "reviewer")
SERVER_TOOL = "mcp__platformio__build_project"

#: Each refused command, with the program the refusal must name.
REFUSED = [
    ("ipython", "ipython"),
    ("ipython3", "ipython3"),
    ("isympy", "isympy"),
    ("ipython -m platformio run -t upload", "ipython"),
    ("ipython3 -m serial.tools.miniterm", "ipython3"),
    ("ipython -c 'import os'", "ipython"),
    ("ipython --version", "ipython"),
    ("isympy -q", "isympy"),
    ("ipython script.py", "ipython"),
    ("/opt/env/venv/bin/ipython", "ipython"),
    ("IPython", "ipython"),
    ("timeout 5 ipython", "ipython"),
    ("echo 'import os' | ipython", "ipython"),
    ("sh -c 'isympy'", "isympy"),
    ("python3 -m IPython", "ipython"),
    ("python3 -m isympy", "isympy"),
    ("mjpython", "mjpython"),
    ("mjpython -m platformio run -t upload", "mjpython"),
    ("mjpython -m serial.tools.miniterm", "mjpython"),
    ("mjpython script.py", "mjpython"),
    ("/opt/env/venv/bin/mjpython -c 'import os'", "mjpython"),
    ("'/opt/env/mujoco/MuJoCo_(mjpython).app/Contents/MacOS/mjpython' script.py", "mjpython"),
]
#: The DXF tool and the highlighter, as a session would use them, and text naming a console.
PASSING = [
    "ezdxf info modules/chassis/exports/plate.dxf",
    "ezdxf audit modules/chassis/exports/plate.dxf",
    "ezdxf --version",
    "pygmentize -l python -f html -o out.html script.py",
    "pygmentize -L lexers",
    "echo ipython",
    "grep -r ipython notes.md",
    "python3 -c 'import build123d'",
]


def _no_form(program: str) -> str:
    # Reached through getattr so a row fails on its assertion, not on a missing name.
    text = getattr(H, "NO_FORM", "<the rule has no reason for a program with no allowed form>")
    return text.format(program=program)


def _decided(tmp: Path, tool: str, tool_input: dict[str, Any], profile: str = "role") -> str:
    config = write_config(tmp, profile=profile)[2]
    if tool == "Bash":
        hook_input = HookInput.model_validate(bash(tool_input["command"], cwd=config.worktree))
    else:
        hook_input = HookInput.model_validate(
            event(tool_name=tool, cwd=config.worktree, tool_input=tool_input)
        )
    decision = H.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize(("command", "program"), REFUSED, ids=[c for c, _ in REFUSED])
def test_a_console_is_refused_in_every_use_with_a_reason_that_names_it(
    tmp_path: Path, command: str, program: str
) -> None:
    assert _decided(tmp_path, "Bash", {"command": command}) == _no_form(program)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("console", CONSOLES)
def test_each_console_is_refused_by_name_in_every_profile(
    tmp_path: Path, console: str, profile: str
) -> None:
    assert _decided(tmp_path, "Bash", {"command": console}, profile) == _no_form(console)


@pytest.mark.parametrize("console", CONSOLES)
def test_a_server_tool_asked_to_run_a_console_is_refused(tmp_path: Path, console: str) -> None:
    assert _decided(tmp_path, SERVER_TOOL, {"argv": [console]}) == _no_form(console)
    assert _decided(tmp_path, SERVER_TOOL, {"command": f"{console} -m platformio"}) == _no_form(
        console
    )


def test_the_consoles_are_guarded_with_no_allowed_form_and_the_other_two_are_not_judged() -> None:
    for console in CONSOLES:
        assert console in H.GUARDED, f"{console} is not guarded"
        before, uses = H.GUARDED[console]
        assert not before, f"{console} has options of its own allowed: {before}"
        assert not uses, f"{console} has uses allowed: {uses}"
        assert not H.build_only(console, []), f"{console} alone is taken for a build-only use"
    for tool in ("ezdxf", "pygmentize"):
        assert tool not in H.GUARDED
        assert tool not in H.FLASHERS


@pytest.mark.parametrize("command", PASSING, ids=PASSING)
def test_the_dxf_tool_the_highlighter_and_text_naming_a_console_pass(
    tmp_path: Path, command: str
) -> None:
    assert _decided(tmp_path, "Bash", {"command": command}) == "allow"


def test_a_guarded_build_tool_alone_still_passes(tmp_path: Path) -> None:
    # The bare form of a guarded program with build-only uses is unchanged: it does nothing.
    assert _decided(tmp_path, "Bash", {"command": "pio"}) == "allow"
    assert _decided(tmp_path, "Bash", {"command": "pio --version"}) == "allow"
