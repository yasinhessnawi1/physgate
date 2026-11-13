"""Library code behind a record is the run's recorded tool environment, named once by its digest.

The writer, told the run's tool environment through the session's environment, names every file
of code it loaded from the environment's roots once, by the environment's digest, and every
other file outside the module by its path: the running interpreter's own places are no longer
left out, so a session's own virtual environment or a ``PYTHONHOME`` of its own is named. The
collector seals library code only as the run's environment (the same roots and digest, held to
the record before the session, the OS layer around it) and refuses every other file outside the
module. A session told no tool environment writes and is judged exactly as before.

Scripts run as real processes on this machine's interpreter; the "environment" is a stand-in
directory of the test's own (no library of the real tool environment is used here).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest
from series_fixture import DIGEST, encode, record_dict
from writer_rig import worktree, write_script

from physgate.series import collect as collect_module
from physgate.series.collect import SeriesEnvironment, collect
from physgate.series.record import parse_record
from physgate.series.seal import SessionSeries
from physgate.series.writer import ENVIRONMENT_VARIABLE

MODULE = "modules/control"
ENVIRONMENT_DIGEST = "e" * 64
#: The interpreter itself, not the harness's virtual environment over it: its standard library
#: is what a stand-in environment's roots hold, as a real one's hold its own.
BASE = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
BASE_PREFIX = os.path.realpath(sys.base_prefix)
STDLIB = sysconfig.get_paths()["stdlib"]
VERSION = f"python{sys.version_info[0]}.{sys.version_info[1]}"

LIBRARY_IMPORT = "import standin_library\nassert standin_library.GAIN == 2.0"


def _stand_in_environment(tmp_path: Path) -> Path:
    """A directory standing in for a tool environment's library root."""
    root = Path(os.path.realpath(tmp_path)) / "environment"
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "standin_library.py").write_text("GAIN = 2.0\n")
    return root


def _told(roots: list[str], sha256: str = ENVIRONMENT_DIGEST) -> str:
    return json.dumps({"roots": roots, "sha256": sha256})


def _run(
    script: Path,
    *,
    interpreter: str = BASE,
    told: str | None = None,
    flags: tuple[str, ...] = ("-E", "-s"),
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    base = script.parents[2]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(base / ".home"), **(extra_env or {})}
    if told is not None:
        env[ENVIRONMENT_VARIABLE] = told
    return subprocess.run(
        [interpreter, *flags, str(script)],
        cwd=base,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def _library_script(base: Path, root: Path, extra: str = "") -> Path:
    imports = f"sys.path.insert(0, {str(root / 'lib')!r})\n{LIBRARY_IMPORT}\n{extra}"
    return write_script(base, extra=imports)


def _written(done: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert done.returncode == 0, done.stderr
    raw = json.loads(Path(done.stdout.strip()).read_bytes())
    assert isinstance(raw, dict)
    return raw


def _loaded(raw: dict[str, Any]) -> set[str]:
    return {entry["path"] for entry in raw["producer"]["loaded"]}


# -- the writer --------------------------------------------------------------------------------


def test_code_from_the_environment_s_roots_is_named_once_by_the_environment_s_digest(
    tmp_path: Path,
) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    roots = [BASE_PREFIX, str(root)]
    raw = _written(_run(_library_script(base, root), told=_told(roots)))
    assert raw["producer"].get("environment") == {"roots": roots, "sha256": ENVIRONMENT_DIGEST}
    loaded = _loaded(raw)
    assert not [p for p in loaded if p.startswith((BASE_PREFIX + "/", str(root) + "/"))], loaded
    assert loaded == {".physgate/lib/series_writer.py", "modules/control/helper.py"}
    parse_record(Path(_run_path(base)).read_bytes())


def _run_path(base: Path) -> str:
    return str(base / ".physgate" / "series" / "step_nominal.json")


def test_without_an_environment_the_record_is_written_as_before(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    raw = _written(_run(write_script(base)))
    assert "environment" not in raw["producer"]
    # The interpreter's own installation is still left out where no environment is named.
    assert not [p for p in _loaded(raw) if p.startswith(BASE_PREFIX + "/")]


def test_a_session_s_own_virtual_environment_is_named_file_by_file(tmp_path: Path) -> None:
    """A venv the session made, its library edited, is named by path: never left out."""
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    venv = Path(os.path.realpath(tmp_path)) / "session-home" / "venv"
    subprocess.run([BASE, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    (site,) = venv.glob(f"lib/{VERSION}/site-packages")
    (site / "control.py").write_text("def margin():\n    return 'edited'\n")
    script = write_script(base, extra="import control\nassert control.margin() == 'edited'")
    raw = _written(_run(script, interpreter=str(venv / "bin" / "python"), told=_told([str(root)])))
    assert str(site / "control.py") in _loaded(raw)


def _session_home(tmp_path: Path) -> Path:
    """A ``PYTHONHOME`` of the session's own: the standard library linked in, two files its own."""
    home = Path(os.path.realpath(tmp_path)) / "session-home" / "python"
    library = home / "lib" / VERSION
    library.mkdir(parents=True)
    for entry in Path(STDLIB).iterdir():
        if entry.name not in ("sitecustomize.py", "control.py"):
            (library / entry.name).symlink_to(entry)
    (library / "control.py").write_text("def margin():\n    return 'edited'\n")
    (library / "sitecustomize.py").write_text("CUSTOMISED = True\n")
    return home


def test_a_pythonhome_of_the_session_s_own_is_named_its_site_hook_too(tmp_path: Path) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    home = _session_home(tmp_path)
    script = write_script(base, extra="import control\nassert control.margin() == 'edited'")
    raw = _written(
        _run(script, told=_told([str(root)]), flags=("-s",), extra_env={"PYTHONHOME": str(home)})
    )
    loaded = _loaded(raw)
    library = home / "lib" / VERSION
    assert str(library / "control.py") in loaded, loaded
    assert str(library / "sitecustomize.py") in loaded, loaded


@pytest.mark.parametrize(
    "told",
    [
        "not json",
        json.dumps({"roots": [], "sha256": ENVIRONMENT_DIGEST}),
        json.dumps({"roots": ["relative/root"], "sha256": ENVIRONMENT_DIGEST}),
        json.dumps({"roots": ["/opt/../etc"], "sha256": ENVIRONMENT_DIGEST}),
        json.dumps({"roots": ["/opt/env"], "sha256": "not a digest"}),
        json.dumps({"roots": ["/opt/env"], "sha256": ENVIRONMENT_DIGEST, "more": 1}),
        json.dumps({"roots": ["/opt/env"] * 17, "sha256": ENVIRONMENT_DIGEST}),
        json.dumps(["/opt/env"]),
    ],
)
def test_an_environment_told_in_a_form_a_record_cannot_name_refuses_the_record(
    tmp_path: Path, told: str
) -> None:
    base = worktree(tmp_path)
    done = _run(write_script(base), told=told)
    assert done.returncode != 0
    assert "tool environment" in done.stderr
    assert not (base / ".physgate" / "series").exists()


def test_a_bytecode_cache_kept_elsewhere_refuses_a_record_on_the_environment(
    tmp_path: Path,
) -> None:
    """Python runs a cached file under the prefix in place of a source whose stamp it matches."""
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    cache = Path(os.path.realpath(tmp_path)) / "session-home" / "cache"
    done = _run(
        _library_script(base, root),
        told=_told([BASE_PREFIX, str(root)]),
        flags=("-E", "-s", "-X", f"pycache_prefix={cache}"),
    )
    assert done.returncode != 0
    assert "bytecode" in done.stderr
    assert not (base / ".physgate" / "series").exists()


# -- the collector -----------------------------------------------------------------------------


def _collect(
    base: Path,
    run_dir: Path,
    environment: SeriesEnvironment | None,
    writable: tuple[Path, ...] | None = None,
) -> SessionSeries:
    return collect(
        base,
        module_dir=MODULE,
        run_dir=run_dir,
        subtask_id="control-1",
        attempt=1,
        session_id="session-1",
        object_format="sha1",
        tool_environment=environment,
        writable_roots=writable,
    )


def _environment(named: list[str], /, **changes: Any) -> SeriesEnvironment:  # noqa: ANN401
    given: dict[str, Any] = {
        "roots": tuple(named),
        "sha256": ENVIRONMENT_DIGEST,
        "held": True,
        "layer": True,
    }
    given.update(changes)
    return SeriesEnvironment(**given)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path)) / "run"


def _only_refusal(series: SessionSeries) -> str:
    assert series.records == ()
    assert [e.name for e in series.refused] == ["step_nominal.json"]
    return series.refused[0].reason


def test_a_record_on_the_run_s_own_environment_seals(tmp_path: Path, run_dir: Path) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    roots = [BASE_PREFIX, str(root)]
    _written(_run(_library_script(base, root), told=_told(roots)))
    series = _collect(base, run_dir, _environment(roots))
    assert series.refused == ()
    (sealed,) = series.records
    assert sealed.record_id == "step_nominal"
    # Nothing of the environment is listed file by file: its digest stands for it.
    assert sealed.environment == ()


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"sha256": "f" * 64}, "another tool environment"),
        ({"roots": ("/opt/elsewhere",)}, "another tool environment"),
        ({"held": False}, "not held"),
        ({"layer": False}, "OS layer"),
    ],
)
def test_a_record_on_another_or_an_unheld_environment_is_kept_unsealed_with_its_reason(
    tmp_path: Path, run_dir: Path, change: dict[str, Any], why: str
) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    roots = [BASE_PREFIX, str(root)]
    _written(_run(_library_script(base, root), told=_told(roots)))
    environment = _environment(roots, **change)
    assert why in _only_refusal(_collect(base, run_dir, environment))


def test_a_session_s_own_virtual_environment_is_refused_at_collection(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    venv = Path(os.path.realpath(tmp_path)) / "session-home" / "venv"
    subprocess.run([BASE, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    (site,) = venv.glob(f"lib/{VERSION}/site-packages")
    (site / "control.py").write_text("def margin():\n    return 'edited'\n")
    roots = [BASE_PREFIX, str(root)]
    script = write_script(base, extra="import control\nassert control.margin() == 'edited'")
    _written(_run(script, interpreter=str(venv / "bin" / "python"), told=_told(roots)))
    reason = _only_refusal(_collect(base, run_dir, _environment(roots)))
    assert "not the run's tool environment" in reason
    assert str(venv) in reason


def test_a_pythonhome_of_the_session_s_own_is_refused_at_collection(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    root = _stand_in_environment(tmp_path)
    home = _session_home(tmp_path)
    roots = [BASE_PREFIX, str(root)]
    script = write_script(base, extra="import control\nassert control.margin() == 'edited'")
    _written(_run(script, told=_told(roots), flags=("-s",), extra_env={"PYTHONHOME": str(home)}))
    reason = _only_refusal(_collect(base, run_dir, _environment(roots)))
    assert "not the run's tool environment" in reason
    assert str(home) in reason


def _hand_written(base: Path, producer: dict[str, Any]) -> None:
    outbox = base / ".physgate" / "series"
    outbox.mkdir(parents=True)
    script = base / MODULE / "sim.py"
    script.write_text("# the script\n")
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    body = record_dict(producer={"script": {"path": f"{MODULE}/sim.py", "sha256": sha}, **producer})
    (outbox / "step_nominal.json").write_bytes(encode(body))


def test_a_record_naming_no_environment_on_a_run_that_records_one_is_refused(
    tmp_path: Path, run_dir: Path
) -> None:
    """A session that dropped the variable left its interpreter's places out: never sealed."""
    base = worktree(tmp_path)
    _hand_written(base, {"loaded": []})
    reason = _only_refusal(_collect(base, run_dir, _environment(["/opt/env"])))
    assert "names no tool environment" in reason


def test_a_record_naming_an_environment_on_a_run_that_records_none_is_refused(
    tmp_path: Path, run_dir: Path
) -> None:
    base = worktree(tmp_path)
    _hand_written(base, {"environment": {"roots": ["/opt/env"], "sha256": ENVIRONMENT_DIGEST}})
    reason = _only_refusal(_collect(base, run_dir, None))
    assert "records no tool environment" in reason


def test_on_a_run_with_an_environment_the_interpreter_s_own_installation_is_not_admitted(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule a file the session's user cannot write once passed is replaced, not kept beside.

    Without an environment the installation's file is admitted, as before (the control).
    """
    installed = Path(os.path.realpath(tmp_path)) / "installation" / "lib" / "own.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("OWN = 1\n")
    sha = hashlib.sha256(installed.read_bytes()).hexdigest()
    monkeypatch.setattr(
        collect_module,
        "trusted_installation",
        lambda: collect_module.Installation(prefixes=(installed.parents[1],), system_customize=()),
    )
    monkeypatch.setattr(collect_module, "_writable_by_the_session", lambda _path: False)
    environment = {"roots": ["/opt/env"], "sha256": ENVIRONMENT_DIGEST}
    loaded = [{"path": str(installed), "sha256": sha}]
    without = worktree(tmp_path / "without")
    _hand_written(without, {"loaded": loaded})
    admitted = _collect(without, run_dir / "without", None, ())
    assert admitted.refused == () and len(admitted.records) == 1
    base = worktree(tmp_path / "with")
    _hand_written(base, {"loaded": loaded, "environment": environment})
    reason = _only_refusal(_collect(base, run_dir / "with", _environment(["/opt/env"]), ()))
    assert "not the run's tool environment" in reason


def test_a_record_written_before_the_field_existed_reads_as_it_did() -> None:
    old = encode(record_dict())
    assert parse_record(old).producer.environment is None
    assert b"environment" not in old
    assert DIGEST in old.decode()
