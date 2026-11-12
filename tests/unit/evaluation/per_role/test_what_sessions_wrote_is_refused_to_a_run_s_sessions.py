"""What sessions wrote lies under the withheld root, which every layer refuses to a run's sessions.

The authoring sessions' streams hold every task they wrote, the blind check's hold the
held-out tasks it was given, and the pool holds tasks that become held-out ones, none with a
canary. They lie under one root per role, and a run that names a tier of the store names that
root among the roots its sessions withhold. A role or baseline session of such a run is then
refused each of them by the file tool, by the shell, and by the OS layer's policy, as it is
refused a tier. (The OS layer itself is exercised on the real binary in CI's OS-layer job.)
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks import paths, shell_paths
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

VERSION = "a" * 64


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _config(base: Path, profile: str, held: tuple[Path, ...]) -> Any:  # noqa: ANN401
    for d in ("wt", "outside/state", "outside/session", "outside/config", "outside/home"):
        (base / d).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(base / "wt"),
        own_branch=None,
        store_root=None,
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=tuple(str(root) for root in held),
    )
    return build_config(request, current_installation())


def _written(store: Path) -> list[Path]:
    """A stream of each kind of session and a pooled task, where the store keeps them."""
    withheld_root = _api("physgate.evaluation.tiers.store.withheld_root")
    places = [
        _api("physgate.evaluation.tiers.store.author_evidence")(store, "control")
        / "s-1"
        / "stdout.jsonl",
        _api("physgate.evaluation.tiers.store.check_evidence")(store, "control")
        / "c-1"
        / "stdout.jsonl",
        _api("physgate.evaluation.tiers.store.pool_dir")(store, "control")
        / "control.t00"
        / "task.json",
    ]
    root = withheld_root(store, "control")
    for place in places:
        assert place.is_relative_to(root), f"{place} lies outside the withheld root {root}"
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text("what a session wrote")
    return places


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_run_s_session_is_refused_what_sessions_wrote_on_every_route(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    store = base / "private" / "store"
    version = store / "control" / VERSION
    written = _written(store)
    withheld = _api("physgate.evaluation.tiers.store.withheld_root")(store, "control")
    held = (version / "held_out", version / "validation", withheld)
    for tier in held[:2]:
        tier.mkdir(parents=True, exist_ok=True)
    config = _config(base, profile, held)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-wh")
    deny_read = policy.settings["sandbox"]["filesystem"]["denyRead"]
    wt = str(base / "wt")
    for place in written:
        target = str(place)
        where = place.relative_to(base)
        assert paths.protection(target, wt, config, writing=False), (
            f"a {profile} session's file tool may read {where}"
        )
        assert shell_paths.check(parse(f"cat {target}")[0], wt, config), (
            f"a {profile} session's shell may read {where}"
        )
        assert [d for d in deny_read if target.startswith(d.rstrip("/") + "/")], (
            f"a {profile} session's OS layer does not deny {where}"
        )


def test_the_version_s_visible_tier_lies_outside_the_withheld_root(tmp_path: Path) -> None:
    store = tmp_path.resolve() / "store"
    withheld = _api("physgate.evaluation.tiers.store.withheld_root")(store, "control")
    visible = _api("physgate.evaluation.tiers.store.version_dir")(store, "control", VERSION)
    assert not (visible / "visible").is_relative_to(withheld)


def _check_s_copy(store: Path) -> Path:
    """The held-out copy a blind check works on, where the store keeps the check's work."""
    work = Path(_api("physgate.evaluation.tiers.store.work_root")(store, "control"))
    copy = work / "check-0" / "worktree" / "tasks.json"
    copy.parent.mkdir(parents=True)
    copy.write_text("the held-out tasks a check was given")
    return copy


@pytest.mark.parametrize("named", ["the role's roots", "the store's parent"])
@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_run_s_session_is_refused_the_blind_check_s_work_on_every_route(
    tmp_path: Path, profile: str, named: str
) -> None:
    base = tmp_path.resolve()
    store = base / "private" / "store"
    version = store / "control" / VERSION
    for tier in ("held_out", "validation"):
        (version / tier).mkdir(parents=True)
    copy = _check_s_copy(store)
    if named == "the store's parent":
        held: tuple[Path, ...] = (store.parent,)
    else:
        held = (
            version / "held_out",
            version / "validation",
            _api("physgate.evaluation.tiers.store.withheld_root")(store, "control"),
            _api("physgate.evaluation.tiers.store.work_root")(store, "control"),
        )
    config = _config(base, profile, held)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-wk")
    deny_read = policy.settings["sandbox"]["filesystem"]["denyRead"]
    wt = str(base / "wt")
    target = str(copy)
    assert paths.protection(target, wt, config, writing=False), (
        f"{named}: a {profile} session's file tool may read the check's work"
    )
    assert shell_paths.check(parse(f"cat {target}")[0], wt, config), (
        f"{named}: a {profile} session's shell may read the check's work"
    )
    assert [d for d in deny_read if target.startswith(d.rstrip("/") + "/")], (
        f"{named}: a {profile} session's OS layer does not deny the check's work"
    )


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_check_s_session_is_refused_all_of_the_role_s_root_but_its_own_work(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    store = base / "private" / "store"
    version = store / "control" / VERSION
    for tier in ("visible", "held_out", "validation"):
        (version / tier).mkdir(parents=True)
    (version / "tierset.json").write_text("{}")
    _written(store)
    work = Path(_api("physgate.evaluation.tiers.store.work_root")(store, "control"))
    sibling = work / "check-other" / "worktree" / "tasks.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("another check's held-out copy")
    own = work / "check-own"
    (own / "worktree").mkdir(parents=True)
    try:
        held = tuple(_api("physgate.evaluation.tiers.store.check_roots")(store, "control", own))
    except TypeError as exc:
        pytest.fail(f"the check's roots are not given its own work: {exc}")
    config = _config(base, profile, held)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-ck")
    deny_read = policy.settings["sandbox"]["filesystem"]["denyRead"]
    wt = str(base / "wt")
    for place in (version / "tierset.json", version / "visible", sibling):
        target, where = str(place), place.relative_to(base)
        assert paths.protection(target, wt, config, writing=False), (
            f"a check's {profile} session's file tool may read {where}"
        )
        assert shell_paths.check(parse(f"cat {target}")[0], wt, config), (
            f"a check's {profile} session's shell may read {where}"
        )
        assert [d for d in deny_read if (target + "/").startswith(d.rstrip("/") + "/")], (
            f"a check's {profile} session's OS layer does not deny {where}"
        )
    own_task = str(own / "worktree" / "tasks.json")
    assert not paths.protection(own_task, wt, config, writing=False), "its own work is refused"


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_check_s_session_is_refused_every_other_role_s_root(tmp_path: Path, profile: str) -> None:
    base = tmp_path.resolve()
    store = base / "private" / "store"
    for role in ("control", "firmware"):
        for tier in ("visible", "held_out", "validation"):
            (store / role / VERSION / tier).mkdir(parents=True)
    other = store / "firmware" / "withheld" / "check" / "c-1" / "stdout.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("the held-out tasks another role's check was given")
    own = Path(_api("physgate.evaluation.tiers.store.work_root")(store, "control")) / "check-own"
    (own / "worktree").mkdir(parents=True)
    held = tuple(_api("physgate.evaluation.tiers.store.check_roots")(store, "control", own))
    config = _config(base, profile, held)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-ot")
    deny_read = policy.settings["sandbox"]["filesystem"]["denyRead"]
    wt = str(base / "wt")
    for place in (other, store / "firmware" / VERSION / "visible"):
        target, where = str(place), place.relative_to(base)
        assert paths.protection(target, wt, config, writing=False), (
            f"a control check's {profile} session's file tool may read {where}"
        )
        assert shell_paths.check(parse(f"cat {target}")[0], wt, config), (
            f"a control check's {profile} session's shell may read {where}"
        )
        assert [d for d in deny_read if (target + "/").startswith(d.rstrip("/") + "/")], (
            f"a control check's {profile} session's OS layer does not deny {where}"
        )


def test_the_check_s_roots_name_the_withheld_root_before_it_is_there(tmp_path: Path) -> None:
    store = tmp_path.resolve() / "store"
    (store / "control" / VERSION / "held_out").mkdir(parents=True)
    work_root = Path(_api("physgate.evaluation.tiers.store.work_root")(store, "control"))
    held = _api("physgate.evaluation.tiers.store.check_roots")(store, "control", work_root / "c")
    withheld = _api("physgate.evaluation.tiers.store.withheld_root")(store, "control")
    assert withheld in held, "a role's root with no withheld root yet leaves it out"
    assert store / "control" / VERSION in held


def test_a_role_s_root_is_made_with_its_withheld_and_work_roots(tmp_path: Path) -> None:
    make = _api("physgate.evaluation.tiers.store.make_role_root")
    root = tmp_path / "store" / "control"
    assert make(root) == root
    assert sorted(p.name for p in root.iterdir()) == ["withheld", "work"]
    for name in ("withheld", "work"):
        assert (root / name).is_dir() and not (root / name).is_symlink()
    (root / "withheld" / "pool").mkdir()
    make(root)
    assert (root / "withheld" / "pool").is_dir(), "making the role's root again changed it"


def _check_config(base: Path, profile: str, store: Path, own: Path) -> Any:  # noqa: ANN401
    """A check's session config as the check installs it: the store protected but ``own``."""
    held = tuple(_api("physgate.evaluation.tiers.store.check_roots")(store, "control", own))
    for d in ("outside/state", "outside/session", "outside/config", "outside/home"):
        (base / d).mkdir(parents=True, exist_ok=True)
    try:
        return build_config(_check_request(base, profile, own, held, store), current_installation())
    except ValueError as exc:
        pytest.fail(f"a check's session working inside the store cannot be installed: {exc}")


def _check_request(
    base: Path, profile: str, own: Path, held: tuple[Path, ...], store: Path
) -> InstallRequest:
    return InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(own / "worktree"),
        own_branch=None,
        store_root=None,
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=tuple(str(root) for root in held),
        extra_protected=(str(store),),
        extra_protected_exceptions=(str(own),),
    )


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_check_s_session_writes_nowhere_in_the_store_but_its_own_work(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    store = base / "private" / "store"
    for tier in ("visible", "held_out", "validation"):
        (store / "control" / VERSION / tier).mkdir(parents=True)
    (store / "firmware" / "withheld").mkdir(parents=True)
    own = Path(_api("physgate.evaluation.tiers.store.work_root")(store, "control")) / "check-own"
    (own / "worktree").mkdir(parents=True)
    config = _check_config(base, profile, store, own)
    wt = str(own / "worktree")
    for place in (
        store / "control" / "copy.json",
        store / "control" / "work" / "copy.json",
        store / "control" / "work" / "check-other" / "tasks.json",
        store / "copy.json",
        store / "firmware" / "copy.json",
    ):
        target, where = str(place), place.relative_to(store)
        assert paths.protection(target, wt, config, writing=True), (
            f"a check's {profile} session's file tool may write {where}"
        )
        assert shell_paths.check(parse(f"echo x > {target}")[0], wt, config), (
            f"a check's {profile} session's shell may write {where}"
        )
    for place in (own / "worktree" / "answers.json", own / "worktree" / "notes" / "n.txt"):
        assert not paths.protection(str(place), wt, config, writing=True), (
            f"a check's {profile} session may not write {place.relative_to(own)} in its own work"
        )
    assert not shell_paths.check(parse(f"echo x > {own / 'worktree' / 'a.txt'}")[0], wt, config)


def test_an_exception_beneath_no_protected_root_is_refused(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    for d in ("wt", "outside/state", "outside/session", "outside/config", "outside/home"):
        (base / d).mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="beneath no root"):
        request = InstallRequest(
            profile="baseline",
            role=None,
            worktree=str(base / "wt"),
            own_branch=None,
            store_root=None,
            state_dir=str(base / "outside" / "state"),
            target_dir=str(base / "outside" / "session"),
            claude_config_dir=str(base / "outside" / "config"),
            user_home=str(base / "outside" / "home"),
            token_ceiling=40960,
            extra_protected=(str(base / "store"),),
            extra_protected_exceptions=(str(base / "elsewhere"),),
        )
        build_config(request, current_installation())


def test_a_protected_root_holding_the_worktree_outside_its_exceptions_is_refused(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    store = base / "store"
    for d in ("store/work/own/worktree", "store/work/other", "outside/state", "outside/home"):
        (base / d).mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="contains the worktree"):
        request = InstallRequest(
            profile="baseline",
            role=None,
            worktree=str(store / "work" / "own" / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(base / "outside" / "state"),
            target_dir=str(base / "outside" / "session"),
            claude_config_dir=str(base / "outside" / "config"),
            user_home=str(base / "outside" / "home"),
            token_ceiling=40960,
            extra_protected=(str(store),),
            extra_protected_exceptions=(str(store / "work" / "other"),),
        )
        build_config(request, current_installation())


def test_the_install_command_carries_a_protected_root_s_exceptions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from physgate.hooks.cli import main

    base = tmp_path.resolve()
    store, own = base / "store", base / "store" / "control" / "work" / "check-own"
    (own / "worktree").mkdir(parents=True)
    argv = ["hooks", "install", "--profile", "baseline", "--worktree", str(own / "worktree")]
    argv += ["--state-dir", str(base / "state"), "--target", str(base / "session")]
    argv += ["--claude-config-dir", str(base / "config"), "--user-home", str(base / "home")]
    argv += ["--ceiling", "40960", "--protect", str(store), "--protect-except", str(own)]
    # What every baseline session is installed with: its own directory and its own temp.
    argv += ["--sessions-root", str(base / "session"), "--temp", "/var/tmp/pgs/0123456789"]
    try:
        assert main(argv) == 0
    except (SystemExit, ValueError) as exc:
        pytest.fail(f"the install command does not take a protected root's exception: {exc!r}")
    config = json.loads(Path(json.loads(capsys.readouterr().out)["config"]).read_text())
    (root,) = [r for r in config["protected_roots"] if r["path"] == str(store)]
    assert root["exceptions"] == [str(own)]


def test_a_session_s_installation_is_given_its_write_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses
    import json
    import subprocess

    from physgate.evaluation.per_role.arms import raw
    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.run_config import RunBounds
    from physgate.oslayer.probe import Absent

    given: list[list[str]] = []

    def installing(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        given.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({}), stderr="")

    monkeypatch.setattr(subprocess, "run", installing)
    setup = raw.RawSetup(
        binary="claude",
        claude_version="2.1.301",
        model="claude-sonnet-5",
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=10,
            infra_retry_delays_s=(),
        ),
        credential=Credential("api_key", "k"),
        base_url="http://127.0.0.1:9",
        install_bin=Path("/nonexistent"),
        role_python=None,
        held_out=(),
        held_out_canaries=(),
        network="none",
        os_layer=Absent(reason="a unit test"),
    )
    fields = {f.name for f in dataclasses.fields(setup)}
    assert {"write_protected", "writable_within"} <= fields, "a session cannot be write-protected"
    setup = dataclasses.replace(setup, write_protected=("/s/store",), writable_within=("/s/w",))
    raw._install(setup, tmp_path / "wt", tmp_path / "sdir", None)
    (argv,) = given
    pairs = list(zip(argv, argv[1:], strict=False))
    assert ("--protect", "/s/store") in pairs and ("--protect-except", "/s/w") in pairs
