"""A git command is seen however the shell is told to run it.

Every row is only parsed by the hook and decided; no git or shell runs, and nothing is
configured. A role session runs no git at all, so for a role every door below must end in
the same refusal. The orchestrator profile may run git, so the rows decided for it are the
rules held for every profile: they must still name the operation refused.

The doors: a reserved word or a program in front of git (``{ git …; }``, ``if git …``,
``timeout 5 git …``, ``sudo -u x git …``), a string handed to a shell or another runner,
git's dashed programs, a path or zsh's ``=git``, quoting, a command named at run time, a
shell given its commands on standard input, ``env`` options whose effect cannot be read,
a shell alias, and the variables that tell git what to read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import git_ops, paths
from physgate.hooks.config import HookInput
from physgate.hooks.settings import InstallRequest, build_config, current_installation

G = git_ops
NO_GIT = G.ROLE_NO_GIT


def _decide(tmp: Path, command: str, profile: str = "role") -> str:
    worktree = tmp / "worktree"
    (worktree / ".git").mkdir(parents=True, exist_ok=True)
    (worktree / ".git" / "HEAD").write_text("ref: refs/heads/subtask/electrical-1\n")
    _, _, config = write_config(tmp, profile=profile)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=str(worktree))), config
    )
    return "allow" if decision.allow else decision.reason


#: Every way a role's command can run git that the hook can see. Each is refused as git.
ROLE_GIT = [
    # Plain, and every subcommand: a read is git too.
    "git status",
    "git",
    "git --version",
    "git log --oneline -n 5",
    "git config --get user.name",
    "git config --list",
    "git config edit",
    "git commit -m x",
    "git add -A",
    "git push",
    "git send-pack origin HEAD:main",
    "git -C /elsewhere status",
    "git myalias",
    # Dashed programs, paths, and zsh's =git.
    "git-status",
    "git-config --list",
    "git-send-pack origin HEAD:main",
    "/usr/bin/git status",
    "/opt/homebrew/opt/git/libexec/git-core/git-push origin x",
    "./git status",
    "=git status",
    # Quoting the shell removes.
    '"git" status',
    "g'i't status",
    "\\git status",
    'g""it status',
    # Wrappers the parser steps over.
    "env git status",
    "env GIT_TRACE=1 git status",
    "env -u FOO git status",
    "command git status",
    "exec git status",
    "nohup git status",
    "time git status",
    "builtin git status",
    "nice -n 5 git status",
    "sudo git status",
    # Programs that run their arguments.
    "timeout 5 git status",
    "sudo -u root git status",
    "exec -a name git status",
    "uv run git status",
    "stdbuf -oL git status",
    "xargs git status",
    "find . -name '*.py' -exec git add {} +",
    "parallel git status ::: a b",
    "watch -n 5 git status",
    # A string handed to a shell or another runner.
    "sh -c 'git status'",
    "bash -lc 'ls; git status'",
    "eval 'git status'",
    "timeout 5 sh -c 'git status'",
    "trap 'git status' EXIT",
    "watch 'git status'",
    "su -c 'git status' root",
    "runuser --command='git status' root",
    "script -q -c 'git status' /dev/null",
    "flock /tmp/lock -c 'git status'",
    # Reserved words, functions, and the shell's own structure.
    "{ git status; }",
    "if true; then git status; fi",
    "if git status; then :; fi",
    "for x in 1; do git status; done",
    "while git status; do :; done",
    "until git status; do :; done",
    "! git status",
    "f() { git status; }; f",
    "function f { git status; }; f",
    "coproc git status",
    "{ git myalias; }",
    "! git",
    "if git; then :; fi",
    "(git status)",
    "ls && git status",
    "ls; git status",
    "ls | git status",
    "git status &",
    "echo $(git status)",
    "echo `git status`",
    'echo "$(git rev-parse HEAD)"',
    "cat <(git log)",
    # A command named at run time, followed by a git command.
    "$G status",
    '"$(command -v git)" log',
    "${GIT:-git} status",
    # Among another program's words, git naming one of its commands.
    "echo git status",
    "grep -n x $(git ls-files)",
]


@pytest.mark.parametrize("command", ROLE_GIT, ids=ROLE_GIT)
def test_a_role_s_git_is_refused_through_every_door(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == NO_GIT


#: Variables that tell git what to read, set any way the shell takes them.
ROLE_VARIABLES = [
    "GIT_CONFIG_GLOBAL=/elsewhere ls",
    "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=x ls",
    "export GIT_CONFIG_GLOBAL=/elsewhere; python3 run.py",
    "GIT_CONFIG_GLOBAL=/elsewhere; python3 run.py",
    "declare -x GIT_CONFIG_NOSYSTEM=1",
    "HOME=/elsewhere python3 run.py",
    "env HOME=/elsewhere python3 run.py",
    "export XDG_CONFIG_HOME=/elsewhere",
    "GIT_DIR=/elsewhere/.git python3 run.py",
    "export GIT_WORK_TREE=/elsewhere",
    "typeset GIT_INDEX_FILE=/elsewhere/index",
    "GIT_COMMON_DIR=/x GIT_OBJECT_DIRECTORY=/y GIT_ALTERNATE_OBJECT_DIRECTORIES=/z ls",
]


@pytest.mark.parametrize("command", ROLE_VARIABLES, ids=ROLE_VARIABLES)
def test_a_role_setting_what_git_reads_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_GIT_VARIABLE


#: A shell reading its commands from standard input, where no check can see them.
STDIN_SHELLS = [
    "echo 'git status' | sh",
    "cat commands.txt | bash",
    "bash -s",
    "zsh -s < commands.txt",
    "bash <<EOF\ngit status\nEOF\n",
    "sh < commands.txt",
    "timeout 5 sh",
    "echo 'git status' | bash -o errexit",
    "bash -O extglob +o histexpand < commands.txt",
    "bash --rcfile x.sh",
]


@pytest.mark.parametrize("command", STDIN_SHELLS, ids=STDIN_SHELLS)
def test_a_shell_reading_its_commands_from_input_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_SHELL_STDIN


#: ``env`` options whose effect a check cannot read.
OPAQUE_ENV = [
    'env -S "git status"',
    'env --split-string="git status"',
    "env -C /elsewhere ls",
    "env --chdir=/elsewhere ls",
    "env -i A=1 ls",
    "env -v ls",
    "env -0",
    'nice env -S "git status"',
    'timeout 5 env -S "git status"',
]


@pytest.mark.parametrize("command", OPAQUE_ENV, ids=OPAQUE_ENV)
def test_an_env_option_whose_effect_cannot_be_read_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == G.ROLE_OPAQUE_ENV


def test_a_shell_alias_is_refused(tmp_path: Path) -> None:
    assert _decide(tmp_path, "alias g='git status'") == G.ROLE_SHELL_ALIAS
    assert _decide(tmp_path, "alias") == "allow"


#: Commands a role runs, and must still run.
ROLE_ADMITTED = [
    "ls -la",
    "python3 run.py",
    "uv run pytest -q",
    "timeout 60 uv run pytest -q",
    "sh -c 'ls'",
    "bash script.sh",
    "env -u FOO python3 run.py",
    "env -i python3 run.py",
    "env PYTHONPATH=src python3 run.py",
    "grep git README.md",
    "grep -rn git src",
    "grep -rn 'git status' docs",
    "grep -n 'git' $FILE",
    "echo 'git status is refused'",
    "cat .gitignore",
    "ls .git",
    "which bash",
    "ls /bin/sh",
    "find . -name '*.py'",
    "cd sub && ls",
    "$PYTHON -m pytest",
    "nohup python3 run.py &",
    "cat <<'EOF' > notes.md\nNever run git push --force.\nEOF\n",
]


@pytest.mark.parametrize("command", ROLE_ADMITTED, ids=ROLE_ADMITTED)
def test_an_ordinary_role_command_is_admitted(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git -C /elsewhere status",
        "GIT_DIR=/elsewhere/.git git status",
        "git myalias",
        'env -S "git status"',
        "echo ls | sh",
        "xargs git status",
        "alias g=git",
        "HOME=/elsewhere git status",
    ],
)
def test_the_role_rules_are_for_role_sessions_only(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == "allow"


# --- Rules held for every profile, decided for the orchestrator, which may run git. ---

#: A reserved word or a program in front of git hides it from a check that looks only at
#: the first word.
IN_FRONT = [
    "{ git push -f; }",
    "if true; then git push -f; fi",
    "for x in 1; do git push -f; done",
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
    "trap 'git push -f' EXIT",
    "watch 'git push -f'",
    "watch -n 5 git push -f",
    "su -c 'git push -f' root",
    "runuser --command='git push -f' root",
    "script -q -c 'git push -f' /dev/null",
    "flock /tmp/lock -c 'git push -f'",
    "git-push --force origin x",
    "/opt/git/libexec/git-core/git-push -f",
    "timeout 5 git-push -f",
    "=git push -f",
    "timeout 5 =git push -f",
]


@pytest.mark.parametrize("command", IN_FRONT, ids=IN_FRONT)
def test_git_behind_a_reserved_word_a_program_or_another_name_is_still_checked(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.FORCE_PUSH


#: A word the shell turns into other words before git sees it.
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


#: Keys that make git run something, in any case, in any way they are set.
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
    "git-config Alias.x y",
]


@pytest.mark.parametrize("command", EXEC_CONFIG, ids=EXEC_CONFIG)
def test_a_key_that_makes_git_run_something_is_refused_however_it_is_set(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.HOOK_CONFIG


#: A push that forces or deletes, by plumbing, by option or by configuration.
FORCED_PUSH = [
    "git send-pack --force origin main",
    "git send-pack origin +HEAD:main",
    "git send-pack --mirror origin",
    "git http-push --force https://example.invalid/r main",
    "git push --prune origin",
    "git push --all --prune",
    "git push --pru origin",
    "git -c 'remote.origin.push=+refs/heads/*:refs/heads/*' push",
    "git -c remote.origin.mirror=true push",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.push GIT_CONFIG_VALUE_0=+x:x git push",
    "git config remote.origin.push +refs/heads/x:refs/heads/main",
    "git config Remote.Origin.Mirror true",
]


@pytest.mark.parametrize("command", FORCED_PUSH, ids=FORCED_PUSH)
def test_a_push_that_forces_by_any_means_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.FORCE_PUSH


#: Options that look like they take a value in one subcommand and do not in another. A word
#: taken for a value would be a flag the checks never see.
VALUE_OPTIONS = [
    ("git am -m --no-verify patch.mbox", G.SKIP_HOOKS),
    ("git am -c --no-verify patch.mbox", G.SKIP_HOOKS),
    ("git am -t --no-verify patch.mbox", G.SKIP_HOOKS),
    ("git branch -t --force main origin/x", G.REF_WRITE),
    ("git branch -t --delete main", G.REF_WRITE),
    ("git branch -tf main origin/x", G.REF_WRITE),
    ("git push -t --force origin x", G.FORCE_PUSH),
    ("git push -tf origin x", G.FORCE_PUSH),
]


@pytest.mark.parametrize(("command", "reason"), VALUE_OPTIONS, ids=[c for c, _ in VALUE_OPTIONS])
def test_a_flag_is_not_taken_for_another_subcommand_s_value(
    tmp_path: Path, command: str, reason: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == reason


#: Forcing a branch to another commit, by any subcommand.
FORCED_BRANCH = [
    "git checkout -B main origin/x",
    "git checkout -fB main",
    "git switch -C main origin/x",
    "git switch --force-create main origin/x",
    "git switch --force-c main",
    "git worktree add -B main ../w origin/x",
    "git fetch origin +x:refs/heads/main",
    "git fetch . +HEAD~3:main",
]


@pytest.mark.parametrize("command", FORCED_BRANCH, ids=FORCED_BRANCH)
def test_forcing_a_branch_by_any_subcommand_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.REF_WRITE


#: A reset that moves the branch somewhere else: another mode, another repository, or after
#: an earlier step moved it.
RESET_ELSEWHERE = [
    "git reset --keep origin/main",
    "git reset --merge origin/main",
    "git reset --kee main",
    "git reset --soft main && git reset --hard HEAD",
    "git reset main; git reset --hard",
    "git reset --mixed origin/x && git reset --keep HEAD",
    "git --git-dir=/elsewhere/.git reset --hard",
    "git --work-tree=/elsewhere reset --hard",
    "GIT_DIR=/elsewhere/.git git reset --hard",
    "env GIT_DIR=/elsewhere/.git git reset --hard",
    "cd /elsewhere && git reset --hard",
    "pushd /elsewhere; git reset --hard",
]


@pytest.mark.parametrize("command", RESET_ELSEWHERE, ids=RESET_ELSEWHERE)
def test_a_reset_that_moves_the_branch_elsewhere_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == G.HARD_RESET


#: What the orchestrator profile still runs.
ADMITTED = [
    "git status",
    "git commit -m --no-verify",
    "git commit -m 'fix? maybe'",
    "git push origin x",
    "git push -u origin x",
    "git branch -t topic origin/x",
    "git branch -u origin/x",
    "git checkout -b topic",
    "git switch -c topic",
    "git fetch origin x:refs/remotes/origin/x",
    "git reset --soft HEAD~1",
    "git reset --keep HEAD~1",
    "git reset --hard",
    "git log HEAD@{1}",
    "git config user.name x",
    "git -c user.name=x commit -m y",
    "grep -rn git *.md",
]


@pytest.mark.parametrize("command", ADMITTED, ids=ADMITTED)
def test_what_the_orchestrator_runs_is_admitted(tmp_path: Path, command: str) -> None:
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
