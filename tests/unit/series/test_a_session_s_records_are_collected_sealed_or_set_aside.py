"""When a session ends, its outbox is emptied: valid records sealed, everything else set aside.

Records here are written by the real writer from real scripts, as a role's would be. What
is checked is what the collector promises: a record whose code is the module's, unchanged,
is copied out and sealed; anything else is refused or discarded with its reason, moved out
of the worktree and listed; the outbox is left empty; and nothing the collector does reaches
through a link, so a role cannot make it move or delete files outside its own outbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from writer_rig import run, worktree, write_script

from physgate.orchestrator.trajectory import Seal
from physgate.series import collect as collect_module
from physgate.series.collect import DISCARDED_DIR, REFUSED_DIR, collect, empty_outbox
from physgate.series.exceptions import RecordTamperedError
from physgate.series.reader import read_record, record_path
from physgate.series.seal import SessionSeries

MODULE = "modules/control"


def _collect(base: Path, run_dir: Path, session: str = "session-1") -> SessionSeries:
    return collect(
        base,
        module_dir=MODULE,
        run_dir=run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id=session,
        object_format="sha1",
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path)) / "run"


def _outbox(base: Path) -> Path:
    return base / ".physgate" / "series"


def _written(base: Path, **kwargs: str) -> Path:
    done = run(write_script(base, **kwargs))
    assert done.returncode == 0, done.stderr
    return Path(done.stdout.strip())


CACHE = ".physgate/lib/__pycache__"


def _caches(series: SessionSeries) -> list[str]:
    return [e.name for e in series.discarded if e.name.startswith(CACHE)]


def test_a_record_whose_code_is_the_module_s_is_sealed_and_leaves_the_worktree(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    written = _written(base)
    data = written.read_bytes()
    series = _collect(base, run_dir)
    assert series.refused == ()
    assert [e.name for e in series.discarded] == _caches(series)
    (sealed,) = series.records
    assert sealed.record_id == "step_nominal"
    assert (sealed.sha256, sealed.length) == (hashlib.sha256(data).hexdigest(), len(data))
    script = base / MODULE / "sim.py"
    assert sealed.script == "modules/control/sim.py"
    assert sealed.script_sha256 == hashlib.sha256(script.read_bytes()).hexdigest()
    git_says = subprocess.run(
        ["git", "hash-object", str(script)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert sealed.script_blob == git_says
    assert list(_outbox(base).iterdir()) == []
    path = record_path(run_dir, "control-1", 1, "session-1", "step_nominal")
    assert path.read_bytes() == data
    assert path.stat().st_nlink == 1
    held = Seal(sha256=sealed.sha256, length=sealed.length)
    assert read_record(path, held).id == sealed.record_id


def test_no_outbox_is_no_records(tmp_path: Path, run_dir: Path) -> None:
    assert _collect(worktree(tmp_path), run_dir) == SessionSeries()


def _refused_reason(base: Path, run_dir: Path, name: str) -> str:
    series = _collect(base, run_dir)
    assert series.records == ()
    assert [e.name for e in series.refused] == [name]
    assert list(_outbox(base).iterdir()) == []
    kept = run_dir / "series" / REFUSED_DIR / "control-1" / "1" / "session-1" / name
    assert kept.exists() or kept.is_symlink()
    return series.refused[0].reason


def test_a_file_not_named_as_a_record_is_refused_and_moved_aside(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _outbox(base).mkdir(parents=True)
    (_outbox(base) / "Results.txt").write_text("not a record\n")
    assert "not a record's name" in _refused_reason(base, run_dir, "Results.txt")


def test_a_writer_s_temporary_file_is_discarded(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    _outbox(base).mkdir(parents=True)
    (_outbox(base) / ".step.json.123.tmp").write_text("{")
    series = _collect(base, run_dir)
    assert series.records == () and series.refused == ()
    assert [e.name for e in series.discarded] == [".step.json.123.tmp"]
    assert (run_dir / "series" / DISCARDED_DIR / "session-1" / ".step.json.123.tmp").exists()


def test_a_record_that_does_not_validate_is_refused_with_the_schema_s_reason(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _outbox(base).mkdir(parents=True)
    (_outbox(base) / "step.json").write_text('{"format": "series.v1", "id": "step"}')
    assert "does not validate" in _refused_reason(base, run_dir, "step.json")


def test_a_file_named_for_another_record_is_refused(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    written = _written(base)
    written.rename(written.with_name("other.json"))
    assert "named for another record" in _refused_reason(base, run_dir, "other.json")


def test_a_record_whose_script_ran_from_outside_the_worktree_is_refused(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    scratch = Path(os.path.realpath(tmp_path)) / "scratch"
    scratch.mkdir()
    (scratch / "helper.py").write_text("GAIN = 2.0\n")
    lib = base / ".physgate" / "lib"
    script = scratch / "sim.py"
    script.write_text(
        f"import sys\nsys.path.insert(0, {str(lib)!r})\nimport series_writer, helper\n"
        "series_writer.record('step_nominal', title='t', axis='time', x=('t', 's', [0.0]),"
        " traces=[('p', 'm', [helper.GAIN])])\n"
    )
    done = subprocess.run(
        [sys.executable, "-E", "-s", str(script)],
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(base / ".home")},
    )
    assert done.returncode == 0, done.stderr
    assert "outside the worktree" in _refused_reason(base, run_dir, "step_nominal.json")


def test_a_record_whose_code_loaded_from_outside_the_module_is_refused(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    outside = base / "modules" / "power"
    outside.mkdir(parents=True)
    (outside / "elsewhere.py").write_text("VALUE = 1\n")
    _written(base, extra=f"sys.path.insert(0, {str(outside)!r})\nimport elsewhere")
    reason = _refused_reason(base, run_dir, "step_nominal.json")
    assert "outside the module ran: modules/power/elsewhere.py" in reason


def test_a_record_whose_script_changed_after_it_was_written_is_refused(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _written(base)
    with (base / MODULE / "sim.py").open("a") as script:
        script.write("# edited after the run\n")
    reason = _refused_reason(base, run_dir, "step_nominal.json")
    assert "changed after the record was written" in reason


def test_a_record_with_a_second_name_is_refused(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    written = _written(base)
    os.link(written, base / MODULE / "kept.json")
    assert "another name" in _refused_reason(base, run_dir, "step_nominal.json")


def test_records_past_the_session_s_bound_are_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    _written(base, name="a.py", record_id="first")
    _written(base, name="b.py", record_id="second")
    monkeypatch.setattr(collect_module, "MAX_RECORDS_PER_SESSION", 1)
    series = _collect(base, run_dir)
    assert [r.record_id for r in series.records] == ["first"]
    assert [e.name for e in series.refused] == ["second.json"]
    assert "over the session's bound" in series.refused[0].reason


def test_what_is_set_aside_is_listed_under_the_line_s_bound(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    _outbox(base).mkdir(parents=True)
    for n in range(5):
        (_outbox(base) / f"junk{n}.txt").write_text("x")
    monkeypatch.setattr(collect_module, "MAX_ENTRIES", 3)
    series = _collect(base, run_dir)
    assert [e.name for e in series.refused] == ["junk0.txt", "junk1.txt", "(more)"]
    assert "3 more entries" in series.refused[-1].reason
    assert list(_outbox(base).iterdir()) == []


def _elsewhere(tmp_path: Path) -> Path:
    """A directory standing in for one a role must not reach, holding a valid-looking record."""
    target = Path(os.path.realpath(tmp_path)) / "harness-stand-in"
    target.mkdir()
    (target / "step_nominal.json").write_text("{}")
    (target / "precious.py").write_text("KEEP = True\n")
    return target


def _untouched(target: Path) -> None:
    assert sorted(p.name for p in target.iterdir()) == ["precious.py", "step_nominal.json"]
    assert (target / "precious.py").read_text() == "KEEP = True\n"


def test_an_outbox_that_is_a_link_is_refused_and_nothing_behind_it_is_moved(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    target = _elsewhere(tmp_path)
    _outbox(base).parent.mkdir(parents=True, exist_ok=True)
    _outbox(base).symlink_to(target, target_is_directory=True)
    series = _collect(base, run_dir)
    assert series.records == ()
    assert "moved aside, not followed" in series.refused[0].reason
    _untouched(target)
    assert not os.path.lexists(_outbox(base))


def test_a_physgate_directory_that_is_a_link_is_refused_and_nothing_behind_it_is_moved(
    tmp_path: Path, run_dir: Path
) -> None:
    base = Path(os.path.realpath(tmp_path)) / "wt"
    base.mkdir()
    target = _elsewhere(tmp_path)
    (target / "series").mkdir()
    (target / "series" / "step_nominal.json").write_text("{}")
    (base / ".physgate").symlink_to(target, target_is_directory=True)
    series = _collect(base, run_dir)
    assert series.records == ()
    assert "nothing was collected or moved" in series.refused[0].reason
    assert (base / ".physgate").is_symlink()
    assert (target / "series" / "step_nominal.json").read_text() == "{}"
    names = sorted(p.name for p in target.iterdir())
    assert names == ["precious.py", "series", "step_nominal.json"]


def test_before_a_session_whatever_an_earlier_one_left_is_moved_aside(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _written(base)
    left = empty_outbox(base, run_dir, "session-2")
    assert [(e.name, e.reason) for e in left] == [
        ("step_nominal.json", "left in the outbox before this session began")
    ]
    assert list(_outbox(base).iterdir()) == []
    assert (run_dir / "series" / DISCARDED_DIR / "session-2" / "step_nominal.json").exists()
    series = _collect(base, run_dir, session="session-2")
    assert series.records == () and series.refused == ()


def test_earlier_discards_head_the_session_s_own_list(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    _written(base)
    left = empty_outbox(base, run_dir, "session-2")
    _written(base, record_id="second")
    series = collect(
        base,
        module_dir=MODULE,
        run_dir=run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id="session-2",
        object_format="sha1",
        discarded_before=left,
    )
    assert [e.name for e in series.discarded][0] == "step_nominal.json"
    assert [r.record_id for r in series.records] == ["second"]


def test_collecting_changes_nothing_in_the_worktree_but_the_outbox(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _written(base)
    cache = base / CACHE
    before = {
        str(p.relative_to(base)): p.read_bytes()
        for p in base.rglob("*")
        if p.is_file() and _outbox(base) not in p.parents and cache not in p.parents
    }
    assert any(cache.iterdir())
    _collect(base, run_dir)
    after = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    assert after == before
    assert not cache.exists()


def test_only_the_writer_s_own_cache_is_removed_and_each_file_is_listed(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _written(base)
    cache = base / CACHE
    (cache / "planted.cpython-312.pyc").write_bytes(b"not the writer's")
    (cache / "series_writer.cpython-399.pyc").mkdir()
    series = _collect(base, run_dir)
    assert len(_caches(series)) == 1
    assert sorted(p.name for p in cache.iterdir()) == [
        "planted.cpython-312.pyc",
        "series_writer.cpython-399.pyc",
    ]


def test_a_cache_directory_that_is_a_link_is_left_as_it_is(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    target = _elsewhere(tmp_path)
    (target / "series_writer.cpython-312.pyc").write_bytes(b"x")
    (base / CACHE).symlink_to(target, target_is_directory=True)
    series = _collect(base, run_dir)
    assert _caches(series) == []
    assert (target / "series_writer.cpython-312.pyc").exists()


def _no_link_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every path check see no link, as it would if one were swapped in just after it."""
    monkeypatch.setattr(os.path, "realpath", os.path.normpath)


def test_a_parent_swapped_for_a_link_after_the_check_is_still_not_followed(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = Path(os.path.realpath(tmp_path)) / "wt"
    base.mkdir()
    target = _elsewhere(tmp_path)
    (target / "series").mkdir()
    (target / "series" / "step_nominal.json").write_text("{}")
    (base / ".physgate").symlink_to(target, target_is_directory=True)
    _no_link_seen(monkeypatch)
    series = _collect(base, run_dir)
    assert series.records == ()
    assert (target / "series" / "step_nominal.json").read_text() == "{}"
    names = sorted(p.name for p in target.iterdir())
    assert names == ["precious.py", "series", "step_nominal.json"]


def test_code_reached_through_a_directory_swapped_for_a_link_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    lib = base / MODULE / "lib"
    lib.mkdir()
    (lib / "shared.py").write_text("SHARED = 3\n")
    _written(base, extra=f"sys.path.insert(0, {str(lib)!r})\nimport shared")
    elsewhere = Path(os.path.realpath(tmp_path)) / "elsewhere-lib"
    lib.rename(elsewhere)
    lib.symlink_to(elsewhere, target_is_directory=True)
    _no_link_seen(monkeypatch)
    reason = _refused_reason(base, run_dir, "step_nominal.json")
    assert "link" in reason


def test_what_is_set_aside_never_replaces_what_was_set_aside_before(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    earlier = run_dir / "series" / DISCARDED_DIR / "session-2" / "step_nominal.json"
    earlier.parent.mkdir(parents=True)
    earlier.write_text("set aside earlier\n")
    _written(base)
    empty_outbox(base, run_dir, "session-2")
    assert earlier.read_text() == "set aside earlier\n"
    assert (earlier.parent / "step_nominal.json.1").exists()


def test_a_link_planted_where_the_run_s_records_go_is_refused_and_written_through_never(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _written(base)
    target = _elsewhere(tmp_path)
    (run_dir / "series").mkdir(parents=True)
    (run_dir / "series" / "control-1").symlink_to(target, target_is_directory=True)
    with pytest.raises(RecordTamperedError, match="link or not a directory"):
        _collect(base, run_dir)
    _untouched(target)


# ── code from the interpreter's own installation ─────────────────────────────


def _with_loaded(base: Path, extra: Path) -> None:
    """The written record, as if the producing process had also loaded ``extra``.

    A distribution's interpreter can load a file of its own installation that lies outside
    its prefix (Ubuntu's ``/etc/python3.12/sitecustomize.py``), and the writer names it. The
    record is rewritten here to name a stand-in for it, with its digest, as the writer would.
    """
    written = _written(base)
    body = json.loads(written.read_text())
    digest = hashlib.sha256(extra.read_bytes()).hexdigest()
    body["producer"]["loaded"].append({"path": str(extra), "sha256": digest})
    written.write_text(json.dumps(body))


def _sitecustomize(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    path = where / "sitecustomize.py"
    path.write_text("# a distribution's own interpreter customisation\n")
    return Path(os.path.realpath(path))


def _collect_with(base: Path, run_dir: Path, writable: tuple[Path, ...]) -> SessionSeries:
    return collect(
        base,
        module_dir=MODULE,
        run_dir=run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id="session-1",
        object_format="sha1",
        writable_roots=writable,
    )


@pytest.fixture
def unwritable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every file outside the worktree reads as one the session's user cannot write.

    A test cannot make a root-owned file; the property under test here is the roots, and
    the writability check has a test of its own.
    """
    monkeypatch.setattr(collect_module, "_writable_by_the_session", lambda path: False)


def _installed_at(
    monkeypatch: pytest.MonkeyPatch, prefixes: tuple[Path, ...], system: Path
) -> None:
    """The harness's interpreter, as if installed at stand-ins under the test's own directory.

    Its prefix is ``prefixes``, and its distribution's ``sitecustomize`` is ``system``.
    """
    # Added to the real installation, which a distribution's interpreter loads code from
    # in every process (Ubuntu's own sitecustomize, for one).
    real = collect_module.trusted_installation()
    trusted = collect_module.Installation(
        prefixes=(*real.prefixes, *(Path(os.path.realpath(p)) for p in prefixes)),
        system_customize=(*real.system_customize, system),
    )
    monkeypatch.setattr(collect_module, "trusted_installation", lambda: trusted)


@pytest.mark.usefixtures("unwritable")
def test_interpreter_code_outside_every_session_writable_root_is_admitted_and_recorded(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    system = _sitecustomize(Path(os.path.realpath(tmp_path)) / "system" / "etc" / "python3.12")
    _installed_at(monkeypatch, (), system)
    _with_loaded(base, system)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.refused == ()
    (sealed,) = series.records
    digest = hashlib.sha256(system.read_bytes()).hexdigest()
    assert (str(system), digest) in [(e.path, e.sha256) for e in sealed.environment]
    assert str(system) not in [c.path for c in sealed.loaded]


@pytest.mark.usefixtures("unwritable")
def test_the_same_file_in_the_session_home_s_user_site_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    home = base / ".home"
    planted = _sitecustomize(home / ".local" / "lib" / "python3.12" / "site-packages")
    _installed_at(monkeypatch, (), planted)
    _with_loaded(base, planted)
    series = _collect_with(base, run_dir, writable=(home,))
    assert series.records == ()
    (refused,) = series.refused
    assert "a place the session can write" in refused.reason


@pytest.mark.usefixtures("unwritable")
def test_the_same_file_in_the_temporary_directory_is_refused_by_default(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    planted = _sitecustomize(Path(os.path.realpath(tempfile.mkdtemp(dir=tmp_path))))
    _installed_at(monkeypatch, (), planted)
    _with_loaded(base, planted)
    if not any(planted.is_relative_to(r) for r in collect_module.temporary_roots()):
        pytest.skip("this test's directory is not under the machine's temporary directory")
    series = _collect(base, run_dir)
    assert series.records == ()
    assert "a place the session can write" in series.refused[0].reason


def test_interpreter_code_the_session_s_user_can_write_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    system = _sitecustomize(Path(os.path.realpath(tmp_path)) / "system" / "etc" / "python3.12")
    _installed_at(monkeypatch, (), system)
    _with_loaded(base, system)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    (refused,) = series.refused
    assert "the session's user can write" in refused.reason


@pytest.mark.usefixtures("unwritable")
def test_interpreter_code_changed_after_the_record_was_written_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    system = _sitecustomize(Path(os.path.realpath(tmp_path)) / "system" / "etc" / "python3.12")
    _installed_at(monkeypatch, (), system)
    _with_loaded(base, system)
    system.write_text("# changed\n")
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    assert "changed after the record was written" in series.refused[0].reason


def _module_file(where: Path, name: str = "extra.py") -> Path:
    where.mkdir(parents=True, exist_ok=True)
    path = where / name
    path.write_text("VALUE = 1\n")
    return Path(os.path.realpath(path))


@pytest.mark.usefixtures("unwritable")
def test_code_outside_the_interpreter_s_own_installation_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unwritable and outside every session-writable root, but not the harness interpreter's.
    base = worktree(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    _installed_at(monkeypatch, (root / "prefix",), root / "etc" / "python3.12" / "sitecustomize.py")
    elsewhere = _module_file(root / "opt" / "vendor")
    _with_loaded(base, elsewhere)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    assert "not the interpreter's own installation" in series.refused[0].reason


@pytest.mark.usefixtures("unwritable")
def test_code_under_the_interpreter_s_own_prefix_is_admitted(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    _installed_at(monkeypatch, (root / "prefix",), root / "etc" / "python3.12" / "sitecustomize.py")
    library = _module_file(root / "prefix" / "lib" / "python3.12")
    _with_loaded(base, library)
    (sealed,) = _collect_with(base, run_dir, writable=(base / ".home",)).records
    assert str(library) in [e.path for e in sealed.environment]


@pytest.mark.usefixtures("unwritable")
@pytest.mark.parametrize("name", ["sitecustomize.py", "usercustomize.py", "extra.pth"])
def test_a_customisation_hook_anywhere_but_the_system_location_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Inside the interpreter's own prefix, unwritable: still refused, since a customisation
    # hook runs in every process and only the distribution's own one is expected.
    base = worktree(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    _installed_at(monkeypatch, (root / "prefix",), root / "etc" / "python3.12" / "sitecustomize.py")
    hook = _module_file(root / "prefix" / "lib" / "python3.12" / "site-packages", name)
    _with_loaded(base, hook)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    assert "customisation" in series.refused[0].reason


@pytest.mark.usefixtures("unwritable")
def test_a_session_writable_root_spelt_in_another_case_is_still_that_root(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = worktree(tmp_path)
    home = Path(os.path.realpath(tmp_path)) / "session" / "home"
    planted = _module_file(home / "lib")
    variant = Path(str(planted).replace("/session/home/", "/SESSION/HOME/"))
    if not variant.exists() or os.path.realpath(variant) != str(variant):
        pytest.skip("this volume is case-sensitive, or resolves case; the variant is not one")
    root = Path(os.path.realpath(tmp_path))
    _installed_at(monkeypatch, (root,), root / "etc" / "python3.12" / "sitecustomize.py")
    _with_loaded(base, variant)
    series = _collect_with(base, run_dir, writable=(home,))
    assert series.records == ()
    assert "a place the session can write" in series.refused[0].reason


def test_a_read_only_file_in_a_directory_the_session_can_write_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The file itself cannot be written, but its directory can: the file can be replaced.
    base = worktree(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    _installed_at(monkeypatch, (root / "prefix",), root / "etc" / "python3.12" / "sitecustomize.py")
    library = _module_file(root / "prefix" / "lib")
    library.chmod(0o444)
    _with_loaded(base, library)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    assert "the session's user can write" in series.refused[0].reason


def test_the_trusted_installation_is_the_harness_interpreter_s_own() -> None:
    found = collect_module.trusted_installation()
    assert Path(os.path.realpath(sys.base_prefix)) in found.prefixes
    major, minor = sys.version_info[:2]
    assert found.system_customize == (Path(f"/etc/python{major}.{minor}/sitecustomize.py"),)


@pytest.mark.usefixtures("unwritable")
@pytest.mark.parametrize("name", ["usercustomize.py", "extra.pth"])
def test_a_customisation_hook_beside_the_system_one_is_refused(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Admission is by the system file's exact path, never by the directory it lies in.
    base = worktree(tmp_path)
    system = _sitecustomize(Path(os.path.realpath(tmp_path)) / "system" / "etc" / "python3.12")
    _installed_at(monkeypatch, (), system)
    beside = _module_file(system.parent, name)
    _with_loaded(base, beside)
    series = _collect_with(base, run_dir, writable=(base / ".home",))
    assert series.records == ()
    assert "customisation" in series.refused[0].reason
