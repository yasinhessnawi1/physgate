"""The raw agent's session (profile ``baseline``): the evaluation's two protections, kept.

The arm the harness is measured against keeps what guards the evaluation itself, the
held-out tier and the frozen experiments, and the roots without which a session could
undo those two (its settings, its records, its configuration, the hook code). It keeps
none of the harness's discipline over a design worktree, and it has a role's tools.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from physgate.hooks.reasons import HELD_OUT_REASON
from physgate.hooks.settings import PROFILE_TOOLS, InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation


def _request(tmp_path: Path, profile: str) -> InstallRequest:
    outside = tmp_path / "outside"
    return InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(tmp_path / "worktree"),
        own_branch=None,
        store_root=None,
        state_dir=str(outside / "state"),
        target_dir=str(outside / "session"),
        claude_config_dir=str(outside / "config"),
        user_home=str(outside / "home"),
        token_ceiling=1000,
        held_out=(str(tmp_path / "heldout"),),
    )


def test_the_raw_agent_keeps_held_out_experiments_and_its_own_integrity(tmp_path: Path) -> None:
    config = build_config(_request(tmp_path, "baseline"), installation())
    roots = {root.path: root for root in config.protected_roots}
    held = roots[str(tmp_path / "heldout")]
    assert (held.reason, held.reads, held.watch) == (HELD_OUT_REASON, "denied", "revert")
    assert [rule.root for rule in config.experiments] == [str(tmp_path / "worktree/experiments")]
    outside = tmp_path / "outside"
    for integrity in ("session", "state", "config"):
        assert str(outside / integrity) in roots
    for code in (config.installation.package_dir, config.installation.environment_root):
        assert roots[code].watch == "halt"
    assert str(tmp_path / "worktree" / ".claude") in roots


def test_the_raw_agent_is_held_to_none_of_the_harness_s_design_discipline(tmp_path: Path) -> None:
    role = {
        r.path for r in build_config(_request(tmp_path, "role"), installation()).protected_roots
    }
    raw = {
        r.path for r in build_config(_request(tmp_path, "baseline"), installation()).protected_roots
    }
    worktree = tmp_path / "worktree"
    discipline = {
        str(worktree / "src/physgate/gate"),
        str(worktree / "src/physgate/hooks"),
        str(worktree / "knowledge"),
        str(worktree / ".physgate/lib"),
        str(worktree / ".physgate/series"),
    }
    git_config = {
        str(tmp_path / "outside/home/.gitconfig"),
        str(tmp_path / "outside/home/.config/git"),
    }
    assert discipline <= role and not discipline & raw
    assert git_config <= role and not git_config & raw
    assert raw == role - discipline - git_config


def test_the_raw_agent_has_exactly_a_role_s_tools() -> None:
    assert PROFILE_TOOLS["baseline"] == PROFILE_TOOLS["role"]


def test_the_installer_command_takes_the_raw_agent_offline(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from physgate.hooks.cli import add_parser

    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    outside = outside_tmp / "outside"
    (outside_tmp / "worktree").mkdir()
    args = parser.parse_args(
        [
            "hooks",
            "install",
            "--profile",
            "baseline",
            "--worktree",
            str(outside_tmp / "worktree"),
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
            "--held-out",
            str(outside_tmp / "heldout"),
            "--os-layer-temp",
            "/tmp/pg-0123456789ab",
            "--os-layer-network",
            "none",
            # Spawned with its pid exported as the survivor reaper's canary (macOS).
            "--spawns-with-canary",
        ]
    )
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    settings = json.loads(Path(printed["settings"]).read_text())
    config = json.loads(Path(printed["config"]).read_text())
    assert config["profile"] == "baseline"
    assert settings["sandbox"]["network"]["strictAllowlist"] is True


def test_offline_asked_for_without_the_os_layer_is_said_never_silently_dropped(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the OS layer can take a shell offline: without it the install says so, twice."""
    import json

    from physgate.hooks.cli import add_parser
    from physgate.oslayer.policy import NETWORK_UNENFORCED

    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    outside = outside_tmp / "outside"
    (outside_tmp / "worktree").mkdir()
    common = [
        *("hooks", "install", "--profile", "baseline", "--worktree", str(outside_tmp / "worktree")),
        *("--state-dir", str(outside / "state"), "--target", str(outside / "session")),
        *("--claude-config-dir", str(outside / "config"), "--user-home", str(outside / "home")),
        *("--ceiling", "1000", "--os-layer-network", "none"),
    ]
    args = parser.parse_args(common)
    assert args.func(args) == 0
    said = capsys.readouterr()
    printed = json.loads(said.out)
    assert printed["network_unenforced"].startswith(NETWORK_UNENFORCED)
    assert NETWORK_UNENFORCED in said.err
    assert "sandbox" not in json.loads(Path(printed["settings"]).read_text())
    # With the layer, nothing is said: the printed record is exactly what dispatch reads.
    args = parser.parse_args(
        [*common, "--os-layer-temp", "/tmp/pg-0123456789ab", "--spawns-with-canary"]
    )
    assert args.func(args) == 0
    said = capsys.readouterr()
    assert "network_unenforced" not in json.loads(said.out) and not said.err
