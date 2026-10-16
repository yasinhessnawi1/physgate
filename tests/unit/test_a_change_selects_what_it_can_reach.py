"""``scripts/affected.py``: what a change can reach, for the fast loop and the UI gate.

The check script skips the operator UI's gate on this script's word, so a wrong "no" is a gate
that did not run. Every case here that expects a "no" is paired with a near one that must say
yes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import affected
import pytest

HOOK_TEST = "tests/unit/hooks/test_the_shell_splitter_finds_commands_not_text.py"
POWER_TEST = "tests/unit/gate/test_check_4_refuses_a_supply_its_consumers_exceed.py"


def test_a_changed_module_selects_the_tests_whose_imports_reach_it() -> None:
    picked = affected.tests_for(["src/physgate/gate/check_power.py"])
    assert picked is not None
    assert POWER_TEST in picked
    assert HOOK_TEST not in picked


def test_a_change_reaches_through_a_chain_of_imports() -> None:
    # The shell splitter's test imports the shell module, which imports the hooks' exceptions.
    picked = affected.tests_for(["src/physgate/hooks/exceptions.py"])
    assert picked is not None
    assert HOOK_TEST in picked


def test_a_test_tree_helper_selects_the_tests_that_import_it_by_its_bare_name() -> None:
    picked = affected.tests_for(["tests/unit/hooks/hook_helpers.py"])
    assert picked is not None
    assert "tests/unit/hooks/test_a_reviewer_reads_only_beneath_its_allowance.py" in picked
    assert POWER_TEST not in picked


def test_a_changed_test_selects_itself() -> None:
    assert affected.tests_for([HOOK_TEST]) == [HOOK_TEST]


def test_a_file_that_is_not_python_selects_the_tests_that_name_its_directory() -> None:
    picked = affected.tests_for(["experiments/R-OP-01/README.md"])
    assert picked is not None
    assert "tests/test_frozen_tree_fence.py" in picked


@pytest.mark.parametrize(
    "changed",
    [
        "tests/conftest.py",
        "tests/harness_pin.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "scripts/affected.py",
        "src/physgate/gate/a_module_that_was_deleted.py",
    ],
)
def test_shared_fixtures_the_environment_or_a_deleted_module_select_everything(
    changed: str,
) -> None:
    assert affected.tests_for([HOOK_TEST, changed]) is None


@pytest.mark.parametrize(
    "changed",
    [
        "tests/unit/ui/test_every_response_forbids_storing_it.py",
        "tests/integration/hooks/anything.py",
        "experiments/R-OP-01/README.md",
        "desktop/src-tauri/src/main.rs",
        "src/physgate/roles/role.py",
    ],
)
def test_the_ui_gate_is_skipped_only_for_a_change_that_cannot_reach_it(changed: str) -> None:
    assert affected.ui_affected([changed]) is None


@pytest.mark.parametrize(
    "changed",
    [
        "ui/src/main.tsx",
        "src/physgate/ui/server.py",
        "src/physgate/state/store.py",
        "src/physgate/cli.py",
        "tests/ui_rig.py",
        "scripts/check-ui.sh",
        "scripts/affected.py",
        "pyproject.toml",
        "knowledge/README.md",
        "a-new-top-level-file",
    ],
)
def test_the_ui_gate_runs_for_a_change_that_can_reach_it(changed: str) -> None:
    reason = affected.ui_affected(["src/physgate/roles/role.py", changed])
    assert reason is not None
    assert changed in reason


def test_a_failure_to_read_the_change_runs_the_ui_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> list[str]:
        msg = "no base"
        raise affected.AffectedError(msg)

    monkeypatch.setattr(affected, "changed_files", broken)
    assert affected.main(["ui"]) == 0
    assert affected.main(["tests"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "tests"


def test_skip_has_an_exit_code_no_crash_can_give() -> None:
    assert affected.NOT_AFFECTED not in {0, 1, 2}


def _git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *identity, "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return done.stdout


def test_the_change_is_committed_uncommitted_and_untracked_files_since_the_merge_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    for name in ("kept", "edited", "committed"):
        (repo / name).write_text("0\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "switch", "-q", "-c", "work")
    (repo / "committed").write_text("1\n")
    _git(repo, "commit", "-q", "-am", "work")
    (repo / "edited").write_text("1\n")
    (repo / "untracked").write_text("1\n")
    monkeypatch.setattr(affected, "REPO", repo)
    monkeypatch.setenv("PHYSGATE_CHECK_BASE", "master")
    monkeypatch.setenv("HOME", os.devnull)
    assert affected.changed_files() == ["committed", "edited", "untracked"]
