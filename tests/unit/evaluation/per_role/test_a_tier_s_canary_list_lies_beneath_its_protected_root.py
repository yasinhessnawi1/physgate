"""A held-out tier's canary list lies beneath the root it protects, and is never seen half-written.

A canary a session can read tells it what not to print, which defeats the stream scan, the
only layer that detects a read. Every layer of the protection refuses what lies beneath a
held-out root and nothing beside one, so the split writes the list inside the tier: a role or
baseline session given that tier as its held-out root is refused the list by the file tool,
by the shell and by the OS layer, as it is refused a task.

The list is written under another name and given its own only once it is whole, and before
any task is written, so a look at the tier at any moment finds either no task or a whole list
beside them. The split reports the list's digest, apart from the tier's, which leaves the list
out.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.tiers.authoring import split
from physgate.evaluation.tiers.task import load_task
from physgate.hooks import paths, shell_paths
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

LIST_NAME = "canaries.json"


def _stage(root: Path, count: int = 16) -> Path:
    staging = root / "staging"
    for i in range(count):
        write_task_dir(
            staging / f"control.t{i:02d}",
            own_task(id=f"control.t{i:02d}"),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return staging


def _lists(base: Path) -> list[Path]:
    """Every file under ``base`` named as a canary list, in any case."""
    named = (LIST_NAME, f".{LIST_NAME}")
    return sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and (p.name.casefold() == named[0] or p.name.casefold().endswith(named[1]))
    )


def _held_canaries(tier: Path) -> list[str]:
    return sorted(str(load_task(p).task.canary) for p in sorted(tier.iterdir()) if p.is_dir())


def _config(base: Path, profile: str, held: Path) -> Any:  # noqa: ANN401
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
        held_out=(str(held),),
    )
    return build_config(request, current_installation())


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_session_is_refused_the_split_s_canary_list_on_every_route(
    tmp_path: Path, profile: str
) -> None:
    base = tmp_path.resolve()
    held = base / "private" / "heldout"
    split(_stage(base / "a"), base / "repo" / "visible", held, seed=3)
    found = _lists(base)
    assert found, "the split wrote no canary list"
    config = _config(base, profile, held)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-cl")
    deny_read = policy.settings["sandbox"]["filesystem"]["denyRead"]
    wt = str(base / "wt")
    for listed in found:
        target = str(listed)
        tool = paths.protection(target, wt, config, writing=False)
        shell = shell_paths.check(parse(f"cat {target}")[0], wt, config)
        denied = [d for d in deny_read if target == d or target.startswith(d.rstrip("/") + "/")]
        where = listed.relative_to(base)
        assert tool, f"a {profile} session's file tool may read the canary list at {where}"
        assert shell, f"a {profile} session's shell may read the canary list at {where}"
        assert denied, f"a {profile} session's OS layer does not deny the canary list at {where}"


def test_the_list_lies_inside_the_tier_and_names_exactly_its_canaries(tmp_path: Path) -> None:
    held = tmp_path / "private" / "heldout"
    out = split(_stage(tmp_path), tmp_path / "repo" / "visible", held, seed=3)
    assert _lists(tmp_path) == [held / LIST_NAME], (
        f"the split's canary lists are not exactly the one inside the tier: {_lists(tmp_path)}"
    )
    data = (held / LIST_NAME).read_bytes()
    assert sorted(json.loads(data)) == _held_canaries(held)
    assert out.get("held_out_canaries_sha256") == hashlib.sha256(data).hexdigest(), (
        "the split does not report the list's digest"
    )


def test_the_list_is_whole_before_it_has_its_name_and_before_any_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = tmp_path / "private" / "heldout"
    real_write = os.write
    seen: list[dict[str, Any]] = []

    def watching(fd: int, data: Any) -> int:  # noqa: ANN401
        if held.is_dir():
            seen.append(
                {
                    "data": bytes(data),
                    "named": _lists(held.parent),
                    "tasks": sorted(p.name for p in held.iterdir() if p.is_dir()),
                }
            )
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", watching)
    split(_stage(tmp_path), tmp_path / "repo" / "visible", held, seed=3)
    monkeypatch.undo()
    listed = _lists(held.parent)
    assert len(listed) == 1, f"the split did not write one canary list: {listed}"
    final = listed[0].read_bytes()
    writes = [s for s in seen if s["data"] == final]
    assert writes, "the list was not written in one piece"
    for write in writes:
        assert listed[0] not in write["named"], "the list had its own name before it was whole"
        assert write["tasks"] == [], (
            f"the list was written after {len(write['tasks'])} tasks were already in the tier"
        )
