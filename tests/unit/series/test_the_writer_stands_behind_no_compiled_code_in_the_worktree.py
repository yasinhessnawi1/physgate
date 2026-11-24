"""The series writer stands behind no compiled code in the worktree.

The interpreter runs a module's compiled file in place of its source whenever the file's header
names the source's time and size, and it reads such a file even where it is told to write none.
A record names the source's bytes as the code that ran, so a compiled file beside a source the
session controls would let other code stand behind a curve, and the cleanup at the session's end
would then remove the proof. So the writer refuses to write a record while any module loaded
from the worktree has a compiled file where the interpreter would read one for it, or was loaded
by any loader but the source loader. The check is the writer's, at the moment it writes: a
record written and sealed before is read and collected exactly as it was.
"""

from __future__ import annotations

import importlib._bootstrap_external as bootstrap
import importlib.util
from pathlib import Path

from writer_rig import WRITER_SOURCE, run, worktree, write_script

from physgate.orchestrator.trajectory import Seal
from physgate.series.collect import collect
from physgate.series.reader import read_record
from physgate.series.record import parse_record

#: Code of the size the helper's source has, which records another number.
PLANTED = "GAIN = 9.0\n"


def _helper(base: Path) -> Path:
    return base / "modules" / "control" / "helper.py"


def _planted_pyc(source: Path) -> bytes:
    """A compiled file of other code whose header names ``source``'s time and size."""
    held = source.stat()
    assert len(PLANTED) == held.st_size
    code = compile(PLANTED, str(source), "exec")
    return bytes(bootstrap._code_to_timestamp_pyc(code, held.st_mtime, held.st_size))  # type: ignore[attr-defined]


def _outbox(base: Path) -> list[str]:
    outbox = base / ".physgate" / "series"
    return sorted(p.name for p in outbox.iterdir()) if outbox.is_dir() else []


def test_a_planted_cache_whose_header_matches_its_source_refuses_the_record(
    tmp_path: Path,
) -> None:
    base = worktree(tmp_path)
    source = _helper(base)
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir()
    cache.write_bytes(_planted_pyc(source))
    done = run(write_script(base))
    assert done.returncode != 0, "the record was written on code other than its source"
    assert "compiled code lies at modules/control/__pycache__/helper." in done.stderr.replace(
        "\n", " "
    ), done.stderr
    assert "in place of modules/control/helper.py's source" in done.stderr.replace("\n", " ")
    assert _outbox(base) == []


def test_a_compiled_file_beside_its_source_refuses_the_record(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    source = _helper(base)
    source.with_suffix(".pyc").write_bytes(_planted_pyc(source))
    done = run(write_script(base))
    assert done.returncode != 0
    assert "compiled code lies at modules/control/helper.pyc" in done.stderr.replace("\n", " ")
    assert _outbox(base) == []


def test_a_module_loaded_from_compiled_code_alone_refuses_the_record(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    source = _helper(base)
    data = _planted_pyc(source)
    source.unlink()
    source.with_suffix(".pyc").write_bytes(data)
    done = run(write_script(base))
    assert done.returncode != 0
    assert "modules/control/helper.pyc was not loaded from its source" in done.stderr.replace(
        "\n", " "
    )
    assert _outbox(base) == []


def test_a_clean_worktree_writes_its_record_naming_the_source_as_before(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    done = run(write_script(base))
    assert done.returncode == 0, done.stderr
    record = parse_record(Path(done.stdout.strip()).read_bytes())
    assert "modules/control/helper.py" in {f.path for f in record.producer.loaded}


def test_a_record_an_earlier_writer_wrote_is_collected_and_read_as_before(
    tmp_path: Path,
) -> None:
    # Written by a writer without the check, as every record before it was: collection holds
    # it to the writer's bytes in its own worktree, and reading holds it to its seal; neither
    # asks what the harness's writer is now.
    base = worktree(tmp_path)
    check = b"    compiled = _compiled_in_place(base)\n"
    assert WRITER_SOURCE.count(check) == 1
    earlier = WRITER_SOURCE.replace(check, b"    compiled = None\n")
    (base / ".physgate" / "lib" / "series_writer.py").write_bytes(earlier)
    done = run(write_script(base))
    assert done.returncode == 0, done.stderr
    run_dir = tmp_path / "run"
    series = collect(
        base,
        module_dir="modules/control",
        run_dir=run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id="session-1",
        object_format="sha1",
    )
    assert series.refused == ()
    (sealed,) = series.records
    path = run_dir / "series" / "control-1" / "1" / "session-1" / f"{sealed.record_id}.json"
    record = read_record(path, Seal(sha256=sealed.sha256, length=sealed.length))
    assert record.id == "step_nominal"
