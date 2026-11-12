"""A session is wired to its tools from a file the environment itself carries.

Which programs a session finds by name, which directories and links it needs in its temporary
directory and which variables its tools read are facts of the tools, so they are data in the
environment (``session.json`` at a root, under the environment's digest like every other file),
never names in the harness. The harness reads the file as data, bounded, and applies only what
it can hold to the environment's own roots and the session's own temporary directory: a program
or a link target outside the root, a name that climbs out of the temporary directory, a variable
the harness sets itself or one a loader reads, and anything the file's shape does not name are
refused. Wiring a session writes nothing into the environment.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import scan
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import MAX_SESSION_FILE_BYTES, SESSION_FILE, wire

WIRING: dict[str, Any] = {
    "programs": {"build": "bin/build"},
    "directories": ["core", "cache"],
    "links": {"core/packages": "store/packages"},
    "variables": {
        "BUILD_CORE_DIR": "{temp}/core",
        "BUILD_STORE": "{root}/store",
        "BUILD_QUIET": "yes",
    },
}


def _environment(tmp_path: Path, wiring: object = None, name: str = "env") -> Path:
    root = Path(os.path.realpath(tmp_path)) / "tools" / name
    (root / "bin").mkdir(parents=True)
    (root / "store" / "packages").mkdir(parents=True)
    for program in ("python3", "build"):
        (root / "bin" / program).write_text("#!/bin/sh\n")
        (root / "bin" / program).chmod(0o755)
    (root / "store" / "packages" / "gcc.txt").write_text("7.3.0\n")
    (root / "notes.txt").write_text("not a program\n")
    if wiring is not None:
        text = wiring if isinstance(wiring, str) else json.dumps(wiring)
        (root / SESSION_FILE).write_text(text)
    return root


def _recorded(*roots: Path) -> ToolEnvironment:
    return ToolEnvironment(
        interpreter=str(roots[0] / "bin" / "python3"),
        resolved=str(roots[0] / "bin" / "python3"),
        python_version="3.12.9",
        prefix=str(roots[0]),
        distributions=(),
        native_tools=(),
        roots=tuple(str(root) for root in roots),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


def _wire(tmp_path: Path, *roots: Path, taken: tuple[str, ...] = ("PATH",)) -> dict[str, str]:
    session = tmp_path / "session"
    (session / "temp").mkdir(parents=True, exist_ok=True)
    return wire(_recorded(*roots), bin_dir=session / "bin", temp=session / "temp", taken=taken)


def test_an_environment_with_no_file_gives_the_session_its_interpreter_and_nothing_else(
    tmp_path: Path,
) -> None:
    root = _environment(tmp_path)
    assert _wire(tmp_path, root) == {}
    bin_dir = tmp_path / "session" / "bin"
    assert [p.name for p in bin_dir.iterdir()] == ["python3"]
    assert _starts(bin_dir / "python3") == root / "bin" / "python3"
    assert list((tmp_path / "session" / "temp").iterdir()) == []


def test_the_file_s_programs_directories_links_and_variables_are_applied(tmp_path: Path) -> None:
    root = _environment(tmp_path, WIRING)
    temp = tmp_path / "session" / "temp"
    variables = _wire(tmp_path, root)
    assert variables == {
        "BUILD_CORE_DIR": f"{temp}/core",
        "BUILD_STORE": f"{root}/store",
        "BUILD_QUIET": "yes",
    }
    bin_dir = tmp_path / "session" / "bin"
    assert sorted(p.name for p in bin_dir.iterdir()) == ["build", "python3"]
    assert (bin_dir / "build").readlink() == root / "bin" / "build"
    assert (temp / "core").is_dir() and (temp / "cache").is_dir()
    assert (temp / "core" / "packages").readlink() == root / "store" / "packages"
    assert (temp / "core" / "packages" / "gcc.txt").read_text() == "7.3.0\n"


def test_wiring_a_session_writes_nothing_into_the_environment(tmp_path: Path) -> None:
    root = _environment(tmp_path, WIRING)
    before = scan([root])
    _wire(tmp_path, root)
    _wire(tmp_path, root)
    assert scan([root]) == before


def test_a_session_s_directory_of_programs_is_made_afresh(tmp_path: Path) -> None:
    root = _environment(tmp_path, WIRING)
    bin_dir = tmp_path / "session" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "left-over").write_text("#!/bin/sh\n")
    (bin_dir / "python3").symlink_to("/usr/bin/false")
    _wire(tmp_path, root)
    assert sorted(p.name for p in bin_dir.iterdir()) == ["build", "python3"]
    assert _starts(bin_dir / "python3") == root / "bin" / "python3"


def test_each_root_s_file_is_applied_with_its_own_root(tmp_path: Path) -> None:
    first = _environment(tmp_path, WIRING)
    second = _environment(
        tmp_path,
        {"programs": {"check": "bin/build"}, "variables": {"CHECK_HOME": "{root}"}},
        name="more",
    )
    variables = _wire(tmp_path, first, second)
    assert variables["CHECK_HOME"] == str(second) and variables["BUILD_STORE"] == f"{first}/store"
    assert (tmp_path / "session" / "bin" / "check").readlink() == second / "bin" / "build"


def _starts(launcher: Path) -> Path:
    """The interpreter ``launcher`` starts: a program of its own, never a link."""
    assert launcher.is_file() and not launcher.is_symlink() and os.access(launcher, os.X_OK)
    first, second = launcher.read_text().splitlines()
    assert first == "#!/bin/sh" and second.startswith("exec ") and second.endswith(' "$@"')
    return Path(shlex.split(second)[1])


def test_the_interpreter_is_started_by_its_own_path_and_given_every_argument(
    tmp_path: Path,
) -> None:
    # An interpreter of a virtual environment started through a link elsewhere finds none of
    # the environment's libraries, so the session's python3 starts it by its own path.
    root = _environment(tmp_path, name="an env's")
    (root / "bin" / "python3").write_text(
        '#!/bin/sh\necho "$0"; for a in "$@"; do echo "$a"; done\n'
    )
    _wire(tmp_path, root)
    done = subprocess.run(
        [str(tmp_path / "session" / "bin" / "python3"), "-c", "print('a b')", "x y"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.splitlines() == [str(root / "bin" / "python3"), "-c", "print('a b')", "x y"]


def _changed(**changes: object) -> dict[str, Any]:
    return {**WIRING, **changes}


REFUSED = {
    "the interpreter's own name": _changed(programs={"python3": "bin/build"}),
    "a program name with a slash": _changed(programs={"../build": "bin/build"}),
    "a program path that climbs out": _changed(programs={"build": "bin/../../env/bin/build"}),
    "an absolute program path": _changed(programs={"build": "/bin/sh"}),
    "a program that is not there": _changed(programs={"build": "bin/absent"}),
    "a program that is not executable": _changed(programs={"build": "notes.txt"}),
    "a program that is a directory": _changed(programs={"build": "store"}),
    "a directory that climbs out": _changed(directories=["../outside"]),
    "an absolute directory": _changed(directories=["/var/tmp/elsewhere"]),
    "a link name that climbs out": _changed(links={"../packages": "store/packages"}),
    "a link beneath a directory not made": _changed(links={"absent/packages": "store/packages"}),
    "a link target that climbs out": _changed(links={"core/packages": "store/../../.."}),
    "an absolute link target": _changed(links={"core/packages": "/etc"}),
    "a link target that is not there": _changed(links={"core/packages": "store/absent"}),
    "a link over a directory made": _changed(links={"core": "store/packages"}),
    "a link over a directory made beneath another": _changed(
        directories=["core", "core/held"], links={"core/held": "store/packages"}
    ),
    "the search path": _changed(variables={"PATH": "{root}/bin"}),
    "a variable the session already holds": _changed(variables={"BUILD_HELD": "x"}),
    "a variable the harness sets": _changed(variables={"ANTHROPIC_BASE_URL": "http://x"}),
    "a loader's variable": _changed(variables={"LD_PRELOAD": "{root}/x.so"}),
    "the other loader's variable": _changed(variables={"DYLD_INSERT_LIBRARIES": "{root}/x"}),
    "the interpreter's own path": _changed(variables={"PYTHONPATH": "{temp}"}),
    "the interpreter's home": _changed(variables={"PYTHONHOME": "{temp}"}),
    "a start-up script": _changed(variables={"PYTHONSTARTUP": "{temp}/s.py"}),
    "a shell's start-up file": _changed(variables={"BASH_ENV": "{temp}/rc"}),
    "another program's options": _changed(variables={"NODE_OPTIONS": "--require {temp}/x.js"}),
    "the home": _changed(variables={"HOME": "{temp}"}),
    "the temporary directory": _changed(variables={"TMPDIR": "{temp}"}),
    "a lower-case name": _changed(variables={"build_quiet": "yes"}),
    "a placeholder it does not know": _changed(variables={"BUILD_HOME": "{home}/x"}),
    "an unclosed brace": _changed(variables={"BUILD_HOME": "{temp"}),
    "a control character": _changed(variables={"BUILD_QUIET": "yes\nPATH=/x"}),
    "a value that is not text": _changed(variables={"BUILD_QUIET": 1}),
    "a key the file's shape does not name": _changed(commands=["rm -rf /"]),
    "a list for the programs": _changed(programs=["build"]),
    "not an object": ["programs"],
    "not JSON": "{programs",
}


@pytest.mark.parametrize("why", list(REFUSED))
def test_what_the_harness_cannot_hold_to_the_environment_is_refused(
    tmp_path: Path, why: str
) -> None:
    root = _environment(tmp_path, REFUSED[why])
    raised: BaseException | None = None
    try:
        _wire(tmp_path, root, taken=("PATH", "ANTHROPIC_BASE_URL", "BUILD_HELD"))
    except Exception as exc:  # noqa: BLE001 - a refusal must be the domain error, never another
        raised = exc
    assert isinstance(raised, ToolEnvironmentError), (why, raised)
    assert "session file is refused" in str(raised)
    # A refusal leaves the session nothing half-wired to run with.
    assert not (tmp_path / "session" / "bin").exists()
    assert list((tmp_path / "session" / "temp").iterdir()) == []


def test_a_program_that_is_a_link_leading_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = _environment(tmp_path, WIRING)
    (root / "bin" / "build").unlink()
    (root / "bin" / "build").symlink_to("/bin/sh")
    with pytest.raises(ToolEnvironmentError, match="session"):
        _wire(tmp_path, root)


def test_a_link_whose_target_leads_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = _environment(tmp_path, _changed(links={"core/packages": "store/elsewhere"}))
    (root / "store" / "elsewhere").symlink_to("/etc")
    with pytest.raises(ToolEnvironmentError, match="session"):
        _wire(tmp_path, root)
    assert not (tmp_path / "session" / "bin").exists()


def test_a_file_that_is_a_link_is_refused(tmp_path: Path) -> None:
    root = _environment(tmp_path)
    (root / "real.json").write_text(json.dumps(WIRING))
    (root / SESSION_FILE).symlink_to(root / "real.json")
    with pytest.raises(ToolEnvironmentError, match="session"):
        _wire(tmp_path, root)


def test_a_file_too_large_to_be_one_is_refused_unparsed(tmp_path: Path) -> None:
    # Ten megabytes of valid JSON: refused by its size, before any of it is parsed.
    padded = json.dumps({**WIRING, "variables": {"BUILD_QUIET": "y" * (10 << 20)}})
    assert len(padded) > MAX_SESSION_FILE_BYTES
    root = _environment(tmp_path, padded)
    with pytest.raises(ToolEnvironmentError, match="too large"):
        _wire(tmp_path, root)


def test_bytes_that_are_not_text_are_refused(tmp_path: Path) -> None:
    root = _environment(tmp_path)
    (root / SESSION_FILE).write_bytes(b'{"programs": {"b\xff": "bin/build"}}')
    with pytest.raises(ToolEnvironmentError, match="session"):
        _wire(tmp_path, root)


def test_a_file_nested_past_the_parser_s_depth_is_refused(tmp_path: Path) -> None:
    root = _environment(tmp_path, "[" * 100_000)
    with pytest.raises(ToolEnvironmentError, match="session"):
        _wire(tmp_path, root)


def test_two_roots_that_name_the_same_program_or_variable_are_refused(tmp_path: Path) -> None:
    first = _environment(tmp_path, WIRING)
    clashes = ({"programs": {"build": "bin/build"}}, {"variables": {"BUILD_QUIET": "no"}})
    for index, clash in enumerate(clashes):
        second = _environment(tmp_path / str(index), clash, name="more")
        with pytest.raises(ToolEnvironmentError, match="session"):
            _wire(tmp_path, first, second)
