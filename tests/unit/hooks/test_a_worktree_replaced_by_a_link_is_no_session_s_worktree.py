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
from test_a_file_tool_writes_only_in_the_session_s_worktree import SID, installed

from physgate.hooks import runtime, sentinel
from physgate.hooks.config import SessionConfig
from physgate.hooks.lean import parse_input

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


@pytest.mark.parametrize("to", TARGETS)
def test_the_sentinel_puts_nothing_back_through_a_link_made_after_the_call_was_checked(
    to: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A swap between the entry point's check and the sentinel's put-back: the sentinel opens the
    # worktree itself, no link followed, holds it to its identity, and writes only relative to
    # it. Here the protected entries it would put back are gone from the moved worktree's place.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    worktree = s.worktree
    target, _ = _target(s, to)
    before = _tree(target)
    os.rename(worktree, worktree.parent / "moved-away")
    os.symlink(target, worktree)
    stdin = json.dumps(
        {
            "session_id": SID,
            "cwd": str(worktree),
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": str(worktree / "x")},
        }
    )
    decision = sentinel.check(parse_input(stdin), s.hooks.config)
    assert not decision.allow
    assert sentinel.WORKTREE_NOT_HELD in decision.reason, decision.reason
    assert _tree(target) == before


def test_a_parent_swapped_for_a_link_to_a_tree_with_a_directory_of_that_name_is_refused(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    worktree = s.worktree
    parent = worktree.parent
    decoy = outside_tmp / "decoy" / parent.name
    (decoy / worktree.name).mkdir(parents=True)
    (decoy / worktree.name / "x.txt").write_text("a\n")
    os.rename(parent, parent.with_name(parent.name + "-moved"))
    os.symlink(decoy, parent)
    code, said, _ = s.hooks.call(
        "PreToolUse", tool_name="Read", tool_input={"file_path": str(worktree / "x.txt")}
    )
    assert code != 0 and runtime.WORKTREE_MOVED in said, said


def test_the_same_directory_reached_through_a_linked_parent_is_still_the_worktree(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The parent renamed away and a link to it left at its path: the worktree's path still leads
    # to the very directory recorded, so its own files read and write there, and nothing else is
    # reached that the session could not reach before.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    worktree = s.worktree
    parent = worktree.parent
    moved = parent.with_name(parent.name + "-moved")
    os.rename(parent, moved)
    os.symlink(moved, parent)
    code, said, _ = s.hooks.write("Write", str(worktree / "kept.txt"))
    assert code == 0, said
    assert not runtime.worktree_moved(s.hooks.config)


@pytest.mark.parametrize("kind", ("role-in-the-layer", "role-hooks-only"))
def test_nothing_outside_the_session_s_home_is_put_back_through_a_link_above_a_root_in_it(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A put-back root two levels beneath the session's home (git's own configuration), and the
    # level between made a link to another directory that holds an entry of the root's name: the
    # sentinel runs outside the sandbox, so what it moves aside or writes there, no command of the
    # session could have reached.
    import shutil

    s = installed(kind, outside_tmp, monkeypatch)
    config = s.hooks.config
    nested = [
        Path(r.path)
        for r in config.protected_roots
        if r.watch == "revert" and r.path.endswith("/.config/git")
    ]
    assert nested, [r.path for r in config.protected_roots]
    root = nested[0]
    other = s.lay.home / "operator-config"
    (other / root.name).mkdir(parents=True)
    (other / root.name / "config").write_text("[user]\n\tname = the operator\n")
    before = _tree(other)
    if root.parent.is_dir() and not root.parent.is_symlink():
        shutil.rmtree(root.parent)
    os.symlink(other, root.parent)
    own = s.worktree / "notes.md"
    own.write_text("the session's own\n")
    told = []
    for _ in range(2):
        code, said, _ = s.hooks.call(
            "PreToolUse", tool_name="Read", tool_input={"file_path": str(own)}
        )
        told.append((code, said[:300]))
    assert _tree(other) == before, told
    assert (other / root.name / "config").read_text() == "[user]\n\tname = the operator\n"


@pytest.mark.parametrize("kind", ("role-in-the-layer", "raw-trial"))
def test_a_link_to_the_very_worktree_left_at_its_path_is_no_worktree_either(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The device and inode it leads to are the recorded ones: only its being a link tells it.
    s = installed(kind, outside_tmp, monkeypatch)
    worktree = s.worktree
    moved = worktree.parent / "moved-away"
    os.rename(worktree, moved)
    os.symlink(moved, worktree)
    code, said, _ = s.hooks.call(
        "PreToolUse", tool_name="Read", tool_input={"file_path": str(worktree / "x.txt")}
    )
    assert code != 0 and runtime.WORKTREE_MOVED in said, said


@pytest.mark.parametrize("kind", ("role-in-the-layer", "raw-trial"))
def test_a_worktree_whose_path_is_gone_altogether_refuses_every_call(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    os.rename(s.worktree, s.worktree.parent / "moved-away")
    code, said, _ = s.hooks.call(
        "PreToolUse", tool_name="Read", tool_input={"file_path": str(s.worktree / "x.txt")}
    )
    assert code != 0 and runtime.WORKTREE_MOVED in said, said


def _protected_in_the_worktree(s: object) -> Path:
    """A put-back root beneath the session's worktree, as its configuration names it."""
    config = s.hooks.config  # type: ignore[attr-defined]
    top = str(s.worktree)  # type: ignore[attr-defined]
    roots = [
        Path(r.path)
        for r in config.protected_roots
        if r.watch == "revert" and r.path.startswith(top + "/")
    ]
    assert roots, [r.path for r in config.protected_roots]
    return sorted(roots)[0]


def _sentinel_call(s: object) -> object:
    worktree = s.worktree  # type: ignore[attr-defined]
    stdin = json.dumps(
        {
            "session_id": SID,
            "cwd": str(worktree),
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": str(worktree / "x")},
        }
    )
    return sentinel.check(parse_input(stdin), s.hooks.config)  # type: ignore[attr-defined]


def test_another_directory_at_the_worktree_s_path_after_the_entry_check_gets_nothing_put_back(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not a link: a directory of its own, renamed in after the entry point held the path.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    root = _protected_in_the_worktree(s)
    worktree = s.worktree
    other = worktree.parent / "another"
    (other / root.relative_to(worktree)).mkdir(parents=True)
    planted = other / root.relative_to(worktree) / "theirs.txt"
    planted.write_text("another directory's own file\n")
    os.rename(worktree, worktree.parent / "moved-away")
    os.rename(other, worktree)
    decision = _sentinel_call(s)
    assert not decision.allow  # type: ignore[attr-defined]
    assert sentinel.WORKTREE_NOT_HELD in decision.reason  # type: ignore[attr-defined]
    assert (worktree / root.relative_to(s.worktree) / "theirs.txt").read_text() == (
        "another directory's own file\n"
    )


def test_a_swap_between_the_hold_and_the_put_back_puts_back_in_the_held_directory(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sentinel holds the worktree, and then the path is swapped: what it puts back lands in
    # the directory it holds, named relative to it, and the directory now at the path is left.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    root = _protected_in_the_worktree(s)
    worktree = s.worktree
    inside = root.relative_to(worktree)
    (root).mkdir(parents=True, exist_ok=True)
    (root / "planted.txt").write_text("the session's write to a protected place\n")
    other = worktree.parent / "another"
    (other / inside).mkdir(parents=True)
    (other / inside / "planted.txt").write_text("another directory's own file\n")
    moved = worktree.parent / "moved-away"
    real = sentinel._hold_worktree

    def held_then_swapped(config: object) -> int | None:
        fd = real(config)  # type: ignore[arg-type]
        os.rename(worktree, moved)
        os.rename(other, worktree)
        return fd

    monkeypatch.setattr(sentinel, "_hold_worktree", held_then_swapped)
    _sentinel_call(s)
    assert (worktree / inside / "planted.txt").read_text() == "another directory's own file\n"
    assert not (moved / inside / "planted.txt").exists(), "nothing was put back where it was held"
