"""A reviewer reads only beneath its allowance; no other session reads what only reviewers read.

The allowance is a list of what may be read, judged on the path as resolved: a
symlink inside it that points out is outside, and a file with a second name is
refused. Everything else, the harness checkout and any copy of a corpus
included, is refused because it is not on the list. The reviewer tree under
``knowledge/`` is withheld from every other session, by the file tools and the
shell alike, wherever the session's own checkout and the harness put it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import OUTSIDE_REVIEW_REASON, REVIEW_MATERIAL_REASON
from physgate.hooks.settings import InstallRequest, build_config, review_material
from physgate.hooks.settings import current_installation as installation


@pytest.fixture
def root(tmp_path: Path) -> Path:
    files = {
        "review/read/worktree/design/node.json": "{}\n",
        "review/read/transcript.md": "# transcript\n",
        "harness/corpora/set/a01.json": "{}\n",
        "harness/knowledge/reviewers/control/rubric.md": "# rubric\n",
        "harness/knowledge/control/standards.md": "# standards\n",
        "target/knowledge/reviewers/control/rubric.md": "# rubric copy\n",
        "target/knowledge/control/skill.md": "# skill\n",
    }
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    return tmp_path


def _reviewer(root: Path) -> SessionConfig:
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
            read_roots=(str(root / "review" / "read"),),
            harness_root=str(root / "harness"),
        ),
        installation(),
    )


def _role(root: Path, profile: str = "role") -> SessionConfig:
    return build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(root / "target"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "settings"),
            claude_config_dir=str(root / "outside" / "config"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            harness_root=str(root / "harness"),
        ),
        installation(),
    )


def _read(config: SessionConfig, target: str, cwd: Path) -> str:
    hook_input = HookInput.model_validate(
        event(tool_name="Read", cwd=str(cwd), tool_input={"file_path": target})
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _shell(config: SessionConfig, command: str, cwd: Path) -> str:
    decision = sp.pre_tool_use(HookInput.model_validate(bash(command, cwd=str(cwd))), config)
    return "allow" if decision.allow else decision.reason


def test_a_reviewer_reads_its_own_files(root: Path) -> None:
    config, cwd = _reviewer(root), root / "review" / "read" / "worktree"
    assert _read(config, "design/node.json", cwd) == "allow"
    assert _read(config, str(root / "review" / "read" / "transcript.md"), cwd) == "allow"
    assert _read(config, "../transcript.md", cwd) == "allow"


@pytest.mark.parametrize(
    "target",
    [
        "@/harness/corpora/set/a01.json",
        "../../../harness/corpora/set/a01.json",
        "@/harness/knowledge/reviewers/control/rubric.md",
        "@/review/session/settings/session-config.json",
        "@/review/read-not/x",
        "/etc/hosts",
    ],
    ids=["harness corpus", "relative escape", "harness rubric", "own settings", "prefix", "system"],
)
def test_everything_else_is_refused_to_a_reviewer(root: Path, target: str) -> None:
    told = _read(
        _reviewer(root), target.replace("@", str(root)), root / "review" / "read" / "worktree"
    )
    assert OUTSIDE_REVIEW_REASON in told


def test_a_symlink_in_the_allowance_that_points_out_is_outside(root: Path) -> None:
    link = root / "review" / "read" / "worktree" / "alias"
    link.symlink_to(root / "harness" / "corpora")
    told = _read(_reviewer(root), "alias/set/a01.json", link.parent)
    assert OUTSIDE_REVIEW_REASON in told


def test_a_symlink_that_stays_inside_is_inside(root: Path) -> None:
    link = root / "review" / "read" / "worktree" / "copy.md"
    link.symlink_to(root / "review" / "read" / "transcript.md")
    assert _read(_reviewer(root), "copy.md", link.parent) == "allow"


def test_a_case_variant_of_the_allowance_is_judged_as_the_allowance(root: Path) -> None:
    variant = str(root / "review" / "READ" / "transcript.md")
    told = _read(_reviewer(root), variant, root)
    # On a case-insensitive volume the variant is the file itself; on a sensitive one
    # it names nothing, and is outside. Either way nothing outside is reached.
    assert told == "allow" or OUTSIDE_REVIEW_REASON in told


def test_a_hard_link_in_the_allowance_is_refused(root: Path) -> None:
    os.link(root / "harness" / "corpora" / "set" / "a01.json", root / "review" / "read" / "a.json")
    told = _read(_reviewer(root), str(root / "review" / "read" / "a.json"), root)
    assert told == paths.REFUSED.format(
        path=str(root / "review" / "read" / "a.json"), reason=paths.HARD_LINKED, tool="Read"
    )


@pytest.mark.parametrize("profile", ["role", "orchestrator"])
@pytest.mark.parametrize(
    "target",
    [
        "@/harness/knowledge/reviewers/control/rubric.md",
        "@/target/knowledge/reviewers/control/rubric.md",
        "knowledge/reviewers/firmware/rubric.md",
        "@/harness/knowledge/reviewers",
    ],
    ids=["harness rubric", "own checkout's rubric", "a rubric not written yet", "the tree"],
)
def test_no_other_session_reads_reviewer_material(root: Path, profile: str, target: str) -> None:
    told = _read(_role(root, profile), target.replace("@", str(root)), root / "target")
    assert REVIEW_MATERIAL_REASON in told


@pytest.mark.parametrize(
    "command",
    [
        "cat @/harness/knowledge/reviewers/control/rubric.md",
        "grep -r indicator knowledge/reviewers",
        "ls knowledge/reviewers",
        "head -1 ./knowledge/../knowledge/reviewers/control/rubric.md",
    ],
)
def test_no_role_reads_reviewer_material_through_the_shell(root: Path, command: str) -> None:
    told = _shell(_role(root), command.replace("@", str(root)), root / "target")
    assert REVIEW_MATERIAL_REASON in told


def test_a_role_still_reads_its_own_library(root: Path) -> None:
    config = _role(root)
    assert (
        _read(config, str(root / "harness" / "knowledge" / "control" / "standards.md"), root)
        == "allow"
    )
    assert _read(config, "knowledge/control/skill.md", root / "target") == "allow"
    assert _shell(config, "cat knowledge/control/skill.md", root / "target") == "allow"


def test_the_withheld_tree_is_one_structural_rule(root: Path) -> None:
    assert _role(root).review_material == review_material(root / "target", root / "harness")
    assert review_material(root / "target", root / "harness") == (
        str(root / "harness" / "knowledge" / "reviewers"),
        str(root / "target" / "knowledge" / "reviewers"),
    )
    assert _reviewer(root).review_material == ()


def _request(root: Path, **fields: object) -> InstallRequest:
    base: dict[str, object] = {
        "profile": "reviewer",
        "role": None,
        "worktree": str(root / "review" / "read" / "worktree"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(root / "review" / "session" / "state"),
        "target_dir": str(root / "review" / "session" / "settings"),
        "claude_config_dir": str(root / "review" / "session" / "config"),
        "user_home": str(root / "review" / "session" / "home"),
        "token_ceiling": 1000,
        "read_roots": (str(root / "review" / "read"),),
    }
    return InstallRequest(**(base | fields))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"read_roots": ()}, "only beneath its read roots"),
        ({"profile": "role", "role": "control"}, "only beneath its read roots"),
        ({"read_roots": ("@/review",)}, "inside a reviewer's read allowance"),
    ],
    ids=["a reviewer with no allowance", "a role with one", "its own files inside it"],
)
def test_an_incoherent_allowance_is_refused_at_install(
    root: Path, fields: dict[str, object], match: str
) -> None:
    if "read_roots" in fields:
        fields["read_roots"] = tuple(str(r).replace("@", str(root)) for r in fields["read_roots"])  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match=match):
        build_config(_request(root, **fields), installation())


def test_the_review_root_is_withheld_from_every_other_session(root: Path) -> None:
    """Every packet under it holds a copy of a rubric, so no role reads or writes it."""
    review_root = root / "review"
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(root / "target"),
        own_branch=None,
        store_root=None,
        state_dir=str(root / "outside" / "state"),
        target_dir=str(root / "outside" / "settings"),
        claude_config_dir=str(root / "outside" / "config"),
        user_home=str(root / "outside" / "home"),
        token_ceiling=1000,
        harness_root=str(root / "harness"),
        extra_review_material=(str(review_root),),
    )
    config = build_config(request, installation())
    assert str(review_root) in config.review_material
    packet_rubric = str(review_root / "read" / "worktree" / "design" / "node.json")
    assert REVIEW_MATERIAL_REASON in _read(config, packet_rubric, root / "target")
    assert REVIEW_MATERIAL_REASON in _shell(config, f"cat {packet_rubric}", root / "target")
    hook_input = HookInput.model_validate(
        event(tool_name="Write", cwd=str(root / "target"), tool_input={"file_path": packet_rubric})
    )
    assert not paths.pre_tool_use(hook_input, config).allow
