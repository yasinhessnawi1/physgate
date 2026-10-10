"""Forbidden git operations are refused wherever they run; text that names them passes.

Every refused row has an allowed twin close to it, so a rule that matched text
instead of commands would fail the twin. The prose rows are the trap this
machine's own commit-flag hook falls into: it refuses a heredoc that writes a
document naming the flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import git_ops
from physgate.hooks.config import HookInput

G = git_ops

REFUSED = [
    ("git push --force", G.FORCE_PUSH),
    ("git push -f origin subtask/electrical-1", G.FORCE_PUSH),
    ("git push -uf origin x", G.FORCE_PUSH),
    ("git push --force-with-lease=main:abc origin main", G.FORCE_PUSH),
    ("git push --force-if-includes origin x", G.FORCE_PUSH),
    ("git push origin +main", G.FORCE_PUSH),
    ("git push origin :main", G.FORCE_PUSH),
    ("git push --delete origin main", G.FORCE_PUSH),
    ("git push --mirror", G.FORCE_PUSH),
    ("git -C /somewhere push --force", G.FORCE_PUSH),
    ("/usr/bin/git push --force", G.FORCE_PUSH),
    ("env GIT_TRACE=1 command git push --force", G.FORCE_PUSH),
    ("nohup git push --force", G.FORCE_PUSH),
    ('sh -c "git push --force"', G.FORCE_PUSH),
    ("bash -lc 'ls; git push -f'", G.FORCE_PUSH),
    ('eval "git push --force"', G.FORCE_PUSH),
    ("echo $(git push --force)", G.FORCE_PUSH),
    ("echo `git push --force`", G.FORCE_PUSH),
    ('echo "done: $(git push -f)"', G.FORCE_PUSH),
    ("ls && (cd sub && git push --force)", G.FORCE_PUSH),
    ("git commit --no-verify -m x", G.SKIP_HOOKS),
    ("git commit -m x --no-verify", G.SKIP_HOOKS),
    ("git commit -n -m x", G.SKIP_HOOKS),
    ("git commit -nm x", G.SKIP_HOOKS),
    ("git commit -anm x", G.SKIP_HOOKS),
    ("git merge --no-verify topic", G.SKIP_HOOKS),
    ("git am --no-verify patch.mbox", G.SKIP_HOOKS),
    ("git -c core.hooksPath=/dev/null commit -m x", G.HOOK_CONFIG),
    ("GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/x'\" git commit -m x", G.HOOK_CONFIG),
    ("git config core.hooksPath /tmp/none", G.HOOK_CONFIG),
    ("git config --local core.HooksPath /tmp/none", G.HOOK_CONFIG),
    ("git config alias.ci 'commit -n'", G.HOOK_CONFIG),
    ("git --config-env=core.hooksPath=X commit -m x", G.HOOK_CONFIG),
    ("git reset --hard origin/main", G.HARD_RESET),
    ("git reset --hard main", G.HARD_RESET),
    ("git checkout main && git reset --hard", G.HARD_RESET),
    ("git -C ../other reset --hard", G.HARD_RESET),
    ("git rebase main", G.REBASE),
    ("git rebase --onto main a b", G.REBASE),
    ("git rebase --continue", G.REBASE),
    ("git branch -f main HEAD", G.REF_WRITE),
    ("git branch -D main", G.REF_WRITE),
    ("git branch --delete main", G.REF_WRITE),
    ("git branch -M main", G.REF_WRITE),
    ("git update-ref refs/heads/main HEAD", G.REF_WRITE),
    ("g=git; $g push --force", G.DYNAMIC_GIT),
    ("git push $FLAGS", G.DYNAMIC_GIT),
    ("git push", G.ROLE_PUSH),
    ("git push origin subtask/electrical-1", G.ROLE_PUSH),
    # A role session may not write git's configuration: any set key could make a later
    # command run a program. The rule is the action, not a list of keys. (These strings are
    # only parsed by the hook; no git runs.)
    ("git config user.email me@example.invalid", G.ROLE_CONFIG_WRITE),
    ("git config filter.x.clean somecommand", G.ROLE_CONFIG_WRITE),
    ("git config diff.external somecommand", G.ROLE_CONFIG_WRITE),
    ("git config core.fsmonitor somecommand", G.ROLE_CONFIG_WRITE),
    ("git config --add remote.o.url x", G.ROLE_CONFIG_WRITE),
    ("git config --unset user.email", G.ROLE_CONFIG_WRITE),
    ("git config --unset-all a.b", G.ROLE_CONFIG_WRITE),
    ("git config --replace-all a.b c", G.ROLE_CONFIG_WRITE),
    ("git config --remove-section foo", G.ROLE_CONFIG_WRITE),
    ("git config --rename-section foo bar", G.ROLE_CONFIG_WRITE),
    ("git config -e", G.ROLE_CONFIG_WRITE),
    ("git config --edit", G.ROLE_CONFIG_WRITE),
    ("git config --file custom a.b c", G.ROLE_CONFIG_WRITE),
    ("git -C sub config user.name me", G.ROLE_CONFIG_WRITE),
    # Inline config, in every spelling git accepts, is also setting config.
    ("git -c filter.x.clean=somecommand add -A", G.ROLE_CONFIG_WRITE),
    ("git -c core.fsmonitor=somecommand status", G.ROLE_CONFIG_WRITE),
    ("git -c core.pager=somecommand log", G.ROLE_CONFIG_WRITE),
    ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager git log", G.ROLE_CONFIG_WRITE),
    ("GIT_CONFIG_PARAMETERS=\"'core.pager=x'\" git log", G.ROLE_CONFIG_WRITE),
    # A shape the rule cannot read as a plain read is refused, not passed.
    ("git config --unknownflag a b", G.ROLE_CONFIG_WRITE),
]

ALLOWED = [
    "git status",
    "git log -n 5 --oneline",
    "git diff --stat",
    "git commit -m 'a normal message'",
    "git commit --only -- src/a.py src/b.py",
    "git commit --only -m 'x' -- src/a.py",
    "git commit -m --no-verify",
    "git commit -m 'docs: explain why --no-verify is refused'",
    "git commit -F notes.txt -a",
    "git config --get user.name",
    "git config user.email",
    "git config --get-regexp '^user'",
    "git config --list",
    "git config -l",
    "git branch --list",
    "git branch subtask/extra",
    "git rebase --abort",
    "git reset --hard",
    "git reset --hard HEAD~1",
    "git reset --soft main",
    "git log --grep='push --force'",
    "echo 'git push --force'",
    "printf '%s\\n' 'git commit --no-verify'",
    "python3 -c \"print('git push -f')\"",
    "grep -rn -- '--no-verify' docs/",
    "# git push --force\nls",
    "cat <<'EOF' > docs/hooks.md\nNever run git commit --no-verify or git push --force.\nEOF\n",
    "cat > t.sh <<EOF\ngit push -f\nEOF\nchmod +x t.sh",
]


def _repo(tmp: Path, branch: str = "subtask/electrical-1") -> Path:
    worktree = tmp / "worktree"
    (worktree / ".git").mkdir(parents=True, exist_ok=True)
    (worktree / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    return worktree


def _decide(
    tmp: Path, command: str, profile: str = "role", branch: str = "subtask/electrical-1"
) -> str:
    worktree = _repo(tmp, branch)
    _, _, config = write_config(tmp, profile=profile)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=str(worktree))), config
    )
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize(("command", "reason"), REFUSED, ids=[c for c, _ in REFUSED])
def test_a_forbidden_git_operation_is_refused(tmp_path: Path, command: str, reason: str) -> None:
    assert _decide(tmp_path, command) == reason


@pytest.mark.parametrize("command", ALLOWED, ids=ALLOWED)
def test_an_ordinary_command_or_text_naming_a_flag_passes(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command) == "allow"


def test_the_config_write_refusal_is_for_role_sessions_only(tmp_path: Path) -> None:
    # The orchestrator owns the repository and writes its own identity and settings.
    assert _decide(tmp_path, "git config user.email x@y.invalid", profile="orchestrator") == "allow"
    # A role session is refused the same write, and still allowed to read a value.
    assert _decide(tmp_path, "git config user.email x@y.invalid") == G.ROLE_CONFIG_WRITE
    assert _decide(tmp_path, "git config --get user.email") == "allow"


#: git accepts any unique prefix of a subcommand's long option, so every
#: forbidden long option has abbreviated twins here. They are decided for the
#: orchestrator profile, which may push, so a force push is refused as a force
#: push and not merely as a push.
ABBREVIATED = [
    ("git commit --no-verif -m x", G.SKIP_HOOKS),
    ("git commit -m x --no-v", G.SKIP_HOOKS),
    ("git merge --no-ver topic", G.SKIP_HOOKS),
    ("git push --no-verif origin x", G.SKIP_HOOKS),
    ("git push --forc origin x", G.FORCE_PUSH),
    ("git push --fo origin x", G.FORCE_PUSH),
    ("git push --force-w origin x", G.FORCE_PUSH),
    ("git push --force-with=x:abc origin x", G.FORCE_PUSH),
    ("git push --force-if origin x", G.FORCE_PUSH),
    ("git push --mirr", G.FORCE_PUSH),
    ("git push --dele origin x", G.FORCE_PUSH),
    ("git reset --har origin/master", G.HARD_RESET),
    ("git reset --ha main", G.HARD_RESET),
    ("git branch --forc x HEAD", G.REF_WRITE),
    ("git branch --delet x", G.REF_WRITE),
    ("git branch --mov a b", G.REF_WRITE),
    ("git branch --cop a b", G.REF_WRITE),
]
#: Long options that share a first letter with a forbidden one and are not a
#: prefix of it: each is allowed.
ABBREVIATED_TWINS_ALLOWED = [
    "git push --follow-tags origin x",
    "git push --dry-run origin x",
    "git commit --no-edit --amend",
    "git branch --contains HEAD",
    "git branch --color=never",
    "git reset --soft HEAD~1",
    "git reset --hard",
]


@pytest.mark.parametrize(("command", "reason"), ABBREVIATED, ids=[c for c, _ in ABBREVIATED])
def test_an_abbreviated_forbidden_long_option_is_refused(
    tmp_path: Path, command: str, reason: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == reason


def test_an_abbreviated_config_env_global_is_refused_whatever_key_it_sets(tmp_path: Path) -> None:
    """A guard for the future, not for today's git.

    git 2.54 rejects an abbreviated global option (``--config-e=`` is an
    unknown option), so this command fails in git as it stands. The hook refuses
    it anyway, as the ``--config-env`` it would abbreviate if a later git
    accepted prefixes there. The key names no hook path on purpose: a key that
    did would be refused by the hook-path rule, and the row would then prove
    nothing about the abbreviation.
    """
    assert (
        _decide(tmp_path, "git --config-e=user.name=X commit -m x", profile="orchestrator")
        == G.HOOK_CONFIG
    )


@pytest.mark.parametrize("command", ABBREVIATED_TWINS_ALLOWED, ids=ABBREVIATED_TWINS_ALLOWED)
def test_a_long_option_that_only_shares_letters_with_a_forbidden_one_passes(
    tmp_path: Path, command: str
) -> None:
    assert _decide(tmp_path, command, profile="orchestrator") == "allow"


@pytest.mark.parametrize("profile", ["reviewer", "orchestrator"])
def test_a_plain_push_is_refused_only_to_a_role(tmp_path: Path, profile: str) -> None:
    assert _decide(tmp_path, "git push origin x", profile=profile) == "allow"
    assert _decide(tmp_path, "git push --force origin x", profile=profile) == G.FORCE_PUSH


def test_a_hard_reset_on_a_branch_that_is_not_the_sessions_own_is_refused(
    tmp_path: Path,
) -> None:
    assert _decide(tmp_path, "git reset --hard HEAD", branch="main") == G.HARD_RESET
    assert _decide(tmp_path, "git reset --hard HEAD", branch="subtask/electrical-1") == "allow"


def test_a_hard_reset_with_no_own_branch_configured_is_refused(tmp_path: Path) -> None:
    worktree = _repo(tmp_path)
    _, _, config = write_config(tmp_path, own_branch=None)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash("git reset --hard", cwd=str(worktree))), config
    )
    assert decision.reason == G.HARD_RESET


def test_a_linked_worktree_is_followed_to_its_head(tmp_path: Path) -> None:
    git_dir = tmp_path / "main-repo" / ".git" / "worktrees" / "w"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/subtask/electrical-1\n")
    worktree = tmp_path / "linked"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {git_dir}\n")
    _, _, config = write_config(tmp_path)
    decision = git_ops.pre_tool_use(
        HookInput.model_validate(bash("git reset --hard", cwd=str(worktree))), config
    )
    assert decision.allow


@pytest.mark.parametrize(
    "command",
    ['git commit -m "unterminated', "cat <<EOF\nno terminator", "echo $(git push"],
)
def test_a_command_that_cannot_be_split_is_refused(tmp_path: Path, command: str) -> None:
    assert _decide(tmp_path, command).startswith("This command could not be split")


def test_writing_a_document_that_names_the_flags_passes(tmp_path: Path) -> None:
    _, _, config = write_config(tmp_path)
    doc = event(
        tool_name="Write",
        tool_input={
            "file_path": str(tmp_path / "worktree" / "docs" / "git.md"),
            "content": "Never run git commit --no-verify, git push --force or git push -f.\n",
        },
    )
    assert git_ops.pre_tool_use(HookInput.model_validate(doc), config).allow
