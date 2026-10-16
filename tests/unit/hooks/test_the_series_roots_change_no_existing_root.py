"""Adding the series outbox and the writer as roots changes no root that existed before them.

Three things are held. The protected-root table, for a request touching every kind of root,
equals the one the hook layer produced at this branch's starting point, entry for entry, once
the two new roots are set aside: same path, reason, watch class, exceptions and order (the
table at the branch point is committed beside this test). On and around every one of those
roots, the path layer and the shell layer decide exactly as they do without the new roots.
And the new roots are no wider than they say: nothing beside them is refused.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from roots_table import config, table

from physgate.hooks import shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import protection
from physgate.hooks.shell import parse

HERE = Path(__file__).parent
NEW = ("/.physgate/lib", "/.physgate/series")


def _without_new(cfg: SessionConfig) -> SessionConfig:
    kept = tuple(r for r in cfg.protected_roots if not r.path.endswith(NEW))
    return cfg.model_copy(update={"protected_roots": kept})


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path))


def test_every_root_that_existed_is_unchanged_and_only_two_are_added(base: Path) -> None:
    before = json.loads((HERE / "protected_roots_at_the_branch_point.json").read_text())
    now = table(base)
    added = [r for r in now if r not in before]
    assert sorted(str(r["path"]) for r in added) == [
        "<base>/run/worktrees/control-1/.physgate/lib",
        "<base>/run/worktrees/control-1/.physgate/series",
    ]
    assert [r for r in now if r in before] == before


def _probes(cfg: SessionConfig) -> list[str]:
    found = []
    for root in cfg.protected_roots:
        if root.path.endswith(NEW):
            continue
        path = root.path.rstrip("/")
        found += [
            path,
            path + "/inside.txt",
            path + "x",
            path + "_sibling/f",
            os.path.dirname(path) + "/./" + os.path.basename(path) + "//f",
            path.upper(),
        ]
    worktree = cfg.worktree
    found += [f"{worktree}/.physgate", f"{worktree}/.physgate/proposals/a.b.json"]
    return found


@pytest.mark.parametrize("writing", [True, False])
def test_the_path_layer_decides_every_existing_root_as_before(base: Path, writing: bool) -> None:
    cfg = config(base)
    old = _without_new(cfg)
    probes = _probes(cfg)
    assert len(probes) > 100
    for probe in probes:
        assert protection(probe, cfg.worktree, cfg, writing=writing) == protection(
            probe, cfg.worktree, old, writing=writing
        ), probe


def test_the_shell_layer_decides_every_existing_root_as_before(base: Path) -> None:
    cfg = config(base)
    old = _without_new(cfg)
    probes = _probes(cfg)
    for probe in probes:
        for command in (f"echo x > {probe}", f"cp a {probe}", f"cat {probe}", f"rm -rf {probe}"):
            for cmd in parse(command):
                assert shell_paths.check(cmd, cfg.worktree, cfg) == shell_paths.check(
                    cmd, cfg.worktree, old
                ), command


@pytest.mark.parametrize(
    "beside",
    [
        ".physgate",
        ".physgate/proposals/control.loop.json",
        ".physgate/specs/control-1.md",
        ".physgate/series_old/x.json",
        ".physgate/seriesx",
        ".physgate/library/x.py",
        ".physgate/li",
        "modules/control/series/x.json",
        "modules/control/lib/x.py",
    ],
)
def test_nothing_beside_the_new_roots_is_refused(base: Path, beside: str) -> None:
    cfg = config(base)
    path = os.path.join(cfg.worktree, beside)
    assert protection(path, cfg.worktree, cfg, writing=True) is None, beside
