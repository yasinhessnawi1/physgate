"""Role sessions run only inside the OS layer, unless the run's parameters allow its absence.

Without the layer, a role session's shell is bounded by the text hooks alone, and the outbox,
the held-out tier and the answer keys with it. So a run whose layer is absent is refused at its
configuration, and at every run and resume, by the same check that holds a run that acts on
queue decisions. ``os_layer_absent: allow`` lets it go on, for development: a flag of the
register, required in a new run's parameters, recorded in the run's configuration, and said on
every run's and resume's line of the OS layer. It never lets a run that acts on decisions go on,
and the evaluation refuses a reportable run that names it, whatever the layer.

The same check is held again where a role session is made, whatever led there: the dispatcher
spawns no role session without the layer's temporary directory, and ``physgate hooks install
--profile role`` writes no role settings without the sandbox, unless the run's recorded
configuration allows the absence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import CLEAN_HARNESS, make_config

from physgate.cli import main
from physgate.orchestrator import cli
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.events import Envelope, OsLayerChecked, read_events
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import load_run_config, os_layer_refusal, write_run_config
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ABSENT = Absent(reason="Linux: bubblewrap (bwrap) is not on the session's search path")
ENVELOPE = Envelope(
    seq=0, ts=utc_stamp(datetime(2026, 10, 22, tzinfo=UTC)), run_id="run-1", gate_mode="on"
)


def _rig(run_dir: Path, allowance: str) -> Rig:
    run_dir.mkdir(parents=True, exist_ok=True)
    return Rig(
        run_dir,
        dispatcher=FakeDispatcher(trajectories=run_dir / "sessions"),
        config_overrides={"os_layer_absent": allowance},
    )


def _checked(loop: Loop, layer: Present | Absent) -> None:
    """The OS layer's line, as the command records it before anything is spawned."""
    loop.record.emit(cli._os_layer_checked(loop.record.envelope(), loop.config, layer))


def _spawned(rig: Rig) -> int:
    """How many role sessions the run dispatched."""
    return len(rig.dispatcher.requests)


# -- the flag ---------------------------------------------------------------------------------


def test_the_allowance_is_a_flag_of_the_register() -> None:
    from physgate.flags import OS_LAYER_ABSENT, REGISTER

    assert OS_LAYER_ABSENT in REGISTER
    assert OS_LAYER_ABSENT.values == ("refuse", "allow")
    assert OS_LAYER_ABSENT.architecture == "ARCH-091"


def test_a_run_recorded_before_the_flag_reads_as_refuse_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    config = make_config(os_layer_absent="refuse", os_layer=PRESENT)
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert "os_layer_absent" not in json.loads(path.read_bytes())
    loaded = load_run_config(path)
    assert loaded.os_layer_absent == "refuse" and loaded.sha256() == config.sha256()


def test_an_allowance_is_recorded_in_the_run_s_manifest(tmp_path: Path) -> None:
    allowed = make_config(os_layer_absent="allow", os_layer=ABSENT)
    assert b'"os_layer_absent":"allow"' in allowed.canonical_bytes()
    path = tmp_path / "run.json"
    write_run_config(path, allowed)
    assert load_run_config(path).os_layer_absent == "allow"


def test_both_example_parameters_refuse_a_run_without_the_layer() -> None:
    paths = sorted(cli.EXAMPLES.glob("params.*.json"))
    assert len(paths) == 2
    for path in paths:
        assert json.loads(path.read_text())["os_layer_absent"] == "refuse"


# -- at the configuration ---------------------------------------------------------------------


def _decompose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowance: str | None) -> list[str]:
    from test_the_physgate_command_starts_and_decides import (  # noqa: PLC0415
        PARAMS,
        _decompose_args,
        fake_binary,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    # A binary older than the layer's pin: the layer is absent here, whatever the machine.
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    params = {k: v for k, v in PARAMS.items() if k != "os_layer_absent"}
    if allowance is not None:
        params["os_layer_absent"] = allowance
    return _decompose_args(tmp_path, params)


def test_a_new_run_without_the_layer_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_decompose(tmp_path, monkeypatch, "refuse")) == 2
    err = capsys.readouterr().err
    # Said out loud first, and never as allowed.
    assert "role sessions do not run without it" in err and "allowed for development" not in err
    error = json.loads(err.strip().splitlines()[-1])
    assert "runs only inside the OS layer" in error["error"]
    assert "predates the OS-layer pin" in error["error"]
    assert "os_layer_absent" in error["error"]
    assert not (tmp_path / "run").exists()


def test_a_new_run_that_does_not_name_the_flag_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_decompose(tmp_path, monkeypatch, None)) == 2
    assert json.loads(capsys.readouterr().err)["reason"].startswith("os_layer_absent")
    assert not (tmp_path / "run").exists()


def test_a_new_run_that_allows_the_absence_passes_the_check_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Stopped at the first requirement after the check, before any model call is spent.
    import physgate.evaluation.requirements as evaluation_requirements

    seen: list[RunFacts] = []

    def stop(facts: RunFacts) -> str | None:
        seen.append(facts)
        return "stopped after the check"

    monkeypatch.setattr(evaluation_requirements, "REQUIREMENTS", (stop,))
    assert main(_decompose(tmp_path, monkeypatch, "allow")) == 2
    err = capsys.readouterr().err
    assert json.loads(err.strip().splitlines()[-1])["requirements"] == "stopped after the check"
    (facts,) = seen
    assert facts.config.os_layer_absent == "allow" and isinstance(facts.os_layer, Absent)
    assert "the OS layer is absent" in err and "allowed for development" in err


# -- at every run and resume ------------------------------------------------------------------


def test_a_run_whose_layer_is_absent_here_is_refused_before_any_session(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", "refuse")
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, ABSENT)
    with pytest.raises(RunStateError, match="runs only inside the OS layer"):
        loop.run()
    loop.close()
    assert _spawned(rig) == 0


def test_a_run_with_no_layer_line_is_refused_like_one_absent(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", "refuse")
    loop = rig.open()
    loop.start(plan("power"))
    with pytest.raises(RunStateError, match="not recorded"):
        loop.run()
    loop.close()


def test_a_resume_whose_layer_is_absent_here_is_refused(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", "refuse")
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, PRESENT)
    loop.run()
    loop.close()
    again = rig.open()
    _checked(again, ABSENT)
    with pytest.raises(RunStateError, match="runs only inside the OS layer"):
        again.resume()
    again.close()


def test_a_run_inside_the_layer_runs(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", "refuse")
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, PRESENT)
    assert loop.run().kind == "done"
    loop.close()
    assert _spawned(rig) == 1


def test_an_allowed_run_runs_without_the_layer_and_its_log_records_the_allowance(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path / "run", "allow")
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, ABSENT)
    assert loop.run().kind == "done"
    loop.close()
    assert _spawned(rig) == 1
    events = read_events(tmp_path / "run" / "events.jsonl")
    (line,) = [e for e in events if isinstance(e, OsLayerChecked)]
    assert isinstance(line.state, Absent) and line.absent_allowed is True


def test_the_layer_line_says_no_allowance_where_none_is_needed_or_given() -> None:
    allowed = make_config(os_layer_absent="allow")
    refused = make_config(os_layer_absent="refuse")
    assert cli._os_layer_checked(ENVELOPE, allowed, PRESENT).absent_allowed is None
    assert cli._os_layer_checked(ENVELOPE, refused, ABSENT).absent_allowed is False


def _recorded(tmp_path: Path, **overrides: object) -> bytes:
    """A run recorded with one subtask planned and nothing run yet; its log's bytes."""
    from physgate.orchestrator.record import RunRecord

    record = RunRecord(make_config(**overrides), tmp_path / "run")
    record.start(plan("power"))
    record.close()
    return (tmp_path / "run" / "events.jsonl").read_bytes()


def _through_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, layer: Present | Absent
) -> tuple[int, list[object]]:
    """``physgate run`` or ``resume`` on the recorded run, where the layer measures ``layer``.

    The layer is stubbed, so the measurement is this process's whatever the machine. A session
    the run would prepare or start is counted and stopped there, so none spawns.
    """
    from loop_fakes import FakeGate, FakeReviewer
    from test_the_physgate_command_starts_and_decides import (  # noqa: PLC0415
        _run_args,
        fake_binary,
    )

    from physgate.orchestrator.dispatch import ClaudeDispatcher

    spawned: list[object] = []

    def environment(_self: ClaudeDispatcher) -> object:
        spawned.append("environment")
        msg = "a role session's installation was being checked: a session was about to start"
        raise AssertionError(msg)

    def run(_self: ClaudeDispatcher, request: object, _on_spawn: object = None) -> object:
        spawned.append(request)
        msg = "a role session was started"
        raise AssertionError(msg)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: layer)
    monkeypatch.setattr(ClaudeDispatcher, "environment", environment)
    monkeypatch.setattr(ClaudeDispatcher, "run", run)
    registrations = cli.Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    return main([command, *_run_args(tmp_path)[1:]], registrations), spawned


@pytest.mark.parametrize("command", ["run", "resume"])
def test_the_command_refuses_a_run_whose_layer_is_absent_here_though_its_record_says_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    _recorded(tmp_path, os_layer_absent="refuse", os_layer=PRESENT)
    code, spawned = _through_the_command(tmp_path, monkeypatch, command, ABSENT)
    err = capsys.readouterr().err
    assert code == 2 and spawned == []
    assert "role sessions do not run without it" in err
    assert "runs only inside the OS layer" in json.loads(err.strip().splitlines()[-1])["error"]
    # The line records the layer this process measured, not the one the run recorded.
    events = read_events(tmp_path / "run" / "events.jsonl")
    (line,) = [e for e in events if isinstance(e, OsLayerChecked)]
    assert line.state == ABSENT and line.as_recorded is False and line.absent_allowed is False
    assert not (tmp_path / "run" / "sessions").exists()


@pytest.mark.parametrize("command", ["run", "resume"])
def test_the_command_refuses_a_reportable_run_whose_record_allows_the_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    # Written past the configuration's check, as only a hand on run.json could: the layer is
    # present here, so the evaluation's requirement is all that refuses it.
    monkeypatch.setattr(cli, "harness_state", lambda _root: CLEAN_HARNESS)
    events = _recorded(
        tmp_path,
        reportable=True,
        harness=CLEAN_HARNESS,
        os_layer_absent="allow",
        os_layer=PRESENT,
    )
    code, spawned = _through_the_command(tmp_path, monkeypatch, command, PRESENT)
    error = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert code == 2 and spawned == []
    assert error["error"] == "the run may not continue"
    requirements = error["requirements"]
    assert "a reportable run never allows role sessions without the OS layer" in requirements
    # Refused before anything is recorded.
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events
    assert not (tmp_path / "run" / "sessions").exists()


def test_the_allowance_never_lets_a_run_that_acts_on_decisions_run_without_the_layer(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path / "run", "allow")
    rig.config_overrides.update(queue_decisions="act", os_layer=PRESENT)
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, ABSENT)
    with pytest.raises(RunStateError, match="acts on queue decisions"):
        loop.run()
    loop.close()


# -- where a role session is made: the dispatcher and the installer -----------------------------


def _dispatched(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    layer: Present | Absent,
    seen: tuple[list[Path | None], list[str]] | None = None,
    **overrides: object,
) -> tuple[list[Path | None], list[str]]:
    """Dispatch one attempt where the layer measures ``layer``.

    Returns, and fills ``seen`` with, the temporary directory each started session was given and
    the subtasks whose worktree was opened. The session itself is stood in for at its start.
    """
    from types import SimpleNamespace

    from orch_helpers import SCRIPTED_BOUNDS

    from physgate.orchestrator import dispatch
    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.dispatch import ClaudeDispatcher
    from physgate.orchestrator.ports import SessionRequest

    config = make_config(**overrides)
    started, opened = seen if seen is not None else ([], [])

    def run_session(  # noqa: PLR0913 - the stood-in method's own parameters
        _self: object,
        _request: object,
        _worktree: Path,
        _sdir: Path,
        _session_id: str,
        _issued: object,
        temp: Path | None,
        **_kw: object,
    ) -> str:
        started.append(temp)
        return "started"

    def open_subtask(subtask_id: str) -> Path:
        opened.append(subtask_id)
        return run_dir / "worktrees" / subtask_id

    monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
    monkeypatch.setattr(dispatch, "empty_outbox", lambda *_a: ())
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: layer)
    monkeypatch.setattr(ClaudeDispatcher, "_run_session", run_session)
    dispatcher = ClaudeDispatcher(
        config=config,
        run=SimpleNamespace(open_subtask=open_subtask, run_dir=run_dir),  # type: ignore[arg-type]
        store_root=run_dir / "store",
        install_bin=run_dir / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=run_dir / "reviews",
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/power",
        model=config.models.roles["electrical"],
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    dispatcher.run(request)
    return started, opened


def test_the_dispatcher_spawns_no_role_session_without_the_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from physgate.orchestrator.exceptions import InvocationError

    started: list[Path | None] = []
    opened: list[str] = []
    with pytest.raises(InvocationError, match="runs only inside the OS layer") as refused:
        _dispatched(monkeypatch, tmp_path, ABSENT, (started, opened), os_layer_absent="refuse")
    assert refused.value.context == {"subtask_id": "s1"}
    # Refused before anything of the session exists: no worktree opened, no session started.
    assert started == [] and opened == []


def test_the_dispatcher_spawns_a_role_session_without_the_layer_where_the_run_allows_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started, opened = _dispatched(monkeypatch, tmp_path, ABSENT, os_layer_absent="allow")
    assert started == [None] and opened == ["s1"]


def test_the_dispatcher_never_spawns_without_the_layer_for_a_run_that_acts_on_decisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from physgate.orchestrator.exceptions import InvocationError

    with pytest.raises(InvocationError, match="acts on queue decisions"):
        _dispatched(
            monkeypatch,
            tmp_path,
            ABSENT,
            os_layer_absent="allow",
            queue_decisions="act",
            os_layer=PRESENT,
        )


def test_the_dispatcher_spawns_a_role_session_inside_the_layer_with_its_temporary_directory(
    monkeypatch: pytest.MonkeyPatch, outside_tmp: Path
) -> None:
    started, _ = _dispatched(monkeypatch, outside_tmp, PRESENT, os_layer_absent="refuse")
    (temp,) = started
    assert temp is not None and temp.name.startswith("pg-")


def _role_install(tmp_path: Path, *extra: str) -> list[str]:
    worktree = tmp_path / "wt"
    worktree.mkdir(exist_ok=True)
    return [
        *("hooks", "install", "--profile", "role", "--role", "electrical"),
        *("--worktree", str(worktree), "--state-dir", str(tmp_path / "state")),
        *("--target", str(tmp_path / "session"), "--claude-config-dir", str(tmp_path / "cfg")),
        *("--ceiling", "1000", *extra),
    ]


def _installer_error(capsys: pytest.CaptureFixture[str]) -> str:
    said: str = json.loads(capsys.readouterr().err.strip().splitlines()[-1])["error"]
    return said


@pytest.mark.parametrize(
    "temp", [[], ["--os-layer-temp", ""]], ids=["no-temporary-directory", "an-empty-one"]
)
def test_the_installer_writes_no_role_settings_without_the_sandbox(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], temp: list[str]
) -> None:
    """An empty temporary directory is none: the settings would carry no sandbox."""
    assert main(_role_install(tmp_path, *temp)) == 2
    said = _installer_error(capsys)
    assert "--os-layer-temp" in said and "os_layer_absent" in said
    assert not (tmp_path / "session").exists()


@pytest.mark.parametrize(
    ("overrides", "said"),
    [
        ({"os_layer_absent": "refuse"}, "runs only inside the OS layer"),
        (
            {"os_layer_absent": "allow", "queue_decisions": "act", "os_layer": PRESENT},
            "acts on queue decisions",
        ),
    ],
    ids=["a-run-that-refuses-the-absence", "a-run-that-acts-on-decisions"],
)
def test_the_installer_holds_the_run_s_recorded_configuration_to_the_one_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], overrides: dict[str, object], said: str
) -> None:
    write_run_config(tmp_path / "run.json", make_config(**overrides))
    assert main(_role_install(tmp_path, "--run-config", str(tmp_path / "run.json"))) == 2
    assert said in _installer_error(capsys)
    assert not (tmp_path / "session").exists()


def test_the_installer_writes_a_role_s_settings_without_the_sandbox_for_a_run_that_allows_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_run_config(tmp_path / "run.json", make_config(os_layer_absent="allow"))
    assert main(_role_install(tmp_path, "--run-config", str(tmp_path / "run.json"))) == 0
    settings = json.loads(Path(json.loads(capsys.readouterr().out)["settings"]).read_text())
    assert "sandbox" not in settings


def test_the_installer_writes_a_role_s_settings_with_the_sandbox_and_needs_no_run_configuration(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    temp = "/tmp/pg-0123456789ab"
    home = str(outside_tmp / "home")
    args = _role_install(
        outside_tmp, "--os-layer-temp", temp, "--spawns-with-canary", "--user-home", home
    )
    assert main(args) == 0
    settings = json.loads(Path(json.loads(capsys.readouterr().out)["settings"]).read_text())
    assert settings["sandbox"]


def test_a_run_configuration_that_cannot_be_read_lets_nothing_be_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing, torn, or no file at all (reading a directory fails as the system's error)."""
    (tmp_path / "torn.json").write_text('{"run_id": ')
    (tmp_path / "a-directory.json").mkdir()
    for path in (tmp_path / "none.json", tmp_path / "torn.json", tmp_path / "a-directory.json"):
        assert main(_role_install(tmp_path, "--run-config", str(path))) == 2
        assert "run configuration" in _installer_error(capsys)
    assert not (tmp_path / "session").exists()


def test_the_dispatcher_names_the_run_s_configuration_to_an_install_without_the_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_the_held_out_tier_and_the_network_reach_every_session import (  # noqa: PLC0415
        _install_argv,
        _values,
    )

    absent = _install_argv(tmp_path, monkeypatch, temp=None)
    assert _values(absent, "--run-config") == [str(tmp_path / "run" / "run.json")]
    inside = _install_argv(tmp_path, monkeypatch, temp=Path("/tmp/pg-0123456789ab"))
    assert "--run-config" not in inside


# -- never from the environment ---------------------------------------------------------------


@pytest.mark.parametrize("variable", ["OS_LAYER_ABSENT", "PHYSGATE_OS_LAYER_ABSENT"])
def test_an_allowance_in_the_environment_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
) -> None:
    monkeypatch.setenv(variable, "allow")
    # The one check, on a run that refuses and on one recorded before the flag existed.
    refusing = make_config(os_layer_absent="refuse", os_layer=PRESENT)
    assert os_layer_refusal(refusing, ABSENT) is not None
    assert os_layer_refusal(refusing, None) is not None
    write_run_config(tmp_path / "run.json", refusing)
    loaded = load_run_config(tmp_path / "run.json")
    assert loaded.os_layer_absent == "refuse" and loaded.sha256() == refusing.sha256()
    # A new run's configuration: refused where the layer is absent, and still required.
    assert main(_decompose(tmp_path / "a", monkeypatch, "refuse")) == 2
    assert "runs only inside the OS layer" in capsys.readouterr().err
    assert main(_decompose(tmp_path / "b", monkeypatch, None)) == 2
    assert json.loads(capsys.readouterr().err)["reason"].startswith("os_layer_absent")
    # Every run and resume: refused before any session.
    rig = _rig(tmp_path / "run", "refuse")
    loop = rig.open()
    loop.start(plan("power"))
    _checked(loop, ABSENT)
    with pytest.raises(RunStateError, match="runs only inside the OS layer"):
        loop.run()
    loop.close()
    assert _spawned(rig) == 0


@pytest.mark.parametrize("variable", ["OS_LAYER_ABSENT", "PHYSGATE_OS_LAYER_ABSENT"])
def test_a_refusal_in_the_environment_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "refuse")
    assert os_layer_refusal(make_config(os_layer_absent="allow"), ABSENT) is None


# -- the evaluation ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer", [ABSENT, PRESENT], ids=["absent", "present"])
def test_a_reportable_run_that_allows_the_absence_is_refused_whatever_the_layer(
    layer: Present | Absent,
) -> None:
    from physgate.evaluation.requirements import (
        REQUIREMENTS,
        no_os_layer_allowance_for_reportable_runs,
    )

    config = make_config(
        reportable=True, harness=CLEAN_HARNESS, os_layer_absent="allow", os_layer=layer
    )
    facts = RunFacts(config=config, os_layer=layer, shell_sessions=True)
    why = no_os_layer_allowance_for_reportable_runs(facts)
    assert why is not None and "os_layer_absent" in why
    assert no_os_layer_allowance_for_reportable_runs in REQUIREMENTS


def test_a_reportable_run_that_refuses_the_absence_is_not_held_to_it() -> None:
    from physgate.evaluation.requirements import no_os_layer_allowance_for_reportable_runs

    config = make_config(
        reportable=True, harness=CLEAN_HARNESS, os_layer_absent="refuse", os_layer=PRESENT
    )
    facts = RunFacts(config=config, os_layer=PRESENT, shell_sessions=True)
    assert no_os_layer_allowance_for_reportable_runs(facts) is None
