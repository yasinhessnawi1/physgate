"""Under ``skills: off`` no copy of the role's skill file is in a role session's reach.

Withholding the file at its path in the session's own worktree is not enough on its own if its
bytes lie anywhere else the session reads: the run branch's history in the target's object store,
or the checkout of the same commit in the orchestrator's integration worktree. A role session runs
no git, so git's own readers are refused; what remains is every other way to the same bytes.

The session here is installed as the dispatcher installs one: the run's protected roots from the
real target repository, its records withheld, and the skill file withheld under the arm.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from hook_helpers import bash

import physgate.hooks.git_ops as git_ops
from physgate.hooks import paths, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.knowledge import loader
from physgate.orchestrator.dispatch import session_protected_roots
from physgate.orchestrator.merge import RunGit
from physgate.oslayer.policy import sandbox_policy

ROLE = "control"
SKILL = f"knowledge/{ROLE}/skill.md"
SPEC = Path(".physgate/specs/s1.md")
BODY = "skill-marker-" + "cd" * 12 + "\n"
GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        ["git", *argv], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _blob_path(repo: Path) -> Path:
    data = BODY.encode()
    oid = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's own name
    return repo / ".git" / "objects" / oid[:2] / oid[2:]


def _session(tmp: Path) -> tuple[SessionConfig, RunGit, Path]:
    """A run whose spec commit holds the library, and one role session of it under the arm."""
    repo = tmp / "target"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name in ("knowledge/cross/standards.md", f"knowledge/{ROLE}/standards.md", SKILL):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(BODY if name == SKILL else "a standard\n")
    (repo / SPEC).parent.mkdir(parents=True, exist_ok=True)
    (repo / SPEC).write_text("the module\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "spec")
    run = RunGit(repo=repo, run_dir=tmp / "run", run_id="run-1")
    run.open_run_branch("main")
    worktree = run.open_subtask("s1")
    (run.run_dir / "run.json").write_text("{}\n")
    reverted, refused = session_protected_roots(run, tmp / "store", worktree, tmp / "install")
    given = loader.session_reading(ROLE, SPEC, skills="off")
    for d in ("state", "session", "config", "home"):
        (tmp / "outside" / d).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile="role",
        role=ROLE,
        worktree=str(worktree),
        own_branch=run.subtask_branch("s1"),
        store_root=str(tmp / "store"),
        state_dir=str(tmp / "outside" / "state"),
        target_dir=str(tmp / "outside" / "session"),
        claude_config_dir=str(tmp / "outside" / "config"),
        user_home=str(tmp / "outside" / "home"),
        token_ceiling=40960,
        required_reading=tuple(str(worktree / p) for p in given.required),
        always_loaded=tuple(str(worktree / p) for p in given.always_loaded),
        extra_protected=tuple(str(p) for p in reverted),
        extra_protected_refuse_only=tuple(str(p) for p in refused),
        sessions_root=str(run.run_dir / "sessions"),
        withheld=(str(run.run_dir / "run.json"), *(str(worktree / p) for p in given.withheld)),
    )
    return build_config(request, current_installation()), run, worktree


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.mark.parametrize(
    "command",
    [
        f"git show HEAD:{SKILL}",
        "git log -p",
        f"git cat-file -p HEAD:{SKILL}",
        "git show HEAD",
        f"git diff HEAD~0 -- {SKILL}",
    ],
)
def test_git_s_own_readers_are_refused_to_a_role_session(base: Path, command: str) -> None:
    config, _, worktree = _session(base)
    hook_input = HookInput.model_validate(bash(command, cwd=str(worktree)))
    decision = git_ops.pre_tool_use(hook_input, config)
    assert not decision.allow, f"a role session ran {command!r}"
    assert git_ops.ROLE_NO_GIT in decision.reason


def test_the_integration_worktree_s_copy_is_not_read_by_a_file_tool(base: Path) -> None:
    config, run, worktree = _session(base)
    copy = run.integration / SKILL
    assert copy.read_text() == BODY  # the copy is there, as the spec commit checked it out
    said = paths.protection(str(copy), str(worktree), config, writing=False)
    assert said is not None, "under skills: off a file tool reads the integration worktree's copy"


def test_the_integration_worktree_s_copy_is_not_read_by_a_shell_command(base: Path) -> None:
    config, run, worktree = _session(base)
    command = f"cat {run.integration / SKILL}"
    said = shell_paths.check(parse(command)[0], str(worktree), config)
    assert said is not None, "under skills: off a shell command reads the integration's copy"


def test_the_object_store_s_copy_is_not_read_by_a_shell_command(base: Path) -> None:
    config, run, worktree = _session(base)
    blob = _blob_path(run.repo)
    assert blob.is_file()  # the bytes are in the store, as the spec commit wrote them
    command = f"python3 -c \"import zlib; print(zlib.decompress(open('{blob}', 'rb').read()))\""
    said = shell_paths.check(parse(command)[0], str(worktree), config)
    assert said is not None, "under skills: off a shell command reads the object store's copy"


def test_the_os_layer_denies_every_copy_of_the_skill_file(base: Path) -> None:
    config, run, _ = _session(base)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-sk")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]

    def denied(path: Path) -> bool:
        return any(str(path) == d or str(path).startswith(d.rstrip("/") + "/") for d in deny)

    reachable = [p for p in (run.integration / SKILL, _blob_path(run.repo)) if not denied(p)]
    assert reachable == [], f"under skills: off the OS layer lets a command read {reachable}"
