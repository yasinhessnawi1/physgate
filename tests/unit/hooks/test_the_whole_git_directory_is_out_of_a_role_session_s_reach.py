"""A role session can write nothing in the target repository's git directory.

A role session runs no git: the orchestrator stages, commits and merges its work. So the whole
common git directory is protected for it (objects, refs, ``packed-refs``, ``shallow``, ``HEAD``,
``index``, every worktree's admin directory with its ``commondir``, ``gitdir``, ``HEAD`` and
``index``), and so is each worktree's ``.git`` pointer file. A file tool's write to any of it is
refused before it happens, and a write made any other way is put back by the sentinel at the next
hook, recorded as ``put back``: a changed file restored from the bytes kept when the session
started, anything new moved aside. Existing object files, packs, their indexes, the multi-pack
index and the commit graph are held byte for byte that way.

The run's graph store is a repository of its own, which the orchestrator commits after an
attempt is applied; its git directory is put back the same way, so its config and its
``info/attributes`` (which git reads whatever attribute source it is given) stay as they were.

The protected set is the one the dispatcher passes the installer
(:func:`session_protected_roots`), built into the session configuration by the installer's own
function.

Inert markers only: the git directory is a fresh one; a byte is appended to an object file, a
``commondir`` names an empty decoy directory, a ``shallow`` file and a ``packed-refs`` line name
commits that exist, and nothing is configured that runs a program.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from hook_helpers import SESSION, bash, event, make_store

from physgate.hooks import paths, sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.state import LOG_NAME
from physgate.orchestrator.dispatch import session_protected_roots
from physgate.orchestrator.git import commit_all, common_dir, init_repo
from physgate.orchestrator.merge import RunGit

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@dataclass(frozen=True)
class Layout:
    """A run's repository as a session finds it, and the session's configuration."""

    root: Path
    run: RunGit
    common: Path
    worktree: Path
    other: Path
    config: SessionConfig

    def admin(self, worktree: Path) -> Path:
        return Path((worktree / ".git").read_text().removeprefix("gitdir:").strip())


def _layout(tmp_path: Path) -> Layout:
    """A repository with packs, a multi-pack index, a commit graph and loose objects too.

    The run's integration worktree and two subtask worktrees exist, as they do when the second
    subtask's session starts; the session is the first subtask's.
    """
    repo = tmp_path / "repo"
    (repo / "m1").mkdir(parents=True)
    (repo / "m2").mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "m1" / "a.txt").write_text("0\n")
    (repo / "m2" / "b.txt").write_text("0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    _git(repo, "repack", "-a", "-d", "-q")
    _git(repo, "multi-pack-index", "write")
    _git(repo, "commit-graph", "write", "--reachable")
    (repo / "m1" / "a.txt").write_text("loose\n")
    _git(repo, "commit", "-q", "-am", "loose objects")
    _git(repo, "pack-refs", "--all")
    start = _git(repo, "rev-parse", "HEAD")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    other = run.open_subtask("m2")
    worktree = run.open_subtask("m1")
    # The graph store as decomposition leaves it: written, then committed in its own repository.
    store = run.run_dir / "store"
    make_store(store)
    init_repo(store)
    commit_all(store, "interface nodes\n")
    reverted, refused = session_protected_roots(run, store, worktree, tmp_path / "install")
    outside = tmp_path / "outside"
    config = build_config(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(worktree),
            own_branch=run.subtask_branch("m1"),
            store_root=str(store),
            state_dir=str(outside / "state"),
            target_dir=str(outside / "session"),
            claude_config_dir=str(outside / "cfg"),
            user_home=str(outside / "home"),
            token_ceiling=1000,
            extra_protected=tuple(str(p) for p in reverted),
            extra_protected_refuse_only=tuple(str(p) for p in refused),
        ),
        installation(),
    )
    return Layout(tmp_path, run, common_dir(repo), worktree, other, config)


def _loose(common: Path) -> Path:
    found = sorted(p for p in (common / "objects").glob("??/*") if p.is_file())
    assert found, "the layout holds loose objects"
    return found[0]


def _pack_file(suffix: str) -> Callable[[Layout], Path]:
    def find(layout: Layout) -> Path:
        found = sorted((layout.common / "objects" / "pack").glob(f"*{suffix}"))
        assert found, suffix
        return found[0]

    return find


#: Each newly protected place: how to find the path a session would write.
EXISTING: dict[str, Callable[[Layout], Path]] = {
    "a loose object": lambda layout: _loose(layout.common),
    "a pack": _pack_file(".pack"),
    "a pack index": _pack_file(".idx"),
    "the multi-pack index": lambda layout: layout.common / "objects/pack/multi-pack-index",
    "the commit graph": lambda layout: layout.common / "objects/info/commit-graph",
    "packed-refs": lambda layout: layout.common / "packed-refs",
    "HEAD": lambda layout: layout.common / "HEAD",
    "the index": lambda layout: layout.common / "index",
    "a branch's loose ref": lambda layout: (
        layout.common / "refs" / "heads" / layout.run.subtask_branch("m1")
    ),
    "a reflog": lambda layout: layout.common / "logs" / "HEAD",
    "the session worktree's commondir": lambda layout: layout.admin(layout.worktree) / "commondir",
    "the session worktree's gitdir": lambda layout: layout.admin(layout.worktree) / "gitdir",
    "the session worktree's HEAD": lambda layout: layout.admin(layout.worktree) / "HEAD",
    "the session worktree's index": lambda layout: layout.admin(layout.worktree) / "index",
    "another worktree's commondir": lambda layout: layout.admin(layout.other) / "commondir",
    "the integration worktree's commondir": lambda layout: (
        layout.admin(layout.run.integration) / "commondir"
    ),
    "the session worktree's .git pointer": lambda layout: layout.worktree / ".git",
    "another worktree's .git pointer": lambda layout: layout.other / ".git",
}
#: Each newly protected place a session could add a file to.
NEW: dict[str, Callable[[Layout], Path]] = {
    "a shallow file": lambda layout: layout.common / "shallow",
    "an alternates file": lambda layout: layout.common / "objects/info/alternates",
    "a new loose object": lambda layout: layout.common / "objects" / "ff" / ("0" * 38),
    "a new ref": lambda layout: layout.common / "refs/heads/planted",
    "a worktree admin directory": lambda layout: layout.common / "worktrees/planted/commondir",
}


def _marker(layout: Layout, name: str, path: Path) -> bytes:
    """The inert content each write leaves: a decoy path, a known commit, or one byte more."""
    decoy = layout.root / "decoy"
    decoy.mkdir(exist_ok=True)
    head = _git(layout.run.repo, "rev-parse", "HEAD~1")
    if path.name == "commondir":
        return f"{decoy}\n".encode()
    if path.name == "gitdir":
        return f"{decoy / '.git'}\n".encode()
    if path.name == ".git":
        return f"gitdir: {decoy}\n".encode()
    if name in ("a shallow file", "a new ref", "HEAD", "a branch's loose ref"):
        return f"{head}\n".encode()
    if name == "packed-refs":
        return path.read_bytes() + f"{head} refs/heads/planted\n".encode()
    if name == "an alternates file":
        return f"{decoy}\n".encode()
    return (path.read_bytes() if path.exists() else b"") + b"\0"


def _shell_write(path: Path, data: bytes) -> None:
    """A write as a shell command makes it: the file's mode does not stop its owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    path.write_bytes(data)


def _check(layout: Layout, name: str = "PostToolUse") -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=str(layout.worktree)) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, layout.config)
    return "allow" if decision.allow else decision.reason


def _log(layout: Layout) -> list[dict[str, object]]:
    path = Path(layout.config.state_dir) / LOG_NAME
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _quarantine(layout: Layout) -> list[str]:
    q = Path(layout.config.state_dir) / "sessions" / SESSION / "sentinel" / "quarantine"
    return sorted(p.name for p in q.iterdir()) if q.exists() else []


def _file_tool(layout: Layout, tool: str, path: Path) -> str | None:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(tool_name=tool, tool_input={key: str(path)}, cwd=str(layout.worktree))
    )
    decision = paths.pre_tool_use(hook_input, layout.config)
    return None if decision.allow else decision.reason


@pytest.mark.parametrize("name", sorted({**EXISTING, **NEW}))
def test_a_file_tool_write_into_the_git_directory_is_refused(tmp_path: Path, name: str) -> None:
    layout = _layout(tmp_path)
    path = {**EXISTING, **NEW}[name](layout)
    for tool in ("Write", "Edit", "NotebookEdit"):
        assert _file_tool(layout, tool, path) is not None, (tool, path)
    # Reading stays allowed, and an ordinary file of the worktree is written as before.
    assert paths.protection(str(path), str(layout.worktree), layout.config, writing=False) is None
    assert _file_tool(layout, "Write", layout.worktree / "m1" / "new.py") is None


@pytest.mark.parametrize("name", sorted(EXISTING))
def test_a_change_to_the_git_directory_is_put_back(tmp_path: Path, name: str) -> None:
    layout = _layout(tmp_path)
    path = EXISTING[name](layout)
    assert path.is_file(), path
    before, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
    assert _check(layout, "SessionStart") == "allow"
    _shell_write(path, _marker(layout, name, path))
    assert path.read_bytes() != before
    reason = _check(layout)
    assert reason.startswith("Protected paths changed"), reason
    assert str(path) in reason
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == mode
    record = _log(layout)[-1]
    assert (record["hook"], record["decision"]) == ("sentinel", "put back")
    assert str(path) in record["paths"]  # type: ignore[operator]
    # Put back once; the next hook finds nothing to do.
    assert _check(layout) == "allow"


@pytest.mark.parametrize("name", sorted(NEW))
def test_a_file_added_to_the_git_directory_is_moved_aside(tmp_path: Path, name: str) -> None:
    layout = _layout(tmp_path)
    path = NEW[name](layout)
    assert not path.exists(), path
    assert _check(layout, "SessionStart") == "allow"
    _shell_write(path, _marker(layout, name, path))
    reason = _check(layout)
    assert reason.startswith("Protected paths changed"), reason
    assert not path.exists()
    assert _quarantine(layout), "kept as evidence, not deleted"
    assert _log(layout)[-1]["decision"] == "put back"
    assert _check(layout) == "allow"


def test_a_session_that_leaves_the_git_directory_alone_is_never_refused(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    assert _check(layout, "SessionStart") == "allow"
    # The session's own work, and what the binary's read-only git leaves: nothing.
    (layout.worktree / "m1" / "a.txt").write_text("the session's change\n")
    _git(layout.worktree, "--no-optional-locks", "status", "--short")
    for event_name in ("PreToolUse", "PostToolUse", "Stop", "SessionEnd"):
        assert _check(layout, event_name) == "allow"
    assert [r for r in _log(layout) if r.get("hook") == "sentinel"] == []


def _tree_bytes(directory: Path) -> dict[str, bytes | None]:
    """Every path under ``directory``, with a file's bytes."""
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in sorted(directory.rglob("*"))
    }


#: A role's write into the graph store's git directory: the store's config gains a filter
#: definition naming a program that does not exist, and ``info/attributes`` selects it.
STORE_WRITES = {
    "config": b'[filter "planted"]\n\tclean = /nonexistent/planted-marker\n',
    "info/attributes": b"* filter=planted\n",
}


@pytest.mark.parametrize("name", sorted(STORE_WRITES))
def test_a_write_into_the_graph_store_s_git_directory_is_put_back(
    tmp_path: Path, name: str
) -> None:
    layout = _layout(tmp_path)
    git_dir = layout.run.run_dir / "store" / ".git"
    path = git_dir / name
    assert _file_tool(layout, "Write", path) is not None
    before = _tree_bytes(git_dir)
    assert _check(layout, "SessionStart") == "allow"
    _shell_write(path, (path.read_bytes() if path.exists() else b"") + STORE_WRITES[name])
    reason = _check(layout)
    assert reason.startswith("Protected paths changed"), reason
    assert str(path) in reason
    assert _tree_bytes(git_dir) == before
    assert _log(layout)[-1]["decision"] == "put back"
    assert _check(layout) == "allow"
