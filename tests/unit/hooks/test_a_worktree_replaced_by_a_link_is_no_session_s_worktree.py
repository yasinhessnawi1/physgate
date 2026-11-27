"""A worktree whose path was renamed away and replaced is no worktree of the session's.

Every rule that opens "the worktree" names it by its path: the file tools' write bound, a root
withheld whole's exception, the sentinel's put-back. So a session that renamed its worktree's
directory away and left a link at its path (to another trial's run, a review packet, the
operator's home) would have the hooks read, write and put back wherever the link points. The
installer records the worktree's device and inode, and that its path is no link; every hook call
holds the path to them first and refuses every call where it is no longer that directory, before
the sentinel puts anything back.

Each session is installed by the real installer from the argument list its real spawner builds
and judged by the generated command's own entry point, after a real SessionStart and the required
reading (the write rule's own rows' rig). Inside the OS layer the rename itself is refused (the
real-client row ``test_a_role_session_runs_inside_the_os_layer.py``); these rows are the hooks'
own answer where nothing else stands behind them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from test_a_file_tool_writes_only_in_the_session_s_worktree import installed

from physgate.hooks import runtime
from physgate.hooks.config import SessionConfig

KINDS = ("role-in-the-layer", "role-hooks-only", "raw-trial", "raw-outside-a-round")
TARGETS = ("another run", "a review packet", "the operator's home", "another module's worktree")


def _target(s: object, to: str) -> tuple[Path, str]:
    lay = s.lay  # type: ignore[attr-defined]
    return {
        "another run": (lay.other, "run.json"),
        "a review packet": (lay.review / "r0123456789ab" / "read", "brief.md"),
        "the operator's home": (lay.home / "notes", "existing.txt"),
        "another module's worktree": (lay.run_dir / "worktrees" / "s2", "README.md"),
    }[to]


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.mark.parametrize("to", TARGETS)
@pytest.mark.parametrize("kind", KINDS)
def test_every_call_is_refused_and_nothing_is_put_back_through_a_link_at_the_worktree_s_path(
    kind: str, to: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    worktree = s.worktree
    (worktree / "notes.md").write_text("the session's own\n")
    code, said, _ = s.hooks.call(
        "PreToolUse", tool_name="Read", tool_input={"file_path": str(worktree / "notes.md")}
    )
    assert code == 0, said  # its own file reads, before anything moved
    target, existing = _target(s, to)
    before = _tree(target)
    os.rename(worktree, worktree.parent / "moved-away")
    os.symlink(target, worktree)
    calls = [
        (
            "PreToolUse",
            {"tool_name": "Read", "tool_input": {"file_path": str(worktree / existing)}},
        ),
        (
            "PreToolUse",
            {"tool_name": "Read", "tool_input": {"file_path": str(worktree / existing)}},
        ),
        (
            "PreToolUse",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(worktree / "new.txt"), "content": "x\n"},
            },
        ),
        (
            "PreToolUse",
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(worktree / existing),
                    "old_string": "a",
                    "new_string": "b",
                },
            },
        ),
        ("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": f"cat {existing}"}}),
        (
            "PostToolUse",
            {"tool_name": "Bash", "tool_input": {"command": "true"}, "tool_response": {}},
        ),
        ("Stop", {}),
    ]
    told = []
    for event, fields in calls:
        code, said, logged = s.hooks.call(event, **fields)
        told.append((event, fields.get("tool_name"), code, said[:200]))
        assert code != 0 and runtime.WORKTREE_MOVED in said, told
        assert any(json.loads(line).get("hook") == "worktree" for line in logged), logged
    # Nothing was put back into, or moved aside out of, wherever the link points.
    assert _tree(target) == before


@pytest.mark.parametrize("kind", ("role-in-the-layer", "raw-trial"))
def test_another_directory_left_at_the_worktree_s_path_is_no_worktree_either(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    worktree = s.worktree
    os.rename(worktree, worktree.parent / "moved-away")
    worktree.mkdir()
    (worktree / "x.txt").write_text("a\n")
    code, said, _ = s.hooks.call(
        "PreToolUse", tool_name="Read", tool_input={"file_path": str(worktree / "x.txt")}
    )
    assert code != 0 and runtime.WORKTREE_MOVED in said, said


def test_the_install_records_the_worktree_s_identity_and_refuses_a_worktree_that_is_a_link(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed("role-in-the-layer", outside_tmp, monkeypatch)
    recorded = s.hooks.config.worktree_identity
    st = os.lstat(s.worktree)
    assert recorded is not None
    assert (recorded.device, recorded.inode) == (st.st_dev, st.st_ino)
    from physgate.hooks.settings import worktree_identity

    link = outside_tmp / "worktree-link"
    link.symlink_to(s.worktree)
    with pytest.raises(ValueError, match="is a link"):
        worktree_identity(str(link))
    assert worktree_identity(str(outside_tmp / "not-made-yet")) is None


def test_a_configuration_written_before_the_identity_still_reads_and_holds_nothing_here(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    raw = json.loads(s.hooks.config.model_dump_json())
    raw.pop("worktree_identity")
    earlier = SessionConfig.model_validate_json(json.dumps(raw))
    assert earlier.worktree_identity is None
    assert not runtime.worktree_moved(earlier)
