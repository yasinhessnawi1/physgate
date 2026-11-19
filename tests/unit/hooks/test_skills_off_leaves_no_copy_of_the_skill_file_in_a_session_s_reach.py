"""Under ``skills: off`` no copy of the role's skill file is in a role session's reach.

Leaving the file out of what the session reads is not enough on its own if its bytes lie anywhere
the session can open: in its own worktree, in the checkout of the same commit in the
orchestrator's integration worktree, or in the target's object store, whose objects are files. So
under the arm decomposition never puts a skill file into the target. A role session runs no git,
so git's own readers are refused to it whatever the store holds; what is shown here is that no
other way leads to a copy, because there is none.

The run is started as decomposition starts one, from a plan, the fixture library and a target
repository, and the role session is installed as the dispatcher installs one: the run's protected
roots from the real target, its records withheld.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from hook_helpers import bash

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from design_review_rig import ROLES, config, outcome, target_repo  # noqa: E402
from knowledge_fixture import FIXTURE_ROLES, fixture_text, write_fixture  # noqa: E402
from orch_helpers import CLEAN_HARNESS  # noqa: E402

import physgate.hooks.git_ops as git_ops  # noqa: E402
from physgate.hooks import paths, shell_paths  # noqa: E402
from physgate.hooks.config import HookInput, SessionConfig  # noqa: E402
from physgate.hooks.settings import InstallRequest, build_config, current_installation  # noqa: E402
from physgate.hooks.shell import parse  # noqa: E402
from physgate.knowledge import loader  # noqa: E402
from physgate.orchestrator.decompose import start_run  # noqa: E402
from physgate.orchestrator.dispatch import session_protected_roots  # noqa: E402
from physgate.orchestrator.merge import RunGit  # noqa: E402

ROLE = ROLES[0]
SKILL = f"knowledge/{ROLE}/skill.md"
#: The skill file's bytes, as the library holds them.
BODY = fixture_text(Path(SKILL)).encode()


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's own name


def _session(tmp: Path) -> tuple[SessionConfig, RunGit, Path]:
    """A run started under the arm, and one role session of it, installed as the dispatcher does."""
    repo = target_repo(tmp)
    library = tmp / "library"
    write_fixture(library, (*FIXTURE_ROLES, *ROLES))
    assert (library / SKILL).read_bytes() == BODY  # the library holds the skill file
    run_dir = tmp / "run"
    the_config = config(repo, "off", skills="off", ablation=True, harness=CLEAN_HARNESS)
    start_run(
        outcome(run_dir), config=the_config, run_dir=run_dir, target_repo=repo, library=library
    ).close()
    run = RunGit(repo=repo, run_dir=run_dir, run_id=the_config.run_id)
    subtask = (run_dir / "ledger.jsonl").read_text().split('"id":"', 1)[1].split('"', 1)[0]
    worktree = run.open_subtask(subtask)
    reverted, refused = session_protected_roots(run, run_dir / "store", worktree, tmp / "install")
    spec = Path(".physgate/specs") / f"{subtask}.md"
    given = loader.session_reading(ROLE, spec, skills="off")
    for d in ("state", "session", "config", "home"):
        (tmp / "outside" / d).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile="role",
        role=ROLE,
        worktree=str(worktree),
        own_branch=run.subtask_branch(subtask),
        store_root=str(run_dir / "store"),
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
        withheld=(str(run.run_dir / "run.json"),),
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


def test_the_session_s_own_worktree_holds_no_copy(base: Path) -> None:
    _, _, worktree = _session(base)
    assert (worktree / f"knowledge/{ROLE}/standards.md").is_file()  # the specification commit
    assert not (worktree / SKILL).exists(), "under skills: off the session's worktree holds it"


def test_the_integration_worktree_s_checkout_holds_no_copy_for_a_file_tool(base: Path) -> None:
    config, run, worktree = _session(base)
    copy = run.integration / SKILL
    assert (run.integration / f"knowledge/{ROLE}/standards.md").is_file()
    assert not copy.exists(), "under skills: off the integration worktree's checkout holds it"
    # The hooks judge the place as they judge it under on: nothing is withheld there.
    assert paths.protection(str(copy), str(worktree), config, writing=False) is None


def test_the_integration_worktree_s_checkout_holds_no_copy_for_a_shell_command(
    base: Path,
) -> None:
    config, run, worktree = _session(base)
    found = sorted(run.integration.rglob(loader.SKILL_NAME))
    assert found == [], f"under skills: off a shell command finds {found}"
    command = f"cat {run.integration / SKILL}"
    assert shell_paths.check(parse(command)[0], str(worktree), config) is None


def test_the_object_store_holds_no_copy_for_a_shell_command(base: Path) -> None:
    _, run, _ = _session(base)
    oid = _blob(BODY)
    loose = run.repo / ".git" / "objects" / oid[:2] / oid[2:]
    assert not loose.exists(), "under skills: off the store holds the skill file as a loose object"
    listed = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=run.repo,
        input=oid + "\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert listed.strip().endswith("missing"), "under skills: off the store holds the skill file"


def test_no_file_a_command_could_open_by_a_path_built_at_run_time_holds_a_copy(
    base: Path,
) -> None:
    # The OS layer is the one judge of a path no hook sees: it is left as it is under on, so
    # what is shown is that no file in the run's places holds the bytes for it to judge.
    _, run, _ = _session(base)
    places = [run.run_dir, run.repo]
    held = [
        path
        for place in places
        for path in place.rglob("*")
        if path.is_file() and not path.is_symlink() and BODY in path.read_bytes()
    ]
    assert held == [], f"under skills: off a command that builds its path at run time reads {held}"
