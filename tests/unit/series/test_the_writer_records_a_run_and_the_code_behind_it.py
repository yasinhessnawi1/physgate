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
    loaded = {f.path: f.sha256 for f in record.producer.loaded}
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


def test_a_session_s_outbox_is_bounded(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    script = write_script(
        base, record_id="second", extra="series_writer.MAX_RECORDS_PER_SESSION = 1"
    )
    first = run(write_script(base, name="first.py", record_id="first"))
    assert first.returncode == 0, first.stderr
    done = run(script)
    assert done.returncode != 0
    assert "at most 1 records" in done.stderr
    assert sorted(p.name for p in (base / ".physgate" / "series").iterdir()) == ["first.json"]


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


def test_writing_a_record_again_replaces_it_whole(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    first = run(write_script(base))
    assert first.returncode == 0, first.stderr
    again = run(write_script(base, name="again.py"))
    assert again.returncode == 0, again.stderr
    outbox = base / ".physgate" / "series"
    assert sorted(p.name for p in outbox.iterdir()) == ["step_nominal.json"]
    record = parse_record((outbox / "step_nominal.json").read_bytes())
    assert record.producer.script.path == "modules/control/again.py"


def test_a_rewrite_that_fails_part_way_leaves_the_earlier_record_whole(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    first = run(write_script(base))
    assert first.returncode == 0, first.stderr
    outbox = base / ".physgate" / "series"
    before = (outbox / "step_nominal.json").read_bytes()

    failing = "def _fail(fd):\n    raise OSError('the disk went away')\nos.fsync = _fail"
    done = run(write_script(base, name="failing.py", extra=failing))
    assert done.returncode != 0
    assert "the disk went away" in done.stderr
    assert sorted(p.name for p in outbox.iterdir()) == ["step_nominal.json"]
    assert (outbox / "step_nominal.json").read_bytes() == before
