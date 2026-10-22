"""Through the real binary: inside the OS layer, no shell command writes a node proposal.

A node reaches the graph as a proposal the Write or Edit tool writes, checked by the
hooks before it exists. The hooks refuse a command that names the proposals
directory, but each command here reaches it without naming it: it copies or moves a
directory of its own into place, builds the path as it runs, or moves the directory
above the proposals away and makes its own. Every proposal it would land is one the
hooks refuse from the file tools (a cross node a domain role may not write, or a new
interface node). With the OS layer none lands; without it each does, which shows the
commands work. The file tools still write a proposal inside the layer, and a command
still reads one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

from physgate.hooks import graph

pytestmark = pytest.mark.integration

LANDED = "electrical.supply.json"


def _node(node_id: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": node_id,
        "kind": "component",
        "domain": "cross",
        "owner_role": "electrical",
        "quantities": {
            "stall_current": {
                "value": 2.4,
                "unit": "A",
                "source": "datasheet",
                "written_by": "electrical",
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-25T00:00:00Z",
    }
    base.update(fields)
    return base


CROSS = json.dumps(_node("electrical.supply"))


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


def _stage(layout: Layout) -> dict[str, object]:
    staged = layout.worktree / "stage" / graph.PROPOSALS_DIR / LANDED
    return tool("Write", file_path=str(staged), content=CROSS)


def _staged_file(layout: Layout) -> dict[str, object]:
    return tool("Write", file_path=str(layout.worktree / "staged.txt"), content=CROSS)


#: Each form, as the steps that make it: none names the proposals directory as the hooks read.
FORMS = {
    "copy-a-staged-directory": lambda w: [
        _stage(w),
        tool("Bash", command="cp -R stage/.physgate ."),
    ],
    "move-a-staged-directory": lambda w: [_stage(w), tool("Bash", command="mv stage/.physgate ./")],
    "move-a-file-by-a-built-path": lambda w: [
        _stage(w),
        tool(
            "Bash",
            command=(
                "d=$(printf %s .phys)gate/proposals; mkdir -p $d; "
                f"mv stage/{graph.PROPOSALS_DIR}/{LANDED} $d/"
            ),
        ),
    ],
    "a-path-built-at-run-time": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, shutil\n"
                "d = os.path.join('.phys' + 'gate', 'propo' + 'sals')\n"
                "os.makedirs(d, exist_ok=True)\n"
                f"shutil.copy('staged.txt', os.path.join(d, {LANDED!r}))"
            ),
        ),
    ],
    "the-directory-above-moved-away": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, shutil\n"
                "top = '.phys' + 'gate'\n"
                "if os.path.exists(top):\n    os.rename(top, 'old')\n"
                "os.makedirs(os.path.join(top, 'propo' + 'sals'))\n"
                f"shutil.copy('staged.txt', os.path.join(top, 'propo' + 'sals', {LANDED!r}))"
            ),
        ),
    ],
    "the-directory-removed-and-made-again": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, shutil\n"
                "d = os.path.join('.phys' + 'gate', 'propo' + 'sals')\n"
                "shutil.rmtree(d, ignore_errors=True)\n"
                "os.makedirs(d, exist_ok=True)\n"
                f"shutil.copy('staged.txt', os.path.join(d, {LANDED!r}))"
            ),
        ),
    ],
}


def _landed(layout: Layout) -> bool:
    return (layout.worktree / graph.PROPOSALS_DIR / LANDED).exists()


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("form", list(FORMS))
def test_with_the_layer_no_command_lands_a_proposal(layout: Layout, form: str) -> None:
    run_session(layout, FORMS[form](layout), layer=True)
    assert not _landed(layout), form
    assert (layout.worktree / graph.PROPOSALS_DIR).is_dir()


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("form", list(FORMS))
def test_without_the_layer_each_command_lands_one_which_shows_the_probe_works(
    layout: Layout, form: str
) -> None:
    run_session(layout, FORMS[form](layout), layer=False)
    assert _landed(layout), form


@pytest.mark.usefixtures("layer")
def test_with_the_layer_the_file_tools_still_write_a_proposal_and_a_command_reads_it(
    layout: Layout,
) -> None:
    legal = json.dumps(_node("electrical.driver", domain="electrical"))
    target = layout.worktree / graph.PROPOSALS_DIR / "electrical.driver.json"
    run = run_session(
        layout,
        [
            tool("Write", file_path=str(target), content=legal),
            tool("Bash", command=f"cat {graph.PROPOSALS_DIR}/electrical.driver.json"),
        ],
        layer=True,
    )
    assert target.read_text() == legal
    assert '"electrical.driver"' in run["told"][1]  # type: ignore[index]
