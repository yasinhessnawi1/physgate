"""The harness keeps its temporary stores in a place of its own, which no session reaches.

The orchestrator's change-check store, the review packet's store and index, the regeneration's
profile, the tier scan's scratch and the like are made beneath the harness process's own
directory (``oslayer.harness_temp``), a root every session is refused both ways. The directory's
parent is held to be this user's alone, and a forked child makes a directory of its own.

Every parent here is a stand-in under the test's own directory.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

import physgate
from physgate.oslayer import harness_temp

#: The harness's own modules that make temporary stores: each such call names the harness's
#: place, never the default temporary directory (shared with every session's commands).
HARNESS_STORE_MAKERS = (
    "orchestrator/git.py",
    "orchestrator/derived.py",
    "reviewers/packet.py",
    "oslayer/regeneration.py",
    "evaluation/tiers/exposure.py",
    "evaluation/observe/rerun.py",
    "evaluation/per_role/firmware/sandbox.py",
    "knowledge/law_promotion.py",
)
MAKERS = ("mkdtemp", "TemporaryDirectory", "mkstemp", "NamedTemporaryFile")


def _calls(module: str) -> list[tuple[int, str | None]]:
    """Each temporary store a module makes: its line, and what its ``dir`` names, in source."""
    path = Path(physgate.__file__).resolve().parent / module
    tree = ast.parse(path.read_text())
    found: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in MAKERS:
            named = [k.value for k in node.keywords if k.arg == "dir"]
            found.append((node.lineno, ast.unparse(named[0]) if named else None))
    return found


@pytest.mark.parametrize("module", HARNESS_STORE_MAKERS)
def test_every_store_the_harness_makes_is_made_in_its_own_place(module: str) -> None:
    calls = _calls(module)
    assert calls, f"{module} makes no temporary store any more: the list is stale"
    elsewhere = [(line, where) for line, where in calls if where != "harness_temp_dir()"]
    assert elsewhere == [], f"{module}: a store made outside the harness's place: {elsewhere}"


def test_a_parent_open_to_others_or_a_link_is_refused(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    loose = base / "loose"
    loose.mkdir()
    loose.chmod(0o755)
    with pytest.raises(OSError, match="alone"):
        harness_temp.harness_temp_dir(str(loose))
    (base / "real").mkdir(mode=0o700)
    (base / "linked").symlink_to(base / "real")
    with pytest.raises(OSError, match="alone"):
        harness_temp.harness_temp_dir(str(base / "linked"))
    assert list((base / "real").iterdir()) == [], "a directory was made through the link"
    own = base / "own"
    made = harness_temp.harness_temp_dir(str(own))
    assert made.parent == own and oct(own.stat().st_mode & 0o777) == "0o700"


def test_a_forked_child_makes_a_directory_of_its_own_and_leaves_its_parent_s(
    tmp_path: Path,
) -> None:
    parent = tmp_path.resolve() / "pgh"
    mine = harness_temp.harness_temp_dir(str(parent))
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:  # the child: says where its own directory is, and leaves
        os.close(read)
        try:
            os.write(write, str(harness_temp.harness_temp_dir(str(parent))).encode())
        finally:
            os._exit(0)
    os.close(write)
    with os.fdopen(read) as said:
        childs = Path(said.read())
    os.waitpid(pid, 0)
    assert childs != mine and childs.parent == mine.parent
    assert mine.is_dir(), "the child removed its parent's directory"
