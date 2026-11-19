"""A file in the session's worktree that has a second name on disk is refused to every read.

A hard link is the same file under another name: nothing about the name says which file it is.
A link made in the worktree to a file the session may not read (the harness's skill file, a
held-out scenario, the hooks' own records, a withheld run record) would hand a file tool that
file under a name in the worktree, where every root test passes, since the inode test compares
directories only. So a read of a regular file with more than one link in the worktree is
refused, by a file tool and by a shell command's word alike, whatever the other name is.

Only the worktree: it is the one place every session's commands write on every layer, and a
worktree's own files (its checkout, what the session wrote) have one name each. Outside it a
session reads files that have more than one name for reasons of their own, an interpreter's
packages hard-linked from a package cache among them, and those stay readable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from test_the_harness_checkout_is_protected import _harness, _request, _shell_decision

from physgate.hooks.paths import protection
from physgate.hooks.settings import build_config, current_installation

#: The words the refusal says, built from what it must name: the file's second name.
SECOND_NAME = "more than one name"


def _config(tmp: Path, *, layer: bool, profile: str = "role", hooks: str = "on") -> Any:  # noqa: ANN401
    """A session of ``profile`` with the harness, a held-out tier and a withheld record named."""
    harness = _harness(tmp)
    held = tmp / "held"
    held.mkdir(exist_ok=True)
    (held / "scenario.json").write_text("a held-out scenario\n")
    run = tmp / "run"
    run.mkdir(exist_ok=True)
    (run / "run.json").write_text("{}\n")
    temp = str(tmp / "pg-1")
    fields: dict[str, Any] = {"os_layer_temp_dir": temp} if layer else {"temp_dir": temp}
    if profile != "role":
        fields |= {"role": None, "own_branch": None, "store_root": None}
        fields["sessions_root"] = str(tmp / "sessions")
    request = _request(
        tmp,
        profile=profile,
        hooks=hooks,
        harness_root=str(harness),
        held_out=(str(held),),
        withheld=(str(run / "run.json"),),
        **fields,
    )
    return build_config(request, current_installation())


def _denied(tmp: Path) -> dict[str, Path]:
    """A file under each kind of root a session may not read."""
    return {
        "the harness's skill file": tmp / "harness" / "knowledge" / "control" / "skill.md",
        "a held-out scenario": tmp / "held" / "scenario.json",
        "a withheld run record": tmp / "run" / "run.json",
        "an ordinary file elsewhere": _ordinary(tmp),
    }


def _ordinary(tmp: Path) -> Path:
    path = tmp / "elsewhere" / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("notes\n")
    return path


def _linked(tmp: Path, source: Path, name: str = "hl.md") -> Path:
    link = tmp / "worktree" / "modules" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, link)
    return link


ARMS = [
    pytest.param(False, "role", "on", id="role-without-the-layer"),
    pytest.param(True, "role", "on", id="role-inside-the-layer"),
    pytest.param(False, "role", "off", id="role-hooks-off"),
    pytest.param(False, "baseline", "on", id="raw-agent"),
]


@pytest.mark.parametrize(("layer", "profile", "hooks"), ARMS)
@pytest.mark.parametrize(
    "what",
    [
        "the harness's skill file",
        "a held-out scenario",
        "a withheld run record",
        "an ordinary file elsewhere",
    ],
)
def test_a_file_tool_is_refused_a_file_with_a_second_name_in_the_worktree(
    tmp_path: Path, layer: bool, profile: str, hooks: str, what: str
) -> None:
    config = _config(tmp_path, layer=layer, profile=profile, hooks=hooks)
    link = _linked(tmp_path, _denied(tmp_path)[what])
    reason = protection(str(link), str(tmp_path / "worktree"), config, writing=False)
    assert reason is not None, f"a file tool reads {what} through a second name in the worktree"
    if what != "a withheld run record":
        # A withheld record is known by its identity on disk too, and refused for itself.
        assert SECOND_NAME in reason, reason


@pytest.mark.parametrize("layer", [False, True], ids=["without the layer", "inside the layer"])
def test_a_command_is_refused_a_file_with_a_second_name_in_the_worktree(
    tmp_path: Path, layer: bool
) -> None:
    config = _config(tmp_path, layer=layer)
    _linked(tmp_path, _denied(tmp_path)["the harness's skill file"])
    cwd = str(tmp_path / "worktree")
    for command in ("cat modules/hl.md", f"cat {cwd}/modules/hl.md", "cd modules && head hl.md"):
        decision = _shell_decision(config, cwd, command)
        assert not decision.allow, f"a command reads a second name in the worktree: {command}"
        assert SECOND_NAME in decision.reason, decision.reason


def test_a_worktree_s_own_files_have_one_name_each_and_are_read(tmp_path: Path) -> None:
    config = _config(tmp_path, layer=False)
    own = tmp_path / "worktree" / "modules" / "drive.py"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("x = 1\n")
    assert own.stat().st_nlink == 1
    assert protection(str(own), str(tmp_path / "worktree"), config, writing=False) is None


def test_a_file_with_a_second_name_outside_the_worktree_is_still_read(tmp_path: Path) -> None:
    # An interpreter's packages, hard-linked from a package cache as a package installer links
    # them: both names lie outside the worktree, and a session reads them as it always did.
    config = _config(tmp_path, layer=False)
    cache = tmp_path / "cache" / "numpy" / "__init__.py"
    cache.parent.mkdir(parents=True)
    cache.write_text("# numpy\n")
    installed = tmp_path / "env" / "lib" / "site-packages" / "numpy" / "__init__.py"
    installed.parent.mkdir(parents=True)
    os.link(cache, installed)
    assert installed.stat().st_nlink == 2
    assert protection(str(installed), str(tmp_path / "worktree"), config, writing=False) is None


def test_a_link_from_outside_the_worktree_to_a_file_with_a_second_name_in_it_is_refused(
    tmp_path: Path,
) -> None:
    # A symbolic link elsewhere names the worktree's file: judged where it lands.
    config = _config(tmp_path, layer=False)
    link = _linked(tmp_path, _ordinary(tmp_path))
    pointer = tmp_path / "elsewhere" / "pointer.md"
    pointer.symlink_to(link)
    reason = protection(str(pointer), str(tmp_path / "worktree"), config, writing=False)
    assert reason is not None and SECOND_NAME in reason, reason
