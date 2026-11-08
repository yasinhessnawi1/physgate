"""A withheld run record is held by every part of the hook layer, from the command to the tripwire.

The installer command takes ``--withheld`` into the session's configuration, where the record is
a protected root refused to every read; the tripwire on the files no session reads holds it to one
name and to the file it was; and a write stays refused.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import paths, sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

CANARY = "cd" * 16
#: What the refusal of a withheld record says it is: the words a session is told.
WITHHELD = "the stream scan looks for"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "run" / "worktrees" / "s1").mkdir(parents=True)
    (tmp_path / "run" / "run.json").write_text('{"held_out_canaries": ["' + CANARY + '"]}\n')
    return tmp_path


def _config(root: Path) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(root / "run" / "worktrees" / "s1"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            extra_protected=(str(root / "run" / "run.json"),),
            withheld=(str(root / "run" / "run.json"),),
        ),
        installation(),
    )


def test_the_installer_command_withholds_the_record_it_is_told(
    outside_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.hooks.cli import add_parser

    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    outside = outside_tmp / "outside"
    (outside_tmp / "worktree").mkdir()
    record = outside_tmp / "run.json"
    record.write_text("{}\n")
    args = parser.parse_args(
        [
            *("hooks", "install", "--profile", "baseline"),
            *("--worktree", str(outside_tmp / "worktree")),
            *("--state-dir", str(outside / "state"), "--target", str(outside / "session")),
            *("--claude-config-dir", str(outside / "config"), "--user-home", str(outside / "home")),
            *("--ceiling", "1000", "--withheld", str(record)),
        ]
    )
    assert args.func(args) == 0
    config = json.loads(Path(json.loads(capsys.readouterr().out)["config"]).read_text())
    roots = [r for r in config["protected_roots"] if r["path"] == str(record.resolve())]
    assert [(r["reads"], r["watch"]) for r in roots] == [("denied", "revert")]
    assert WITHHELD in roots[0]["reason"]


def test_a_withheld_record_named_as_an_ordinary_root_too_is_still_withheld(root: Path) -> None:
    config = _config(root)
    (found,) = [r for r in config.protected_roots if r.path == str(root / "run" / "run.json")]
    assert found.reads == "denied"
    assert WITHHELD in found.reason


def test_a_write_of_a_withheld_record_stays_refused(root: Path) -> None:
    config = _config(root)
    record = str(root / "run" / "run.json")
    said = paths.protection(record, config.worktree, config, writing=True)
    assert said is not None
    assert WITHHELD in said


def test_the_tripwire_holds_a_withheld_record_to_one_name(root: Path) -> None:
    def check(name: str) -> str:
        hook_input = HookInput.model_validate(
            bash("x", cwd=str(root / "run" / "worktrees" / "s1")) | {"hook_event_name": name}
        )
        decision = sentinel.check(hook_input, _config(root))
        return "allow" if decision.allow else decision.reason

    assert check("SessionStart") == "allow"
    os.link(root / "run" / "run.json", root / "run" / "worktrees" / "s1" / "copy.json")
    reason = check("SessionEnd")
    assert "more than one name" in reason and "run.json" in reason


def test_the_check_before_a_commit_names_a_withheld_record_with_a_second_name(root: Path) -> None:
    # The dispatcher's last check, after the session's own end check: a second name made in
    # that window is named before the attempt is committed.
    from physgate.orchestrator.dispatch import withheld_before_commit

    config = _config(root)
    path = root / "outside" / "session-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json())
    assert withheld_before_commit(path) is None
    os.link(root / "run" / "run.json", root / "second-name.json")
    found = withheld_before_commit(path)
    assert found is not None
    assert "run.json: has more than one name (2)" in found


def test_the_parameters_record_is_put_back_like_the_run_s_configuration(tmp_path: Path) -> None:
    import subprocess

    from physgate.orchestrator.dispatch import run_protected_roots
    from physgate.orchestrator.merge import RunGit

    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        env={"PATH": "/usr/bin:/bin", "HOME": os.devnull},
        check=True,
        capture_output=True,
    )
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="run-1")
    reverted, refused = run_protected_roots(run)
    # It names the file every session is installed with withheld: a session that rewrote it would
    # make the next session withhold another file, so the sentinel puts it back.
    assert tmp_path / "run" / "params_source.json" in reverted
    assert tmp_path / "run" / "run.json" in reverted
    assert tmp_path / "run" / "params_source.json" not in refused
