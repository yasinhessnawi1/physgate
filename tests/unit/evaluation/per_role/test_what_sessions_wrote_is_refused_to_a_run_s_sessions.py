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
