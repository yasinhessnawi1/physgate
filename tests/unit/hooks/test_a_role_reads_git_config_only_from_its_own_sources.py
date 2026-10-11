"""A role session may read git's configuration from the repository's own sources, and nothing else.

The ``git config`` forms a role may run are an allowlist matched word by word. Every row
here is only parsed by the hook and decided; no git runs and nothing is configured.

Each refused row is a form git accepts that writes configuration, opens an editor on it,
reads it from a file, blob or repository the command names, or moves the user
configuration file; or a spelling of an admitted form (an abbreviation, a cluster, a
repeated option, a ``--``) that the allowlist does not read and so refuses. The admitted
rows are the read forms that must stay open.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, write_config

from physgate.hooks import git_ops
from physgate.hooks.config import HookInput

G = git_ops
WRITE = G.ROLE_CONFIG_WRITE
SOURCE = G.ROLE_CONFIG_SOURCE


def _decide(tmp: Path, command: str, profile: str = "role") -> str:
    worktree = tmp / "worktree"
    (worktree / ".git").mkdir(parents=True, exist_ok=True)
    (worktree / ".git" / "HEAD").write_text("ref: refs/heads/subtask/electrical-1\n")
    _, _, config = write_config(tmp, profile=profile)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=str(worktree))), config
    )
    return "allow" if decision.allow else decision.reason


#: Forms that set, remove, rename or open an editor on configuration: refused as writes.
WRITES = [
    # The subcommand syntax: every subcommand but ``list`` and ``get``.
    "git config set a.b c",
    "git config set --global a.b c",
    "git config set --append a.b c",
    "git config set --comment=x a.b c",
    "git config unset a.b",
    "git config unset --all a.b",
    "git config rename-section a b",
    "git config remove-section a",
    "git config edit",
    "git config edit --global",
    "git config edit --local",
    "git config --global edit",
    "git config -- edit",
    "git --attr-source HEAD config edit",
    # The older action syntax.
    "git config a.b c",
    "git config --add a.b c",
    "git config --replace-all a.b c",
    "git config --unset a.b",
    "git config --unset-all a.b",
    "git config --rename-section a b",
    "git config --remove-section a",
    "git config -e",
    "git config --edit",
    "git config --global --edit",
    "git config --comment=x a.b c",
    # A write beside a read action: the read flag no longer carries the command.
    "git config --get --edit",
    "git config --list --add a.b c",
    "git config --get --unset a.b",
    "git config -l -e",
    "git config --list -e",
    # A write sent to a named file is a write first.
    "git config --file custom a.b c",
    "git -C sub config user.name me",
    # Nothing to read.
    "git config",
]

#: Spellings of read forms that the allowlist does not read: refused, whatever git makes of them.
SPELLINGS = [
    # Abbreviations git accepts for a long option.
    "git config --li",
    "git config --lis",
    "git config --get-r a",
    "git config --get-al a.b",
    "git config --g a.b",
    "git config --ed",
    "git config --unse a.b",
    "git config --show-o --list",
    # A value given to an option that takes none.
    "git config --list=x",
    "git config --get=a.b",
    "git config --global=x --list",
    # Short-option clusters and attached values.
    "git config -lz",
    "git config -zl",
    "git config -le",
    "git config -tbool --get a.b",
    "git config -t=bool --get a.b",
    # Repeated options, and two of a kind.
    "git config --get --get a.b",
    "git config -l -l",
    "git config -l --list",
    "git config --list --get a.b",
    "git config --global --local --list",
    "git config --type=bool --type=int --get a.b",
    # A ``--`` separator.
    "git config -- a.b",
    "git config --get -- a.b",
    "git config get -- a.b",
    # A subcommand anywhere but first, and a subcommand word as a value.
    "git config --global list",
    "git config --get list",
    "git config --get a.b --default edit",
    # Operand counts the form does not take.
    "git config get a.b c",
    "git config get",
    "git config list a.b",
    "git config --list a.b",
    "git config --get",
    "git config --get a.b c d",
    "git config --get-urlmatch http",
    "git config a.b c d",
    # A value-taking option with no value, or a flag where its value should be.
    "git config --get a.b --type",
    "git config --get --default --edit a.b",
    "git config --get --type -l a.b",
    # Options git has that the allowlist does not name.
    "git config --no-show-origin --list",
    "git config --no-type --get a.b",
    "git config --unknownflag a b",
    "git config list --all",
    "git config --all --get a.b",
    "git config -h",
]

#: Reads from somewhere the command names, or with git pointed at another repository or home.
ELSEWHERE = [
    "git config --file x --list",
    "git config --file=x --list",
    "git config -f x --get a.b",
    "git config --get a.b --file x",
    "git config --blob HEAD:x --list",
    "git config --blob=HEAD:x --get a.b",
    "git config --includes --list",
    "git config --no-includes --list",
    "git config --get-regexp --file /elsewhere/x .",
    "git config get --file x a.b",
    "git config get --blob=HEAD:x a.b",
    "git config list --includes",
    "git config list -f x",
    # Global options that move git to another repository, work tree or program directory.
    "git -C elsewhere config --list",
    "git --git-dir=elsewhere config --list",
    "git --git-dir elsewhere config --list",
    "git --work-tree=elsewhere config --list",
    "git --bare config --list",
    "git --namespace=x config --list",
    "git --exec-path=elsewhere config --list",
    "git --attr-source=HEAD config --list",
    "git -p config --list",
    # A variable set for the read.
    "GIT_DIR=elsewhere git config --list",
    "env GIT_DIR=elsewhere git config --list",
    "GIT_COMMON_DIR=elsewhere git config --get a.b",
    "LC_ALL=C git config --list",
    "XDG_CONFIG_HOME=elsewhere git config --list",
    "HOME=elsewhere git config --global --list",
]

#: Setting a variable that sets configuration, or moves the user configuration file, in any
#: place the shell takes it: before a command, alone, through ``env``, or by ``export``.
ENVIRONMENT = [
    ("env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=x git log", WRITE),
    ("env GIT_CONFIG_GLOBAL=elsewhere git commit -m x", WRITE),
    ("nice env GIT_CONFIG_SYSTEM=elsewhere git status", WRITE),
    ("export GIT_CONFIG_GLOBAL=elsewhere; git commit -m x", WRITE),
    ("GIT_CONFIG_GLOBAL=elsewhere; git commit -m x", WRITE),
    ("declare -x GIT_CONFIG_NOSYSTEM=1 && git status", WRITE),
    ("export GIT_CONFIG=elsewhere && git status", WRITE),
    ("HOME=elsewhere git commit -m x", SOURCE),
    ("env HOME=elsewhere git status", SOURCE),
    ("export HOME=elsewhere && git commit -m x", SOURCE),
    ("XDG_CONFIG_HOME=elsewhere git status", SOURCE),
    ("typeset XDG_CONFIG_HOME=elsewhere; git status", SOURCE),
]

#: The read forms a role session runs, and must still run.
ADMITTED = [
    "git config --get user.name",
    "git config user.email",
    "git config --get-regexp '^user'",
    "git config --list",
    "git config -l",
    "git config --get-all a.b",
    "git config --get a.b pattern",
    "git config --get-urlmatch http https://example.invalid",
    "git config --get-color color.diff.new",
    "git config --get-colorbool color.ui",
    "git config --global --list",
    "git config --system --list",
    "git config --local --get a.b",
    "git config --worktree --list",
    "git config --show-origin --list",
    "git config --show-scope -l",
    "git config --name-only --list",
    "git config --show-names --get a.b",
    "git config -z --list",
    "git config --null -l",
    "git config --bool --get a.b",
    "git config --path --get a.b",
    "git config --type=bool --get a.b",
    "git config --type bool --get a.b",
    "git config -t bool --get a.b",
    "git config --get a.b --default=x",
    "git config --get a.b --default x",
    "git config --fixed-value --get a.b v",
    "git config list",
    "git config list --show-origin",
    "git config list --global",
    "git config list --name-only -z",
    "git config get a.b",
    "git config get --all a.b",
    "git config get --regexp 'a.*'",
    "git config get --value=x a.b",
    "git config get --value x --fixed-value a.b",
    "git config get --url=https://example.invalid http.sslVerify",
    "git config get --type=int --default=1 a.b",
    "git --no-pager config --list",
    "git -P config --get a.b",
    "git --no-optional-locks config --list",
]


@pytest.mark.parametrize("command", WRITES, ids=WRITES)
def test_a_config_write_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == WRITE


@pytest.mark.parametrize("command", SPELLINGS, ids=SPELLINGS)
def test_a_spelling_the_allowlist_does_not_read_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == WRITE


@pytest.mark.parametrize("command", ELSEWHERE, ids=ELSEWHERE)
def test_a_read_from_another_source_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == SOURCE


@pytest.mark.parametrize(("command", "reason"), ENVIRONMENT, ids=[c for c, _ in ENVIRONMENT])
def test_a_variable_that_sets_or_moves_config_is_refused(
    tmp_path: Path, command: str, reason: str
) -> None:
    assert _decide(tmp_path, command) == reason


@pytest.mark.parametrize("command", ADMITTED, ids=ADMITTED)
def test_a_read_of_the_repository_s_own_config_is_admitted(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == "allow"


def test_a_variable_that_does_not_touch_config_is_still_admitted(tmp_path: Path) -> None:
    # Only the configuration's variables are refused, not every variable before a command.
    assert _decide(tmp_path, "GIT_TRACE=1 git status") == "allow"
    assert _decide(tmp_path, "export PATH=/usr/bin:/bin && git status") == "allow"
    assert _decide(tmp_path, "echo HOME=elsewhere GIT_CONFIG_GLOBAL=x") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "HOME=elsewhere git status",
        "git -C elsewhere config --list",
        "git config --file x --list",
        "git config edit",
    ],
)
def test_the_config_source_rules_are_for_role_sessions_only(tmp_path: Path, command: str) -> None:
    # The orchestrator owns the repository and its configuration.
    assert _decide(tmp_path, command, profile="orchestrator") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "env GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/x'\" git commit -m x",
        "export GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/x'\"; git commit -m x",
    ],
)
def test_a_hook_path_set_through_env_or_export_is_refused_to_every_profile(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.HOOK_CONFIG


def test_a_global_option_s_separate_value_is_not_taken_for_the_subcommand(tmp_path: Path) -> None:
    # git reads ``--attr-source HEAD`` as one option and its value (measured, git 2.54), so
    # the subcommand after it is the one checked.
    assert (
        _decide(tmp_path, "git --attr-source HEAD push --force", profile="orchestrator")
        == G.FORCE_PUSH
    )
