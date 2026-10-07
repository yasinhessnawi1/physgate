"""A path is judged as the operating system will resolve it, not only as it is spelt.

Lexical normalisation reads ``link/..`` as the directory holding ``link``; the
kernel reads it as the parent of wherever ``link`` points. A check that judged
only the normalised spelling let ``link/../file`` name a file the kernel then
opened somewhere else entirely: a reviewer read outside its allowance, and a role
read of a rubric, with the hook allowing both. Every check now judges both
spellings and refuses if either is refused; the allowance holds only if both are
inside. A ``cd`` whose destination depends on which reading the shell uses is
refused, because the shell's mode cannot be known before it runs.

The cases that could not reach are kept beside the ones that could: a sibling
directory sharing the allowance's prefix, a trailing slash on a configured
root, a root of nothing but slashes, and ``~``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import GATE_REASON, OUTSIDE_REVIEW_REASON, REVIEW_MATERIAL_REASON
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

MARK = "@"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    files = {
        "review/read/worktree/design/node.json": "{}\n",
        "review/read-other/secret.md": "outside\n",
        "harness/corpora/set/a01.json": "{}\n",
        "harness/knowledge/reviewers/control/rubric.md": "# rubric\n",
        "target/src/physgate/gate/sub/keep.txt": "x\n",
        "target/src/physgate/gate/check.py": "x\n",
        "target/notes.md": "free\n",
    }
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    worktree = tmp_path / "review" / "read" / "worktree"
    (worktree / "alias").symlink_to(tmp_path / "harness" / "corpora" / "set")
    (tmp_path / "target" / "y").symlink_to(
        tmp_path / "harness" / "knowledge" / "reviewers" / "control"
    )
    (tmp_path / "target" / "g").symlink_to(
        tmp_path / "target" / "src" / "physgate" / "gate" / "sub"
    )
    (tmp_path / "target" / "home").mkdir()
    (tmp_path / "target" / "home" / "link").symlink_to(
        tmp_path / "harness" / "knowledge" / "reviewers" / "control"
    )
    return tmp_path


def _reviewer(root: Path, *read_roots: str) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile="reviewer",
            role=None,
            worktree=str(root / "review" / "read" / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "review" / "session" / "state"),
            target_dir=str(root / "review" / "session" / "settings"),
            claude_config_dir=str(root / "review" / "session" / "config"),
            user_home=str(root / "review" / "session" / "home"),
            token_ceiling=1000,
            read_roots=read_roots or (str(root / "review" / "read"),),
            harness_root=str(root / "harness"),
        ),
        installation(),
    )


def _role(root: Path) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile="role",
            role="control",
            worktree=str(root / "target"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "settings"),
            claude_config_dir=str(root / "outside" / "config"),
            user_home=str(root / "target" / "home"),
            token_ceiling=1000,
            harness_root=str(root / "harness"),
        ),
        installation(),
    )


def _tool(config: SessionConfig, tool: str, target: str, cwd: Path) -> str:
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=str(cwd), tool_input={"file_path": target})
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _shell(config: SessionConfig, command: str, cwd: Path) -> str:
    decision = sp.pre_tool_use(HookInput.model_validate(bash(command, cwd=str(cwd))), config)
    return "allow" if decision.allow else decision.reason


# -- what could reach before: each was allowed by the hook ---------------------------


def test_a_reviewer_cannot_leave_its_allowance_through_a_link_and_dot_dot(root: Path) -> None:
    worktree = root / "review" / "read" / "worktree"
    # Spelt, it is worktree/set/a01.json; resolved, it is the harness corpus.
    assert (worktree / "alias" / ".." / "set" / "a01.json").resolve() == (
        root / "harness" / "corpora" / "set" / "a01.json"
    ).resolve()
    told = _tool(_reviewer(root), "Read", "alias/../set/a01.json", worktree)
    assert OUTSIDE_REVIEW_REASON in told


def test_a_role_cannot_read_a_rubric_through_a_link_and_dot_dot(root: Path) -> None:
    told = _tool(_role(root), "Read", "y/../control/rubric.md", root / "target")
    assert REVIEW_MATERIAL_REASON in told


def test_a_role_cannot_cat_a_rubric_through_a_link_and_dot_dot(root: Path) -> None:
    told = _shell(_role(root), "cat y/../control/rubric.md", root / "target")
    assert REVIEW_MATERIAL_REASON in told


@pytest.mark.parametrize("cd", ["cd -P y/..", "cd y/..", "pushd y/..", "cd ./y/../"])
def test_a_cd_whose_destination_depends_on_the_reading_is_refused(root: Path, cd: str) -> None:
    told = _shell(_role(root), f"{cd} && cat control/rubric.md", root / "target")
    assert told != "allow"


def test_a_role_cannot_write_the_gate_through_a_link_and_dot_dot(root: Path) -> None:
    told = _tool(_role(root), "Write", "g/../check.py", root / "target")
    assert GATE_REASON in told


def test_tilde_is_expanded_before_it_is_resolved(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The hook runs with the session's own environment, so ``~`` is the session's
    # home for the shell and for the hook alike.
    monkeypatch.setenv("HOME", str(root / "target" / "home"))
    told = _shell(_role(root), "cat ~/link/../control/rubric.md", root / "target")
    assert REVIEW_MATERIAL_REASON in told


def test_a_relative_path_after_a_cd_is_judged_from_there(root: Path) -> None:
    told = _shell(_role(root), "cd home && cat link/../control/rubric.md", root / "target")
    assert REVIEW_MATERIAL_REASON in told


# -- what could not reach: kept so it stays that way ----------------------------------


def test_a_sibling_sharing_the_allowance_s_prefix_is_outside(root: Path) -> None:
    told = _tool(_reviewer(root), "Read", str(root / "review" / "read-other" / "secret.md"), root)
    assert OUTSIDE_REVIEW_REASON in told


def test_a_trailing_slash_on_a_configured_root_changes_nothing(root: Path) -> None:
    config = _reviewer(root, str(root / "review" / "read") + "/")
    worktree = root / "review" / "read" / "worktree"
    assert _tool(config, "Read", "design/node.json", worktree) == "allow"
    told = _tool(config, "Read", str(root / "review" / "read-other" / "secret.md"), worktree)
    assert OUTSIDE_REVIEW_REASON in told


def test_a_root_of_nothing_but_slashes_is_refused_at_install(root: Path) -> None:
    with pytest.raises(ValueError, match="names the whole filesystem"):
        _reviewer(root, "//")


def test_a_plain_cd_into_an_ordinary_directory_still_works(root: Path) -> None:
    assert _shell(_role(root), "cd src && cat ../notes.md", root / "target") == "allow"


def test_a_link_that_resolves_inside_stays_allowed(root: Path) -> None:
    worktree = root / "review" / "read" / "worktree"
    (worktree / "inner").symlink_to(worktree / "design")
    assert _tool(_reviewer(root), "Read", "inner/../design/node.json", worktree) == "allow"
