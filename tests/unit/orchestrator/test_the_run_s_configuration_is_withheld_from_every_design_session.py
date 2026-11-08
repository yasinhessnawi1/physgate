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
    for command in (f"cat {run_json}", "grep canaries ../../run.json", "head -c 99 ../../run.json"):
        assert shell_paths.check(parse(command)[0], str(wt), config) is not None, command


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

    from physgate.orchestrator.decomposition_review import review_spawned

    monkeypatch.setattr(
        replan_rig, "PARAMS", {**replan_rig.PARAMS, "held_out_canaries": list(CANARIES)}
    )
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
