"""What the design libraries write on first use lands in the session's own temporary directory.

The CAD library's dependencies keep caches and data where the XDG variables point, and fall
back to the home directory without them. The environment's session file names both variables
in the session's own temporary directory, so a session that runs a part script with nothing
set by hand writes nowhere else. The file's other entries are the tool layer's and are left as
they were.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import SESSION_FILE, read_wiring, wire

TOOLENV = Path(__file__).resolve().parents[3] / "toolenv"
FIRST_USE = ("XDG_CACHE_HOME", "XDG_DATA_HOME")


def _stand_in(tmp_path: Path) -> Path:
    """A root with what the real file's programs and links name, and the real file."""
    root = Path(os.path.realpath(tmp_path)) / "env"
    (root / "venv" / "bin").mkdir(parents=True)
    for name in ("pio", "platformio", "python3"):
        (root / "venv" / "bin" / name).write_text("#!/bin/sh\n")
        (root / "venv" / "bin" / name).chmod(0o755)
    for name in ("platforms", "packages", "lib"):
        (root / "platformio" / name).mkdir(parents=True)
    shutil.copyfile(TOOLENV / SESSION_FILE, root / SESSION_FILE)
    return root


def _recorded(root: Path) -> ToolEnvironment:
    return ToolEnvironment(
        interpreter=str(root / "venv" / "bin" / "python3"),
        resolved=str(root / "venv" / "bin" / "python3"),
        python_version="3.12.9",
        prefix=str(root / "venv"),
        distributions=(),
        native_tools=(),
        roots=(str(root),),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


def test_the_session_file_names_both_first_use_variables_in_the_session_s_temporary_directory() -> (
    None
):
    variables = json.loads((TOOLENV / SESSION_FILE).read_text(encoding="utf-8"))["variables"]
    for name in FIRST_USE:
        assert name in variables, sorted(variables)
        assert variables[name].startswith("{temp}/"), (name, variables[name])
    assert variables["XDG_CACHE_HOME"] != variables["XDG_DATA_HOME"]


def test_the_file_with_both_variables_is_one_the_tool_layer_reads(tmp_path: Path) -> None:
    wiring = read_wiring(_stand_in(tmp_path))
    assert wiring is not None
    assert set(FIRST_USE) <= set(wiring.variables)


def test_a_wired_session_s_first_use_places_are_inside_its_own_temporary_directory(
    tmp_path: Path,
) -> None:
    root = _stand_in(tmp_path)
    session = Path(os.path.realpath(tmp_path)) / "session"
    temp = session / "temp"
    temp.mkdir(parents=True)
    variables = wire(_recorded(root), bin_dir=session / "bin", temp=temp, taken=("PATH", "HOME"))
    named = [variables.get(name) for name in FIRST_USE]
    assert all(named), sorted(variables)
    places = [Path(str(place)) for place in named]
    for place in places:
        assert place.is_relative_to(temp) and place != temp, place
    # Neither is the other's, nor inside a directory a tool of the layer was given.
    assert not places[0].is_relative_to(places[1]) and not places[1].is_relative_to(places[0])
    given = {Path(v) for k, v in variables.items() if k not in FIRST_USE and v.startswith("/")}
    for place in places:
        assert not any(place.is_relative_to(other) for other in given), place
