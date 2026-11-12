"""``hooks: off``: a role session without the design discipline, and with every protection kept.

An ablation run's arm measures what the harness's design discipline is worth, so a role session
under ``hooks: off`` drops exactly that discipline and nothing else:

- the hooks that hold it, unwired: required reading, the always-loaded ceiling and the checks on
  a proposal before it is written. Each is checked again where it counts: a proposal by the store
  and the change check at apply, the completion declaration and a dispute by the loop;
- the hooks' write protection of the worktree's own gate source, hook source and knowledge tree,
  which the file tools may then write. The live gate and hooks run from the harness checkout and
  the installation, which stay protected.

The arm switches off hooks, not the operating system's layer: the layer's rules are exactly a
full role session's, those three sources still denied to every shell command.

Every other root is kept exactly as a role session has it: the run's own records, the series
writer and its outbox, the harness checkout and installation, the held-out tier, the answer keys,
the graph store, the experiments rule, the session's settings, state, configuration and home. The
role's closed tool list and git rule are kept too, so the arm differs from the full harness in
its discipline alone. Only a role session is installed so.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

# A run's recorded configuration, as the installer reads it; the orchestrator's helpers build one.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from design_review_rig import outcome_of  # noqa: E402
from orch_helpers import CLEAN_HARNESS, make_config  # noqa: E402

from physgate.flags import Hooks
from physgate.hooks import graph, shell_startup
from physgate.hooks.config import ProtectedRoot, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, build_config, current_installation, install
from physgate.orchestrator.run_config import write_run_config

#: The session's own temporary directory, as the dispatcher makes one.
OWN_TEMP = "/var/tmp/pgs/0123456789"

#: The hooks that hold the design discipline, and the ones every role session keeps.
DROPPED_HOOKS = {"graph", "reading", "token_ceiling"}
KEPT_HOOKS = {"sentinel", "tools", "paths", "shell_paths", "git_ops", "os_abort", "survivors"}


def _fields(tmp: Path) -> dict[str, Any]:
    """A role session's request with every kind of root the dispatcher gives one."""
    worktree, outside, run = tmp / "worktree", tmp / "outside", tmp / "run"
    worktree.mkdir(parents=True, exist_ok=True)
    # The worktree's own sources and the harness's, present as in a real checkout: the OS layer
    # names a missing path inside the worktree only where its parent exists.
    for source in ("src/physgate/gate", "src/physgate/hooks", "knowledge"):
        (worktree / source).mkdir(parents=True, exist_ok=True)
    harness = tmp / "harness"
    (harness / "src").mkdir(parents=True, exist_ok=True)
    (harness / "experiments" / "R-OP-01").mkdir(parents=True, exist_ok=True)
    (harness / "experiments" / "R-OP-01" / "CRITERIA.md").write_text("frozen\n")
    (harness / "experiments" / "R-OP-01" / "RESULT.md").write_text("published\n")
    site = tmp / "site-packages"
    site.mkdir(exist_ok=True)
    return {
        "profile": "role",
        "role": "electrical",
        "worktree": str(worktree),
        "own_branch": "subtask/e1",
        "store_root": str(outside / "store"),
        "state_dir": str(outside / "state"),
        "target_dir": str(outside / "session"),
        "claude_config_dir": str(outside / "config"),
        "user_home": str(outside / "home"),
        "token_ceiling": 4000,
        "required_reading": (str(worktree / "spec.md"), str(run / "sessions" / "s" / "issued")),
        "always_loaded": (str(worktree / "knowledge" / "cross.md"),),
        "held_out": (str(tmp / "heldout"),),
        "answer_keys": (str(tmp / "answers"),),
        "extra_protected": (str(run / "decomposition"),),
        "extra_protected_record": (str(run / "events.jsonl"),),
        "extra_protected_refuse_only": (str(run / "sessions" / "s" / "stream"),),
        "sessions_root": str(run / "sessions"),
        "withheld": (str(run / "run.json"),),
        "harness_root": str(harness),
        "harness_site_packages": (str(site),),
        "shared_claude_temp": (str(tmp / "claude-shared"),),
        "session_temps": str(tmp / "temps"),
        "temp_dir": str(tmp / "temps" / "own"),
    }


def _config(tmp: Path, **overrides: Any) -> Any:  # noqa: ANN401 - a configuration, or why not
    return outcome_of(
        lambda: build_config(InstallRequest(**_fields(tmp) | overrides), current_installation())
    )


def _roots(config: SessionConfig) -> dict[str, ProtectedRoot]:
    return {root.path: root for root in config.protected_roots}


def _dropped(tmp: Path) -> set[str]:
    worktree = tmp / "worktree"
    return {
        str(worktree / "src" / "physgate" / "gate"),
        str(worktree / "src" / "physgate" / "hooks"),
        str(worktree / "knowledge"),
    }


def _kept(tmp: Path) -> dict[str, str]:
    """Every root a role session keeps under ``hooks: off``, by what it is."""
    worktree, outside, run = tmp / "worktree", tmp / "outside", tmp / "run"
    home, harness = outside / "home", tmp / "harness"
    installation = current_installation()
    kept = {
        "the series writer": worktree / ".physgate" / "lib",
        "the series outbox": worktree / ".physgate" / "series",
        "the secrets": worktree / ".env",
        "the worktree's Claude settings": worktree / ".claude",
        "the session's settings": outside / "session",
        "the hooks' state": outside / "state",
        "the session's Claude configuration": outside / "config",
        "the hook package": Path(installation.package_dir),
        "the hook environment": Path(installation.environment_root),
        "the hook interpreter's installation": Path(installation.base_prefix),
        "the user's Claude settings": home / ".claude" / "settings.json",
        "the user's Claude state": home / ".claude.json",
        "git's user configuration": home / ".gitconfig",
        "git's configuration directory": home / ".config" / "git",
        "the harness checkout": harness,
        "the harness source": harness / "src",
        "the harness library": harness / "knowledge",
        "the harness scripts": harness / "scripts",
        "the harness project file": harness / "pyproject.toml",
        "the harness lock file": harness / "uv.lock",
        "a frozen criteria file": harness / "experiments" / "R-OP-01" / "CRITERIA.md",
        "a published result": harness / "experiments" / "R-OP-01" / "RESULT.md",
        "the harness site-packages": tmp / "site-packages",
        "a run record": run / "decomposition",
        "a held run record": run / "events.jsonl",
        "a record the runtime writes": run / "sessions" / "s" / "stream",
        "every session's directory": run / "sessions",
        "the shared Claude temporary directory": tmp / "claude-shared",
        "every session's temporary directory": Path(os.path.realpath(tmp / "temps")),
        "the withheld run configuration": run / "run.json",
        "the held-out tier": tmp / "heldout",
        "the worktree's answer keys": worktree / "corpora",
        "an answer key": tmp / "answers",
        "the graph store": outside / "store",
    }
    kept |= {f"the shell startup file {name}": home / name for name in shell_startup.NAMES}
    return {what: str(path) for what, path in kept.items()}


def test_an_install_request_names_its_hooks_on_or_off() -> None:
    field = InstallRequest.model_fields.get("hooks")
    assert field is not None, "an install request does not say whether the discipline is on"
    assert set(field.annotation.__args__) == {"on", "off"}  # type: ignore[union-attr]


def test_off_drops_exactly_the_worktree_s_gate_hook_and_knowledge_roots(tmp_path: Path) -> None:
    on, off = _config(tmp_path, hooks="on"), _config(tmp_path, hooks="off")
    assert isinstance(on, SessionConfig), on
    assert isinstance(off, SessionConfig), off
    dropped = _dropped(tmp_path)
    assert dropped <= set(_roots(on))
    assert set(_roots(off)) == set(_roots(on)) - dropped


@pytest.mark.parametrize("what", sorted(_kept(Path("/k"))))
def test_off_keeps_each_other_root_exactly_as_a_role_session_has_it(
    tmp_path: Path, what: str
) -> None:
    path = _kept(tmp_path)[what]
    on, off = _config(tmp_path, hooks="on"), _config(tmp_path, hooks="off")
    assert isinstance(off, SessionConfig), off
    assert path in _roots(on), f"a role session does not protect {what}"
    assert _roots(off).get(path) == _roots(on)[path], f"hooks: off changed {what}"


def test_off_keeps_the_experiments_rule_and_what_only_reviewers_read(tmp_path: Path) -> None:
    on, off = _config(tmp_path, hooks="on"), _config(tmp_path, hooks="off")
    assert isinstance(off, SessionConfig), off
    assert off.experiments == on.experiments
    assert [rule.root for rule in off.experiments] == [str(tmp_path / "worktree" / "experiments")]
    assert (off.held_out, off.answer_keys, off.review_material) == (
        on.held_out,
        on.answer_keys,
        on.review_material,
    )
    assert str(tmp_path / "worktree" / "knowledge" / "reviewers") in off.review_material


def test_off_sets_no_required_reading_and_no_always_loaded_set(tmp_path: Path) -> None:
    on, off = _config(tmp_path, hooks="on"), _config(tmp_path, hooks="off")
    assert isinstance(off, SessionConfig), off
    assert on.required_reading and on.always_loaded
    assert (off.required_reading, off.always_loaded) == ((), ())


def test_what_a_session_is_given_to_read_in_its_own_directory_stays_readable(
    tmp_path: Path,
) -> None:
    # Integration's issued state lies beneath every session's directory: the session still reads
    # what it is given, though no hook requires it to.
    off = _config(tmp_path, hooks="off")
    assert isinstance(off, SessionConfig), off
    sessions = _roots(off)[str(tmp_path / "run" / "sessions")]
    assert sessions.read_exceptions == (str(tmp_path / "run" / "sessions" / "s" / "issued"),)


def test_off_keeps_a_role_s_profile_tools_and_ceiling(tmp_path: Path) -> None:
    on, off = _config(tmp_path, hooks="on"), _config(tmp_path, hooks="off")
    assert isinstance(off, SessionConfig), off
    assert (off.profile, off.role, off.tools_allowed, off.token_ceiling) == (
        on.profile,
        on.role,
        on.tools_allowed,
        on.token_ceiling,
    )


@pytest.mark.parametrize("profile", ["baseline", "reviewer", "orchestrator"])
def test_only_a_role_session_is_installed_with_hooks_off(tmp_path: Path, profile: str) -> None:
    fields: dict[str, Any] = {"profile": profile, "role": None}
    if profile == "reviewer":
        fields["read_roots"] = (str(tmp_path / "worktree"),)
    refused = _config(tmp_path, hooks="off", **fields)
    assert not isinstance(refused, SessionConfig), refused
    assert "only a role session is installed with hooks: off" in str(refused)
    assert isinstance(_config(tmp_path, hooks="on", **fields), SessionConfig)


def _install_request(tmp: Path, hooks: Hooks) -> Any:  # noqa: ANN401 - a request, or why not
    worktree = tmp / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    return outcome_of(
        lambda: InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(worktree),
            own_branch="subtask/e1",
            store_root=str(tmp / "store"),
            state_dir=str(tmp / "state"),
            target_dir=str(tmp / "session"),
            claude_config_dir=str(tmp / "claude-config"),
            user_home=str(tmp / "home"),
            token_ceiling=4000,
            sessions_root=str(tmp / "sessions"),
            temp_dir=OWN_TEMP,
            hooks=hooks,
        )
    )


def _wired(settings_path: Path) -> dict[str, set[str]]:
    settings = json.loads(settings_path.read_text())
    wired = {}
    for event, groups in settings["hooks"].items():
        argv = shlex.split(groups[0]["hooks"][0]["command"])
        wired[event] = set(argv[argv.index("--hooks") + 1].split(","))
    return wired


def test_off_wires_every_hook_but_the_discipline_s_three(tmp_path: Path) -> None:
    on_request, off_request = (
        _install_request(tmp_path / "on", "on"),
        _install_request(tmp_path / "off", "off"),
    )
    assert isinstance(on_request, InstallRequest), on_request
    assert isinstance(off_request, InstallRequest), off_request
    on = _wired(install(on_request, REGISTRY).settings_path)
    off = _wired(install(off_request, REGISTRY).settings_path)
    assert set().union(*on.values()) >= DROPPED_HOOKS
    assert not DROPPED_HOOKS & set().union(*off.values())
    assert set().union(*off.values()) >= KEPT_HOOKS
    # Event by event, exactly the three are gone; an event only they handled is not wired.
    assert off == {
        event: names - DROPPED_HOOKS for event, names in on.items() if names - DROPPED_HOOKS
    }


def _installer_args(root: Path, *more: str) -> argparse.Namespace:
    from physgate.hooks.cli import add_parser

    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    outside = root / "outside"
    (root / "worktree").mkdir(exist_ok=True)
    known = parser.parse_known_args(
        [
            "hooks",
            "install",
            "--profile",
            "role",
            "--worktree",
            "w",
            "--state-dir",
            "s",
            "--target",
            "t",
            "--claude-config-dir",
            "c",
            "--ceiling",
            "1",
            *more,
        ]
    )[1]
    assert known == [], f"the installer command does not take {known}"
    return parser.parse_args(
        [
            "hooks",
            "install",
            "--profile",
            "role",
            "--role",
            "electrical",
            "--worktree",
            str(root / "worktree"),
            "--state-dir",
            str(outside / "state"),
            "--target",
            str(outside / "session"),
            "--claude-config-dir",
            str(outside / "config"),
            "--user-home",
            str(outside / "home"),
            "--ceiling",
            "1000",
            "--sessions-root",
            str(outside / "sessions"),
            "--os-layer-temp",
            OWN_TEMP,
            "--spawns-with-canary",
            *more,
        ]
    )


def _recorded(root: Path, **fields: Any) -> Path:  # noqa: ANN401 - run parameters
    config = outcome_of(lambda: make_config(harness=CLEAN_HARNESS, **fields))
    assert not isinstance(config, Exception), config
    path = root / "run.json"
    write_run_config(path, config)
    return path


def test_the_installer_command_drops_the_discipline_for_a_run_that_recorded_hooks_off(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_json = _recorded(outside_tmp, hooks="off", ablation=True)
    args = _installer_args(outside_tmp, "--hooks", "off", "--run-config", str(run_json))
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert not DROPPED_HOOKS & set().union(*_wired(Path(printed["settings"])).values())


@pytest.mark.parametrize(
    ("asked", "recorded"),
    [("off", None), ("off", "on"), ("on", "off")],
    ids=["off with no record", "off where the run recorded on", "on where the run recorded off"],
)
def test_the_installer_command_refuses_hooks_the_run_did_not_record(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str], asked: str, recorded: str | None
) -> None:
    more = ["--hooks", asked]
    if recorded is not None:
        run_json = _recorded(outside_tmp, hooks=recorded, ablation=recorded == "off")
        more += ["--run-config", str(run_json)]
    args = _installer_args(outside_tmp, *more)
    assert args.func(args) == 2
    refusal = json.loads(capsys.readouterr().err)["error"]
    assert "hooks" in refusal
    assert not (outside_tmp / "outside" / "session" / "settings.json").exists()


def _installed_with_the_layer(root: Path, hooks: Hooks) -> dict[str, Any]:
    """The settings a role session of ``root`` is given with the OS layer, as written."""
    fields = _fields(root) | {"temp_dir": None, "os_layer_temp_dir": OWN_TEMP}
    fields |= {"session_temps": "/var/tmp/pgs", "spawns_with_canary": True, "hooks": hooks}
    request = outcome_of(lambda: InstallRequest(**fields))
    assert isinstance(request, InstallRequest), request
    settings: dict[str, Any] = json.loads(install(request, REGISTRY).settings_path.read_text())
    return settings


def test_the_os_layer_denies_exactly_what_it_denies_a_full_session(outside_tmp: Path) -> None:
    # The arm switches off hooks, not the operating system's layer: every write and read the
    # sandbox denies a full role session it denies this one, the worktree's own sources included.
    # Only the hook commands differ.
    on = _installed_with_the_layer(outside_tmp, "on")
    off = _installed_with_the_layer(outside_tmp, "off")
    assert "sandbox" in on
    assert json.dumps(off["sandbox"], sort_keys=True) == json.dumps(on["sandbox"], sort_keys=True)
    assert {k: v for k, v in off.items() if k != "hooks"} == {
        k: v for k, v in on.items() if k != "hooks"
    }
    deny_write = set(off["sandbox"]["filesystem"]["denyWrite"])
    worktree = outside_tmp / "worktree"
    # The knowledge tree is denied around its staging directory, entry by entry, as for a full
    # session; the equality above holds it. The two source trees are denied whole.
    assert {str(worktree / "src/physgate/gate"), str(worktree / "src/physgate/hooks")} <= deny_write
    for held in (graph.PROPOSALS_DIR, graph.COMPLETION_DIR, graph.DISPUTES_DIR):
        assert str(worktree / held) in deny_write, held


def test_the_harness_the_run_s_records_the_held_out_places_and_the_secrets_are_held_alike(
    outside_tmp: Path,
) -> None:
    """Under both layers: the hooks' roots and the OS layer's rules for each, identical."""
    on, off = _config(outside_tmp, hooks="on"), _config(outside_tmp, hooks="off")
    assert isinstance(off, SessionConfig), off
    kept = _kept(outside_tmp)
    named = [
        "the harness checkout",
        "a run record",
        "a held run record",
        "the withheld run configuration",
        "the held-out tier",
        "an answer key",
        "the worktree's answer keys",
        "the secrets",
    ]
    for what in named:
        assert _roots(off).get(kept[what]) == _roots(on)[kept[what]], what
    assert off.held_out == on.held_out
    sandbox_on = _installed_with_the_layer(outside_tmp, "on")["sandbox"]["filesystem"]
    sandbox_off = _installed_with_the_layer(outside_tmp, "off")["sandbox"]["filesystem"]
    for what in named:
        for rule in ("denyWrite", "denyRead"):
            assert (kept[what] in sandbox_off[rule]) == (kept[what] in sandbox_on[rule]), what
        assert kept[what] in sandbox_off["denyWrite"], what
