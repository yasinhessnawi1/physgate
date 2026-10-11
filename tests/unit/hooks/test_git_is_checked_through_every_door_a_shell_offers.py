"""A git command is checked however the shell is told to run it, and wherever it points git.

Every row is only parsed by the hook and decided; no git or shell runs, and nothing is
configured. Rows decided for the orchestrator profile are rules held for every profile;
the rest are a role session's.

The doors: a reserved word or a program in front of git (``{ git …; }``, ``if git …``,
``timeout 5 git …``, ``sudo -u x git …``), a shell given its commands on standard input,
``env`` options whose effect cannot be read, a word the shell expands into something else
(a glob, a brace pattern), git pointed at another repository, a git command git does not
have (an alias), and configuration keys spelt in another case or set another way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import git_ops, paths
from physgate.hooks.config import HookInput
from physgate.hooks.settings import InstallRequest, build_config, current_installation

G = git_ops
WRITE = G.ROLE_CONFIG_WRITE


def _decide(tmp: Path, command: str, profile: str = "role") -> str:
    worktree = tmp / "worktree"
    (worktree / ".git").mkdir(parents=True, exist_ok=True)
    (worktree / ".git" / "HEAD").write_text("ref: refs/heads/subtask/electrical-1\n")
    _, _, config = write_config(tmp, profile=profile)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=str(worktree))), config
    )
    return "allow" if decision.allow else decision.reason


#: A reserved word or a program in front of git hides it from a check that looks only at
#: the first word. Each is refused as what it is, for every profile.
IN_FRONT = [
    "{ git push -f; }",
    "if true; then git push -f; fi",
    "if git push -f; then :; fi",
    "for x in 1; do git push -f; done",
    "while git push -f; do :; done",
    "until git push -f; do :; done",
    "! git push -f",
    "f() { git push -f; }; f",
    "function f { git push -f; }; f",
    "coproc git push -f",
    "timeout 5 git push -f",
    "nice -n 5 timeout 5 git push -f",
    "stdbuf -oL git push -f",
    "sudo -u root git push --force",
    "exec -a name git push --force",
    "uv run git push -f",
    "timeout 5 sh -c 'git push -f'",
    "timeout 5 bash -lc 'ls; git push -f'",
    "timeout 5 eval 'git push -f'",
    "echo sh -c 'git push -f'",
]


@pytest.mark.parametrize("command", IN_FRONT, ids=IN_FRONT)
def test_git_behind_a_reserved_word_or_a_program_is_still_checked(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.FORCE_PUSH


#: The same, for a role's configuration rules.
IN_FRONT_OF_CONFIG = [
    "{ git config edit; }",
    "if true; then git config edit; fi",
    "timeout 5 git config edit",
    "uv run git config edit",
    "find . -maxdepth 0 && timeout 5 git config --add a.b c",
]


@pytest.mark.parametrize("command", IN_FRONT_OF_CONFIG, ids=IN_FRONT_OF_CONFIG)
def test_a_config_write_behind_a_reserved_word_or_a_program_is_refused(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command) == WRITE


#: Programs that add words to the git command they run.
FED = [
    "xargs git status",
    "printf 'a\\n' | xargs git log -n 1",
    "xargs -n 1 git commit -m x",
    "find . -name '*.py' -exec git add {} +",
    "parallel git status ::: a b",
]


@pytest.mark.parametrize("command", FED, ids=FED)
def test_git_run_through_a_program_that_adds_words_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_GIT_FED


#: A shell that reads its commands from standard input.
STDIN_SHELLS = [
    "echo 'git config edit' | sh",
    "cat commands.txt | bash",
    "bash -s",
    "zsh -s < commands.txt",
    "bash <<EOF\ngit config edit\nEOF\n",
    "sh < commands.txt",
    "timeout 5 sh",
]


@pytest.mark.parametrize("command", STDIN_SHELLS, ids=STDIN_SHELLS)
def test_a_shell_reading_its_commands_from_input_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_SHELL_STDIN


#: ``env`` options whose effect a check cannot read.
OPAQUE_ENV = [
    'env -S "git config edit"',
    'env --split-string="git config edit"',
    "env -S 'git push --force'",
    "env -C /elsewhere git status",
    "env --chdir=/elsewhere git status",
    "env -i A=1 git status",
    "env -v git status",
    "env -0",
    'nice env -S "git config edit"',
    'timeout 5 env -S "git config edit"',
]


@pytest.mark.parametrize("command", OPAQUE_ENV, ids=OPAQUE_ENV)
def test_an_env_option_whose_effect_cannot_be_read_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_OPAQUE_ENV


#: A word the shell turns into other words before git sees it. Refused for every profile.
EXPANDING = [
    "git config {edit,}",
    "git config e{d,}it",
    "git config ed?t",
    "git config ed*",
    "git config ed[i]t",
    "git push origin *",
    "git commit -m x {--no-verify,}",
    "timeout 5 git push origin *",
]


@pytest.mark.parametrize("command", EXPANDING, ids=EXPANDING)
def test_a_word_the_shell_expands_in_a_git_command_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.EXPANDING_GIT
    assert _decide(tmp_path, command) == G.EXPANDING_GIT


#: Git pointed at another repository, by option or by variable, on any git command.
REPOSITORY = [
    "git -C /elsewhere status",
    "git -C /elsewhere log --oneline",
    "git --git-dir=/elsewhere/.git status",
    "git --git-dir /elsewhere/.git status",
    "git --work-tree=/elsewhere status",
    "git --work-tree /elsewhere add a.txt",
    "git --bare log",
    "git --namespace=x log",
    "GIT_DIR=/elsewhere/.git git status",
    "GIT_COMMON_DIR=/elsewhere git log",
    "GIT_WORK_TREE=/elsewhere git status",
    "GIT_INDEX_FILE=/elsewhere/index git commit -m x",
    "GIT_OBJECT_DIRECTORY=/elsewhere/objects git log",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES=/elsewhere/objects git log",
    "env GIT_DIR=/elsewhere/.git git status",
    "export GIT_DIR=/elsewhere/.git; git status",
    "GIT_DIR=/elsewhere/.git; git status",
    "declare -x GIT_WORK_TREE=/elsewhere && git status",
    "GIT_DIR=/elsewhere/.git git config --list",
    "GIT_COMMON_DIR=/elsewhere git config --get a.b",
    "timeout 5 git -C /elsewhere status",
]


@pytest.mark.parametrize("command", REPOSITORY, ids=REPOSITORY)
def test_git_pointed_at_another_repository_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_REPOSITORY


def test_a_refusal_that_names_the_operation_still_names_it(tmp_path: Path) -> None:
    # The repository rule comes after the operation rules, so their reasons are kept.
    assert _decide(tmp_path, "git -C /elsewhere push --force") == G.FORCE_PUSH
    assert _decide(tmp_path, "git -C /elsewhere reset --hard") == G.HARD_RESET
    assert _decide(tmp_path, "git -C sub config user.name me") == WRITE


#: A git command git does not have is an alias or a program on the path.
UNKNOWN = [
    "git myalias",
    "git ci -m x",
    "git lfs pull",
    "git st",
    "timeout 5 git myalias",
    "{ git myalias; }",
    "! git myalias",
]


@pytest.mark.parametrize("command", UNKNOWN, ids=UNKNOWN)
def test_a_git_command_git_does_not_have_is_refused(tmp_path: Path, command: str) -> None:
    sub = command.split("git ", 1)[1].split()[0].rstrip(";")
    assert _decide(tmp_path, command) == G.ROLE_UNKNOWN_SUBCOMMAND.format(sub=sub)


def test_a_shell_alias_is_refused(tmp_path: Path) -> None:
    assert _decide(tmp_path, "alias g='git push -f'") == G.ROLE_SHELL_ALIAS
    assert _decide(tmp_path, "alias") == "allow"


#: Keys that make git run something, in any case, in any way they are set: for every profile.
EXEC_CONFIG = [
    "git config Alias.ci 'commit -n'",
    "git config ALIAS.x y",
    "git config include.path /elsewhere/x",
    "git config IncludeIf.gitdir:/x.path /elsewhere/x",
    "git config --rename-section foo core",
    "git config rename-section foo alias",
    "git config --rename-section foo Alias",
    "git -c Alias.x=y status",
    "git -c include.path=/elsewhere/x status",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0=y git status",
    "env GIT_CONFIG_PARAMETERS=\"'Include.Path=/x'\" git status",
    "export GIT_CONFIG_KEY_0=ALIAS.x; git status",
    "env GIT_CONFIG_PARAMETERS=\"'core.HooksPath=/x'\" git status",
]


@pytest.mark.parametrize("command", EXEC_CONFIG, ids=EXEC_CONFIG)
def test_a_key_that_makes_git_run_something_is_refused_however_it_is_set(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.HOOK_CONFIG


#: Commands a role runs, and must still run.
ADMITTED = [
    "git status",
    "git log --oneline -n 5",
    "git diff --stat",
    "git help config",
    "git version",
    "git --version",
    "git commit -m 'fix? maybe'",
    "git log HEAD@{1}",
    "git rev-parse @{u}",
    "git log --grep='a*b'",
    "git config --get-regexp 'a.*'",
    "git add 'src/*.py'",
    "env -u FOO git status",
    "env --unset=FOO git status",
    "env -i git status",
    "env GIT_TRACE=1 git status",
    "sh -c 'ls'",
    "bash script.sh",
    "uv run pytest -q",
    "timeout 60 uv run pytest -q",
    "grep git README.md",
    "grep -rn git src",
    "grep -n 'git' $FILE",
    "grep -rn git *.md",
    "which bash",
    "ls /bin/sh",
    "find . -name '*.py'",
    "echo 'git config edit is refused'",
    "nohup python3 run.py &",
]


@pytest.mark.parametrize("command", ADMITTED, ids=ADMITTED)
def test_an_ordinary_command_is_admitted(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "git -C /elsewhere status",
        "GIT_DIR=/elsewhere/.git git status",
        "git myalias",
        'env -S "git status"',
        "echo ls | sh",
        "xargs git status",
        "alias g=git",
    ],
)
def test_the_role_rules_are_for_role_sessions_only(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == "allow"


def _install(tmp: Path, profile: str) -> InstallRequest:
    worktree = tmp / "worktree"
    worktree.mkdir(exist_ok=True)
    return InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="electrical" if profile == "role" else None,
        worktree=str(worktree),
        own_branch="subtask/e1" if profile == "role" else None,
        store_root=str(tmp / "store"),
        state_dir=str(tmp / "state"),
        target_dir=str(tmp / "session"),
        claude_config_dir=str(tmp / "claude-config"),
        user_home=str(tmp / "home"),
        token_ceiling=4000,
        read_roots=(str(worktree),) if profile == "reviewer" else (),
    )


@pytest.mark.parametrize(
    "relative", [".gitconfig", ".config/git/config", ".config/git/attributes", ".config/git"]
)
def test_a_role_s_git_user_configuration_is_a_protected_path(tmp_path: Path, relative: str) -> None:
    config = build_config(_install(tmp_path, "role"), current_installation())
    target = tmp_path / "home" / relative
    write = event(tool_name="Write", tool_input={"file_path": str(target), "content": "x\n"})
    decision = paths.pre_tool_use(HookInput.model_validate(write), config)
    assert not decision.allow
    assert "git's user configuration" in decision.reason


def test_the_rest_of_a_role_s_home_is_not_protected_by_it(tmp_path: Path) -> None:
    config = build_config(_install(tmp_path, "role"), current_installation())
    target = tmp_path / "home" / "notes.txt"
    write = event(tool_name="Write", tool_input={"file_path": str(target), "content": "x\n"})
    assert paths.pre_tool_use(HookInput.model_validate(write), config).allow


@pytest.mark.parametrize("profile", ["reviewer", "orchestrator"])
def test_only_a_role_s_home_git_configuration_is_added(tmp_path: Path, profile: str) -> None:
    config = build_config(_install(tmp_path, profile), current_installation())
    roots = {root.path for root in config.protected_roots}
    assert str(tmp_path / "home" / ".gitconfig") not in roots
    role = build_config(_install(tmp_path, "role"), current_installation())
    assert {str(tmp_path / "home" / ".gitconfig"), str(tmp_path / "home" / ".config" / "git")} <= {
        root.path for root in role.protected_roots
    }


#: git's own programs run by their dashed names are the same commands.
DASHED = [
    ("git-push --force origin x", G.FORCE_PUSH, "orchestrator"),
    ("/opt/git/libexec/git-core/git-push -f", G.FORCE_PUSH, "orchestrator"),
    ("timeout 5 git-push -f", G.FORCE_PUSH, "orchestrator"),
    ("git-config edit", WRITE, "role"),
    ("git-config Alias.x y", G.HOOK_CONFIG, "orchestrator"),
    ("git-myalias", G.ROLE_UNKNOWN_SUBCOMMAND.format(sub="myalias"), "role"),
]


@pytest.mark.parametrize(("command", "reason", "profile"), DASHED, ids=[c for c, _, _ in DASHED])
def test_a_dashed_git_program_is_checked_as_git(
    tmp_path: Path, command: str, reason: str, profile: str
) -> None:
    assert _decide(tmp_path, command, profile=profile) == reason


#: Programs that run a command handed to them as one string.
STRINGS = [
    "trap 'git push -f' EXIT",
    "watch 'git push -f'",
    "watch -n 5 git push -f",
    "su -c 'git push -f' root",
    "runuser --command='git push -f' root",
    "script -q -c 'git push -f' /dev/null",
    "flock /tmp/lock -c 'git push -f'",
]


@pytest.mark.parametrize("command", STRINGS, ids=STRINGS)
def test_a_command_handed_over_as_a_string_is_checked(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.FORCE_PUSH


#: A hard reset of another repository than the one whose branch was read, for every profile.
RESET_ELSEWHERE = [
    "git --git-dir=/elsewhere/.git reset --hard",
    "git --work-tree=/elsewhere reset --hard",
    "GIT_DIR=/elsewhere/.git git reset --hard",
    "env GIT_DIR=/elsewhere/.git git reset --hard",
    "cd /elsewhere && git reset --hard",
    "pushd /elsewhere; git reset --hard",
]


@pytest.mark.parametrize("command", RESET_ELSEWHERE, ids=RESET_ELSEWHERE)
def test_a_hard_reset_pointed_elsewhere_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.HARD_RESET


#: A role's git run outside its worktree: a ``cd`` in the same call, by any spelling.
MOVED = [
    "cd /elsewhere && git status",
    "cd .. && git status",
    "cd && git status",
    "cd - && git log",
    "cd ~/x && git status",
    "cd $SOMEWHERE && git status",
    "pushd /elsewhere && git commit -m x",
    "cd sub; popd; git status",
    "(cd /elsewhere && git status)",
]


@pytest.mark.parametrize("command", MOVED, ids=MOVED)
def test_a_role_s_git_after_leaving_its_worktree_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_REPOSITORY


def test_a_role_s_git_inside_its_worktree_after_a_cd_is_admitted(tmp_path: Path) -> None:
    assert _decide(tmp_path, "cd sub && git status") == "allow"
    assert _decide(tmp_path, "cd sub/../other && git log -n 1") == "allow"
    assert _decide(tmp_path, "cd /elsewhere && ls") == "allow"


def test_a_role_s_git_in_a_call_that_starts_outside_its_worktree_is_refused(
    tmp_path: Path,
) -> None:
    # A directory change persists between calls, so a call can start somewhere else.
    _, _, config = write_config(tmp_path)
    outside = tmp_path / "other"
    outside.mkdir()
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash("git status", cwd=str(outside))), config
    )
    assert decision.reason == G.ROLE_REPOSITORY
    not_git = git_ops.pre_tool_use(HookInput.model_validate(bash("ls", cwd=str(outside))), config)
    assert not_git.allow
