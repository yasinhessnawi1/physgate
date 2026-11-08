"""The run's recorded configuration is withheld from every session that does design work.

``run.json`` records the held-out tier's canaries: the strings the stream scan looks for to
tell that a session read the held-out tier. A session that could read the list could read the
tier and print nothing the scan knows. A role session's worktree lies beneath the run
directory, so the file is two levels up from it.

So the dispatcher installs every role session with ``run.json`` withheld, and the hook layer
keeps a withheld path from every read: the file tools, a shell command, and the OS layer's
sandbox, for the role and the baseline profiles alike. Writes stay refused, and the file is
still put back if it changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_the_held_out_tier_and_the_network_reach_every_session import _install_argv, _values

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.orchestrator import dispatch
from physgate.oslayer.policy import sandbox_policy

CANARY = "cd" * 16
PROFILES = ("role", "baseline")


def _session(base: Path, profile: str) -> tuple[SessionConfig, Path, Path]:
    """A session of ``profile`` installed as the dispatcher installs one: its config, run.json."""
    wt = base / "run" / "worktrees" / "s1"
    wt.mkdir(parents=True)
    run_json = base / "run" / "run.json"
    run_json.write_text('{"held_out_canaries": ["' + CANARY + '"]}\n')
    for d in ("outside/state", "outside/session", "outside/config", "outside/home", "harness"):
        (base / d).mkdir(parents=True, exist_ok=True)
    held = base / "tiers" / "v1"
    held.mkdir(parents=True)
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(wt),
        own_branch=None,
        store_root=str(base / "run" / "store"),
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=(str(held),),
        extra_protected=(str(run_json),),
        withheld=(str(run_json),),
        harness_root=str(base / "harness"),
    )
    return build_config(request, current_installation()), wt, run_json


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_the_run_s_configuration_is_refused(base: Path, profile: str) -> None:
    config, wt, run_json = _session(base, profile)
    assert paths.protection(str(run_json), str(wt), config, writing=False) is not None
    assert paths.protection("../../run.json", str(wt), config, writing=False) is not None


@pytest.mark.parametrize("profile", PROFILES)
def test_a_shell_read_of_the_run_s_configuration_is_refused(base: Path, profile: str) -> None:
    config, wt, run_json = _session(base, profile)
    for command in (
        f"cat {run_json}",
        "grep canaries ../../run.json",
        "head -c 99 ../../run.json",
        # An interpreter's program, which the shell's parser takes as text: named is enough.
        "python3 -c \"print(open('../../run.json').read())\"",
    ):
        assert shell_paths.check(parse(command)[0], str(wt), config) is not None, command


@pytest.mark.parametrize("profile", PROFILES)
def test_a_command_fed_the_record_s_path_as_text_is_refused_as_for_the_held_out_tier(
    base: Path, profile: str
) -> None:
    # A program's input that only names the record: as for the held-out tier, naming is enough.
    config, wt, _ = _session(base, profile)
    assert shell_paths.check(parse('cat <<< "../../run.json"')[0], str(wt), config) is not None


@pytest.mark.parametrize("profile", PROFILES)
def test_the_os_layer_denies_every_read_of_the_run_s_configuration(
    base: Path, profile: str
) -> None:
    config, _, run_json = _session(base, profile)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-wh")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    assert any(str(run_json) == d or str(run_json).startswith(d.rstrip("/") + "/") for d in deny), (
        deny
    )


def test_every_role_session_is_installed_with_the_run_s_configuration_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = [str(tmp_path / "run" / "run.json"), str(tmp_path / "run" / "decomposition")]
    for temp in (None, Path("/tmp/pg-0123456789ab")):
        argv = _install_argv(tmp_path, monkeypatch, temp=temp)
        assert _values(argv, "--withheld") == named, argv


#: Two canaries, as a run with a held-out tier records them.
CANARIES = ("ab" * 16, "ef" * 16)


def test_no_file_the_run_writes_that_a_role_session_could_read_holds_a_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The run's places as the loop writes them: its configuration and its decomposition, with a
    # plan review; then the record a running review leaves when its command is killed.
    import replan_rig
    from replan_rig import Step, decompose
    from test_the_physgate_command_starts_and_decides import PARAMS

    from physgate.orchestrator.decomposition_review import review_spawned

    monkeypatch.setattr(replan_rig, "PARAMS", {**PARAMS, "held_out_canaries": list(CANARIES)})
    ran = decompose(tmp_path, "on", [Step(review="pass")])
    assert ran.code == 0, ran.err
    review_spawned(ran.run_dir, canaries=CANARIES)("review-1", 1, "2026-11-08T00:00:00Z")
    # What the dispatcher withholds (the rows above hold it to the install it builds), and the
    # parameters file the run was started with, wherever it lies.
    withheld = _withheld(ran.run_dir)
    params = (tmp_path / "params.json").resolve()
    holding = sorted(
        path
        for path in (*ran.run_dir.rglob("*"), params)
        if path.is_file()
        and not path.is_symlink()
        and any(c.encode() in path.read_bytes() for c in CANARIES)
    )
    names = {
        path.name if path == params else path.relative_to(ran.run_dir).as_posix()
        for path in holding
    }
    # Not vacuous: every record that names the canaries is found.
    assert {"run.json", "decomposition/review_session.json", "params.json"} <= names, names
    readable = [p for p in holding if not any(p == w or w in p.parents for w in withheld)]
    assert readable == [], readable


#: The held-out stand-in's bytes: nothing else in the tree holds them.
HELD_BYTES = b"held-out stand-in 0d9e4c21, scenario one\n"


def test_no_file_a_role_session_could_read_after_one_session_holds_a_canary_or_a_held_out_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sweep above runs before any session: here one session is installed as the dispatcher
    # installs it, with a held-out stand-in, and its hooks run their first calls. Its hook state
    # directory then exists, under the run directory, with what the sentinel kept.
    import contextlib
    import io
    import subprocess

    import replan_rig
    from replan_rig import Step, decompose
    from test_the_physgate_command_starts_and_decides import PARAMS

    from physgate.hooks import cli as hooks_cli
    from physgate.hooks import sentinel
    from physgate.hooks.config import HookInput
    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.decomposition_review import review_spawned
    from physgate.orchestrator.merge import RunGit
    from physgate.orchestrator.ports import SessionRequest
    from physgate.orchestrator.run_config import load_run_config

    held = tmp_path.resolve() / "tiers" / "v1"
    held.mkdir(parents=True)
    (held / "scenario.json").write_bytes(HELD_BYTES)
    monkeypatch.setattr(
        replan_rig,
        "PARAMS",
        {
            **PARAMS,
            "held_out": [str(held)],
            "held_out_canaries": list(CANARIES),
            "held_out_sha256": ["0" * 64],
        },
    )
    ran = decompose(tmp_path, "on", [Step(review="pass")])
    assert ran.code == 0, ran.err
    run_dir = ran.run_dir.resolve()
    review_spawned(run_dir, canaries=CANARIES)("review-1", 1, "2026-11-08T00:00:00Z")

    real_run = subprocess.run

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        # The installer is run in this process, as the command line would run it.
        if list(argv[1:3]) == ["hooks", "install"]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hooks_cli.main(argv[1:])
            return subprocess.CompletedProcess(argv, code, out.getvalue(), "")
        return real_run(argv, **kw)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    cfg = load_run_config(run_dir / "run.json")
    assert cfg.held_out == (str(held),)
    dispatcher = dispatch.ClaudeDispatcher(
        config=cfg,
        run=RunGit(repo=tmp_path / "target", run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )
    # The interface contracts the session would also read are no part of this sweep.
    monkeypatch.setattr(dispatcher, "_contracts", lambda _request: ())
    worktree = run_dir / "worktrees" / "s1"
    worktree.mkdir(parents=True)
    sid = "7d0c5e1a-3b2f-4c6d-8e9f-0a1b2c3d4e5f"
    sdir = run_dir / "sessions" / sid
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=cfg.bounds,
    )
    installed = dispatcher._install(request, worktree, sdir, None)
    config = SessionConfig.model_validate_json(Path(installed.config).read_bytes())
    for event in ("SessionStart", "PreToolUse", "PostToolUse"):
        hook_input = HookInput.model_validate(
            {
                "session_id": sid,
                "cwd": str(worktree),
                "hook_event_name": event,
                "tool_name": "Read",
                "tool_input": {"file_path": str(worktree / "notes.md")},
            }
        )
        assert sentinel.check(hook_input, config).allow, event
    state = Path(config.state_dir)
    assert any(p.name.startswith("pack-") for p in state.rglob("*")), "the session kept nothing"

    params = (tmp_path / "params.json").resolve()
    secrets = (*(c.encode() for c in CANARIES), HELD_BYTES)
    holding = sorted(
        path
        for path in (*run_dir.rglob("*"), params, *held.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and any(secret in path.read_bytes() for secret in secrets)
    )
    names = {path.name for path in holding}
    # Not vacuous: the records that name the canaries, and the tier itself, are found.
    assert {"run.json", "review_session.json", "params.json", "scenario.json"} <= names, names
    deny = sandbox_policy(config, home=str(sdir / "home"), temp_dir="/tmp/pg-sweep").settings[
        "sandbox"
    ]["filesystem"]["denyRead"]
    for path in holding:
        assert paths.protection(str(path), str(worktree), config, writing=False) is not None, path
        command = parse(f"cat {path}")[0]
        assert shell_paths.check(command, str(worktree), config) is not None, path
        assert any(str(path) == d or str(path).startswith(d.rstrip("/") + "/") for d in deny), path


def _withheld(run_dir: Path) -> list[Path]:
    """What the dispatcher withholds from a role session of the run in ``run_dir``."""
    named = getattr(dispatch, "withheld_paths", None)
    if named is None:  # before the dispatcher named them in one place
        return [run_dir / name for name in getattr(dispatch, "WITHHELD_RECORDS", ())]
    return [Path(p) for p in named(run_dir)]


def test_decompose_records_the_parameters_file_it_was_started_with(tmp_path: Path) -> None:
    from replan_rig import Step, decompose

    ran = decompose(tmp_path, "off", [Step()])
    assert ran.code == 0, ran.err
    record = ran.run_dir / "params_source.json"
    assert record.is_file(), sorted(p.name for p in ran.run_dir.iterdir())
    assert json.loads(record.read_text()) == {"params": str((tmp_path / "params.json").resolve())}


def test_every_role_session_is_installed_with_the_run_s_parameters_file_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    params = tmp_path / "elsewhere" / "params-9.json"
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "params_source.json").write_text(json.dumps({"params": str(params)}))
    argv = _install_argv(tmp_path, monkeypatch, temp=None)
    assert str(params) in _values(argv, "--withheld"), argv


def test_a_parameters_record_that_cannot_be_read_installs_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from design_review_rig import outcome_of

    from physgate.orchestrator.exceptions import InvocationError

    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "params_source.json").write_text("{not json")
    got = outcome_of(lambda: _install_argv(tmp_path, monkeypatch, temp=None))
    assert isinstance(got, InvocationError), got
