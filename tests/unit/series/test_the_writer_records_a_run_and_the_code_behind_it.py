"""The writer, run from a script the way a role session runs it, writes a record the schema admits.

What it records about the code is checked against the files themselves: the script by its
path in the module, every loaded file of the role's own code with the digest of its bytes,
and code from outside the worktree by its absolute path, so the orchestrator can refuse it.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from writer_rig import WRITER_SOURCE, run, worktree, write_script

from physgate.series.record import parse_record


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_record_written_from_a_script_is_one_the_schema_admits(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    script = write_script(base)
    done = run(script)
    assert done.returncode == 0, done.stderr
    written = Path(done.stdout.strip())
    assert written == base / ".physgate" / "series" / "step_nominal.json"
    record = parse_record(written.read_bytes())
    assert record.traces[0].values == (0.0, 0.02, 0.05)
    assert record.inputs["seed"].value == 7
    assert record.producer.script.path == "modules/control/sim.py"
    assert record.producer.script.sha256 == _sha(script)
    # A distribution's interpreter may load a file of its own from outside its prefix (Ubuntu's
    # /etc/python3.12/sitecustomize.py); the writer names it by its absolute path, and the
    # collector judges it. Every file named in the worktree is held exactly.
    loaded = {f.path: f.sha256 for f in record.producer.loaded if not f.path.startswith("/")}
    assert loaded == {
        ".physgate/lib/series_writer.py": hashlib.sha256(WRITER_SOURCE).hexdigest(),
        "modules/control/helper.py": _sha(base / "modules" / "control" / "helper.py"),
    }
    assert sorted(p.name for p in written.parent.iterdir()) == ["step_nominal.json"]


def test_the_record_is_the_same_wherever_the_script_is_run_from(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    script = write_script(base)
    first = run(script)
    assert first.returncode == 0, first.stderr
    data = Path(first.stdout.strip()).read_bytes()
    # An id is written once: the record is taken away, as the session's end collects it.
    Path(first.stdout.strip()).unlink()
    again = subprocess.run(
        [sys.executable, "-E", "-s", "sim.py"],
        cwd=script.parent,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(base / ".home")},
        check=False,
    )
    assert again.returncode == 0, again.stderr
    assert Path(again.stdout.strip()).read_bytes() == data


def test_code_loaded_from_outside_the_worktree_is_named_by_its_absolute_path(
    tmp_path: Path,
) -> None:
    base = worktree(tmp_path)
    outside = Path(os.path.realpath(tmp_path)) / "scratch"
    outside.mkdir()
    (outside / "elsewhere.py").write_text("VALUE = 1\n")
    script = write_script(base, extra=f"sys.path.insert(0, {str(outside)!r})\nimport elsewhere")
    done = run(script)
    assert done.returncode == 0, done.stderr
    record = parse_record(Path(done.stdout.strip()).read_bytes())
    paths = {f.path for f in record.producer.loaded}
    assert str(outside / "elsewhere.py") in paths


def test_a_writer_that_is_not_at_its_place_in_a_worktree_refuses(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    misplaced = base / "modules" / "control" / "series_writer.py"
    shutil.copy(base / ".physgate" / "lib" / "series_writer.py", misplaced)
    script = base / "modules" / "control" / "direct.py"
    script.write_text(
        "import series_writer\n"
        "series_writer.record('x', title='t', axis='time', x=('t', 's', [0.0]),"
        " traces=[('p', 'm', [0.0])])\n"
    )
    done = run(script)
    assert done.returncode != 0
    assert "runs from .physgate/lib" in done.stderr
    assert not (base / ".physgate" / "series").exists()


def test_a_process_with_no_script_cannot_write_a_record(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    code = (
        f"import sys; sys.path.insert(0, {str(base / '.physgate' / 'lib')!r});"
        "import series_writer;"
        "series_writer.record('x', title='t', axis='time', x=('t', 's', [0.0]),"
        " traces=[('p', 'm', [0.0])])"
    )
    done = subprocess.run(
        [sys.executable, "-E", "-s", "-c", code],
        cwd=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode != 0
    assert "from a script file" in done.stderr


def test_a_refused_record_leaves_no_file_behind(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    script = write_script(base, record_id="Bad-Id")
    done = run(script)
    assert done.returncode != 0
    assert "lower-case name" in done.stderr
    outbox = base / ".physgate" / "series"
    assert not outbox.exists() or list(outbox.iterdir()) == []


def test_the_writer_leaves_the_session_s_bounds_to_the_collector(tmp_path: Path) -> None:
    # Counting the records already there would read the outbox, which a session may not; the
    # collector holds the bounds and sets aside a record beyond them.
    base = worktree(tmp_path)
    first = run(write_script(base, name="first.py", record_id="first"))
    assert first.returncode == 0, first.stderr
    script = write_script(
        base, record_id="second", extra="series_writer.MAX_RECORDS_PER_SESSION = 1"
    )
    done = run(script)
    assert done.returncode == 0, done.stderr
    names = sorted(p.name for p in (base / ".physgate" / "series").iterdir())
    assert names == ["first.json", "second.json"]


#: Run inside a script before it records: the outbox behaves as Seatbelt makes a read-denied
#: one behave (measured on macOS with Claude Code 2.1.301). Listing it, asking about an entry
#: (even through the descriptor that made it) and opening one to read fail; renaming, linking
#: or removing anything in it, and renaming a file in over one already there, fail too;
#: creating a new file there and writing it still work. The platform reads as macOS, whose
#: writer takes a refused question about its own new entry as Seatbelt's.
_BLIND = """
import builtins, errno
class _Platform:
    platform = "darwin"
    def __getattr__(self, name):
        return getattr(sys, name)
series_writer.sys = _Platform()
_outbox = os.path.realpath(os.path.join(here, ".physgate", "series"))
_real_lstat = os.lstat
_real_open = os.open
_real_fstat = os.fstat
_made = set()
def _there(path):
    try:
        _real_lstat(path)
    except FileNotFoundError:
        return False
    return True
def _inside(path):
    path = "" if isinstance(path, int) else os.path.abspath(os.fspath(path))
    return path == _outbox or path.startswith(_outbox + os.sep)
def _refuse(path):
    raise PermissionError(errno.EPERM, "Operation not permitted", str(path))
def _deny(real, refused):
    def guarded(path, *args, **kwargs):
        if refused(path, *args, **kwargs):
            _refuse(path)
        return real(path, *args, **kwargs)
    return guarded
_entry = lambda path, *a, **k: _inside(path) and os.path.abspath(os.fspath(path)) != _outbox
for _name in ("listdir", "scandir"):
    setattr(os, _name, _deny(getattr(os, _name), lambda path, *a, **k: _inside(path)))
for _name in ("stat", "lstat", "unlink", "remove"):
    setattr(os, _name, _deny(getattr(os, _name), _entry))
_moves = lambda src, dst, *a, **k: _inside(src) or (_inside(dst) and _there(dst))
os.replace = _deny(os.replace, _moves)
os.rename = _deny(os.rename, _moves)
os.link = _deny(os.link, lambda src, dst, *a, **k: _inside(src))
def _open(path, flags, *args, **kwargs):
    if _inside(path) and not flags & os.O_WRONLY:
        _refuse(path)
    fd = _real_open(path, flags, *args, **kwargs)
    if _inside(path):
        _made.add(fd)
    return fd
os.open = _open
os.fstat = _deny(_real_fstat, lambda fd: fd in _made)
builtins.open = _deny(builtins.open, lambda p, mode="r", *a, **k: _inside(p) and "r" in mode)
"""

#: Run inside a script before it records: every file the process makes is listed on stderr,
#: so a test sees each place the writer put anything, however briefly.
_MAKES = """
_real_make = os.open
def _make(path, flags, *args, **kwargs):
    if flags & os.O_CREAT:
        sys.stderr.write("made " + os.path.abspath(os.fspath(path)) + "\\n")
    return _real_make(path, flags, *args, **kwargs)
os.open = _make
"""


def test_the_writer_writes_the_outbox_without_reading_it(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    (base / ".physgate" / "series").mkdir()
    first = run(write_script(base, extra=_BLIND))
    assert first.returncode == 0, first.stderr
    outbox = base / ".physgate" / "series"
    assert sorted(p.name for p in outbox.iterdir()) == ["step_nominal.json"]
    record = parse_record((outbox / "step_nominal.json").read_bytes())
    assert record.producer.script.path == "modules/control/sim.py"
    # Nothing is left beside the outbox either.
    assert sorted(p.name for p in (base / ".physgate").iterdir()) == ["lib", "series"]


def test_the_writer_makes_nothing_but_the_record_and_nothing_beside_the_outbox(
    tmp_path: Path,
) -> None:
    # A file made beside the outbox and moved in later could be linked or held open, before
    # the move, by a process the session left running; the record's file is made in place.
    base = worktree(tmp_path)
    done = run(write_script(base, extra=_MAKES))
    assert done.returncode == 0, done.stderr
    lines = done.stderr.splitlines()
    made = [line.removeprefix("made ") for line in lines if line.startswith("made ")]
    assert made == [str(base / ".physgate" / "series" / "step_nominal.json")]


@pytest.mark.parametrize("blind", [False, True])
def test_a_record_id_already_written_is_refused_and_the_record_left_as_it_was(
    tmp_path: Path, blind: bool
) -> None:
    # From the same command or a later one, on either platform: a name already in the outbox
    # is never written over, so the script records the run under a new id.
    base = worktree(tmp_path)
    first = run(write_script(base, extra=_BLIND if blind else ""))
    assert first.returncode == 0, first.stderr
    outbox = base / ".physgate" / "series"
    before = (outbox / "step_nominal.json").read_bytes()
    again = run(write_script(base, name="again.py", extra=_BLIND if blind else ""))
    assert again.returncode != 0
    assert "already in the outbox" in again.stderr and "under a new id" in again.stderr
    assert (outbox / "step_nominal.json").read_bytes() == before
    assert sorted(p.name for p in (base / ".physgate").iterdir()) == ["lib", "series"]


@pytest.mark.parametrize("blind", [False, True])
def test_a_file_linked_in_under_the_record_s_name_is_never_written_through(
    tmp_path: Path, blind: bool
) -> None:
    # The bait: a session links a file of its own into the outbox under the name its script
    # will record, then reads the record through its own name. The writer refuses the name.
    base = worktree(tmp_path)
    outbox = base / ".physgate" / "series"
    outbox.mkdir()
    bait = base / "modules" / "control" / "bait.txt"
    bait.write_text("BAIT")
    os.link(bait, outbox / "step_nominal.json")
    done = run(write_script(base, extra=_BLIND if blind else ""))
    assert done.returncode != 0
    assert "already in the outbox" in done.stderr
    assert bait.read_text() == "BAIT"


@pytest.mark.parametrize("bait", ["a symbolic link", "a directory", "a fifo"])
def test_no_other_kind_of_entry_under_the_record_s_name_is_written_through(
    tmp_path: Path, bait: str
) -> None:
    base = worktree(tmp_path)
    outbox = base / ".physgate" / "series"
    outbox.mkdir()
    target = base / "modules" / "control" / "target.txt"
    target.write_text("TARGET")
    entry = outbox / "step_nominal.json"
    if bait == "a symbolic link":
        entry.symlink_to(target)
    elif bait == "a directory":
        entry.mkdir()
    else:
        os.mkfifo(entry)
    done = run(write_script(base))
    assert done.returncode != 0
    assert "already in the outbox" in done.stderr
    assert target.read_text() == "TARGET"


#: Run inside a script before it records: as the record's file is made, a second name is
#: linked to it outside the outbox, as a process of the same command could on Linux, where
#: an entry made during a command is not denied to that command.
_SECOND_NAME = """
_real_make = os.open
def _make(path, flags, *args, **kwargs):
    fd = _real_make(path, flags, *args, **kwargs)
    if flags & os.O_CREAT and os.path.basename(os.fspath(path)) == "step_nominal.json":
        os.link(path, os.path.join(here, "modules", "control", "caught"))
    return fd
os.open = _make
"""


def test_a_record_s_file_with_a_second_name_is_left_empty(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    done = run(write_script(base, extra=_SECOND_NAME))
    assert done.returncode != 0
    assert "has 2 names" in done.stderr and "nothing was written" in done.stderr
    # Nothing reached the second name; the empty record is refused when the session ends.
    assert (base / "modules" / "control" / "caught").read_bytes() == b""
    assert (base / ".physgate" / "series" / "step_nominal.json").read_bytes() == b""


def test_a_refused_question_about_its_own_entry_is_taken_as_seatbelt_s_only_on_macos(
    tmp_path: Path,
) -> None:
    # Elsewhere a writer that cannot ask how many names its new file has does not write it.
    base = worktree(tmp_path)
    linux = _BLIND.replace('platform = "darwin"', 'platform = "linux"')
    done = run(write_script(base, extra=linux))
    assert done.returncode != 0
    assert "Operation not permitted" in done.stderr
    assert (base / ".physgate" / "series" / "step_nominal.json").read_bytes() == b""


def test_a_writer_that_reads_the_outbox_fails_where_it_is_unreadable(tmp_path: Path) -> None:
    # The stand-in for the OS layer bites: a script that lists the outbox is refused by it.
    base = worktree(tmp_path)
    (base / ".physgate" / "series").mkdir()
    looks = _BLIND + "os.listdir(os.path.join(here, '.physgate', 'series'))\n"
    done = run(write_script(base, extra=looks))
    assert done.returncode != 0
    assert "Operation not permitted" in done.stderr


SYSTEM_PYTHON = "/usr/bin/python3"


def _system_python_version() -> tuple[int, int] | None:
    if not os.path.exists(SYSTEM_PYTHON):
        return None
    done = subprocess.run(
        [SYSTEM_PYTHON, "-I", "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    major, minor = done.stdout.split()
    return int(major), int(minor)


def test_the_writer_runs_on_the_oldest_interpreter_a_session_may_find(tmp_path: Path) -> None:
    version = _system_python_version()
    if version is None or version >= (3, 12):
        pytest.skip(
            f"this run did not reach an interpreter older than 3.12 ({SYSTEM_PYTHON}: {version}); "
            "the syntax fence still holds the file to 3.9"
        )
    base = worktree(tmp_path)
    done = run(write_script(base), interpreter=SYSTEM_PYTHON)
    assert done.returncode == 0, done.stderr
    record = parse_record(Path(done.stdout.strip()).read_bytes())
    assert record.producer.script.path == "modules/control/sim.py"
    assert {f.path for f in record.producer.loaded} == {
        ".physgate/lib/series_writer.py",
        "modules/control/helper.py",
    }


def test_a_record_cut_short_is_left_where_the_collector_refuses_it(tmp_path: Path) -> None:
    # Not whole-or-nothing: the record's file is made before it is written, and a write that
    # fails part way leaves it short. The collector refuses it when the session ends.
    base = worktree(tmp_path)
    failing = "def _fail(fd):\n    raise OSError('the disk went away')\nos.fsync = _fail"
    done = run(write_script(base, extra=failing))
    assert done.returncode != 0
    assert "the disk went away" in done.stderr
    outbox = base / ".physgate" / "series"
    assert sorted(p.name for p in outbox.iterdir()) == ["step_nominal.json"]


#: Run inside a script before it records: the interpreter's standard library is taken to be
#: ``stdlib``, and a ``sitecustomize`` module is taken to have been loaded from ``hook``, as a
#: distribution's interpreter loads its own site hook in every process.
_SITE_HOOK = """
import sysconfig, types
_real_paths = sysconfig.get_paths
def _paths(*args, **kwargs):
    paths = dict(_real_paths(*args, **kwargs))
    paths["stdlib"] = {stdlib!r}
    return paths
sysconfig.get_paths = _paths
_hook = types.ModuleType("sitecustomize")
_hook.__file__ = {hook!r}
sys.modules["sitecustomize"] = _hook
"""


def _site_hook_record(tmp_path: Path, hook_dir: Path) -> set[str]:
    """What a record names when ``sitecustomize`` was loaded from ``hook_dir``.

    The hook's file there links to one under a stand-in ``/etc``, outside every place the
    interpreter is installed, as Debian and Ubuntu link ``<stdlib>/sitecustomize.py`` to
    ``/etc/python3.X/sitecustomize.py``.
    """
    base = worktree(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    target = root / "etc" / "python3.12" / "sitecustomize.py"
    target.parent.mkdir(parents=True)
    target.write_text("# a distribution's own site hook\n")
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "sitecustomize.py").symlink_to(target)
    stdlib = root / "installation" / "lib" / "python3.12"
    stdlib.mkdir(parents=True, exist_ok=True)
    extra = _SITE_HOOK.format(stdlib=str(stdlib), hook=str(hook_dir / "sitecustomize.py"))
    done = run(write_script(base, extra=extra))
    assert done.returncode == 0, done.stderr
    return {f.path for f in parse_record(Path(done.stdout.strip()).read_bytes()).producer.loaded}


def test_the_interpreter_s_own_site_hook_is_not_named_as_loaded_code(tmp_path: Path) -> None:
    # Ubuntu's interpreter runs /etc/python3.12/sitecustomize.py in every process, by a link
    # in its standard library. Named, it read to a role as code from outside the module, and
    # the role worked round it by turning the site machinery off.
    root = Path(os.path.realpath(tmp_path))
    paths = _site_hook_record(tmp_path, root / "installation" / "lib" / "python3.12")
    assert not any(p.endswith("sitecustomize.py") for p in paths), paths
    assert paths == {".physgate/lib/series_writer.py", "modules/control/helper.py"}


def test_a_site_hook_from_anywhere_but_the_standard_library_is_named(tmp_path: Path) -> None:
    # The same hook found elsewhere on the path (a home the session writes, a scratch
    # directory) is code the session could have planted, and the collector judges it.
    root = Path(os.path.realpath(tmp_path))
    paths = _site_hook_record(tmp_path, root / "home" / "site-packages")
    assert str(root / "etc" / "python3.12" / "sitecustomize.py") in paths
