"""A session finds KiCad, its libraries and a configuration of its own from the KiCad root's file.

How a session is wired to KiCad is a fact of the tool, so it is data in the KiCad root, written
by provisioning beside the copied release (``session.json``, the tool layer's one file per root),
and no name of the tool enters the harness. Read here: the file names ``kicad-cli`` at the place
provisioning put it on each machine; KiCad's configuration in the session's own temporary
directory (``KICAD_CONFIG_HOME``), with the release's own library tables linked into it, so a
fresh session reads the pinned symbol and footprint libraries and writes no setting anywhere
else; the libraries' variables at the release's own folders; and that the tool layer wires a
session to it beside the environment's own file with no name named twice.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import SESSION_FILE, read_wiring, wire

REPO = Path(__file__).resolve().parents[3]
TOOLENV = REPO / "toolenv"
#: Where the release keeps its libraries, inside the KiCad root, on each machine.
SHARE = {
    "Linux": "app/share/kicad",
    "Darwin": "app/KiCad.app/Contents/SharedSupport",
}
PROGRAM = {
    "Linux": "app/bin/kicad-cli",
    "Darwin": "app/KiCad.app/Contents/MacOS/kicad-cli",
}
TABLES = ("sym-lib-table", "fp-lib-table")


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("toolenv_provision", TOOLENV / "provision.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _named(name: str) -> Callable[..., object]:
    found = getattr(_provision(), name, None)
    assert callable(found), f"provisioning has no {name}"
    return found  # type: ignore[no-any-return]


def _session(system: str) -> dict[str, object]:
    found = _named("kicad_session")(system)
    assert isinstance(found, dict)
    return found


def _kicad_root(tmp_path: Path, system: str = "Linux") -> Path:
    """A KiCad root with what the file names: the program, the libraries, the two tables."""
    root = Path(os.path.realpath(tmp_path)) / "kicad"
    program = root / PROGRAM[system]
    program.parent.mkdir(parents=True)
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    share = root / SHARE[system]
    for name in ("symbols/Device.kicad_symdir", "footprints/Resistor_SMD.pretty", "template"):
        (share / name).mkdir(parents=True)
    for table in TABLES:
        (share / "template" / table).write_text(f"({table.replace('-', '_')})\n")
    _named("write_kicad_session")(root, system)
    return root


def _environment_root(tmp_path: Path) -> Path:
    """The environment's other root with its own real file, as the tool layer's test makes it."""
    root = Path(os.path.realpath(tmp_path)) / "env"
    (root / "venv" / "bin").mkdir(parents=True)
    for name in ("pio", "platformio", "python3"):
        (root / "venv" / "bin" / name).write_text("#!/bin/sh\n")
        (root / "venv" / "bin" / name).chmod(0o755)
    for name in ("platforms", "packages", "lib"):
        (root / "platformio" / name).mkdir(parents=True)
    shutil.copyfile(TOOLENV / SESSION_FILE, root / SESSION_FILE)
    return root


def _recorded(*roots: Path) -> ToolEnvironment:
    python = roots[0] / "venv" / "bin" / "python3"
    return ToolEnvironment(
        interpreter=str(python),
        resolved=str(python),
        python_version="3.12.9",
        prefix=str(roots[0] / "venv"),
        distributions=(),
        native_tools=(),
        roots=tuple(str(root) for root in roots),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


def test_the_file_names_the_program_where_provisioning_puts_it_on_each_machine() -> None:
    place = _named("kicad_cli")
    for system in ("Linux", "Darwin"):
        programs = _session(system)["programs"]
        assert programs == {"kicad-cli": PROGRAM[system]}, system
        assert str(place(Path("/r"), system)) == f"/r/{PROGRAM[system]}"


def test_kicad_s_configuration_is_the_session_s_own_with_the_release_s_tables_linked_in() -> None:
    for system in ("Linux", "Darwin"):
        session = _session(system)
        variables = session["variables"]
        assert isinstance(variables, dict)
        assert variables["KICAD_CONFIG_HOME"] == "{temp}/kicad-config", system
        assert session["directories"] == ["kicad-config", "kicad-config/10.0"], system
        assert session["links"] == {
            f"kicad-config/10.0/{table}": f"{SHARE[system]}/template/{table}" for table in TABLES
        }, system


def test_the_libraries_variables_name_the_release_s_own_folders() -> None:
    for system in ("Linux", "Darwin"):
        variables = _session(system)["variables"]
        assert isinstance(variables, dict)
        share = "{root}/" + SHARE[system]
        assert variables["KICAD10_SYMBOL_DIR"] == f"{share}/symbols", system
        assert variables["KICAD10_FOOTPRINT_DIR"] == f"{share}/footprints", system
        assert variables["KICAD10_TEMPLATE_DIR"] == f"{share}/template", system
        # Nothing the environment's own file names, so the two roots never name one thing twice.
        environment = json.loads((TOOLENV / SESSION_FILE).read_text(encoding="utf-8"))
        assert not set(variables) & set(environment["variables"]), system


def test_provisioning_writes_the_file_into_the_root_and_the_tool_layer_reads_it(
    tmp_path: Path,
) -> None:
    root = _kicad_root(tmp_path)
    written = json.loads((root / SESSION_FILE).read_text(encoding="utf-8"))
    assert written == _session("Linux")
    wiring = read_wiring(root)
    assert wiring is not None
    assert wiring.programs == {"kicad-cli": PROGRAM["Linux"]}


def test_a_session_is_wired_to_kicad_beside_the_environment_with_its_config_in_its_own_temp(
    tmp_path: Path,
) -> None:
    kicad = _kicad_root(tmp_path / "k")
    env = _environment_root(tmp_path / "e")
    session = Path(os.path.realpath(tmp_path)) / "session"
    temp = session / "temp"
    temp.mkdir(parents=True)
    variables = wire(_recorded(env, kicad), bin_dir=session / "bin", temp=temp, taken=("PATH",))
    assert (session / "bin" / "kicad-cli").resolve() == (kicad / PROGRAM["Linux"]).resolve()
    assert variables["KICAD_CONFIG_HOME"] == str(temp / "kicad-config")
    assert variables["KICAD10_SYMBOL_DIR"] == str(kicad / SHARE["Linux"] / "symbols")
    for table in TABLES:
        link = temp / "kicad-config" / "10.0" / table
        assert link.is_symlink(), table
        assert link.resolve() == (kicad / SHARE["Linux"] / "template" / table).resolve()
    # The environment's own entries are still there: one session, both roots.
    assert "XDG_CACHE_HOME" in variables
    assert (session / "bin" / "pio").is_symlink()
