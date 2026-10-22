"""Through the real binary: inside the OS layer, the proposals deny holds on five more routes.

The routes measured first (copying or moving a staged directory into place, a path
built in the shell or at run time, the directory above moved away, the directory
removed and made again) reach the proposals by making or moving the directory. These
reach the directory as it stands (the installer makes it before a sandboxed session
starts, so that it can be denied), another way each: through a link to it made first,
by hard-linking a staged file into it, by unpacking an archive or applying a patch whose
own content names the path, and by a bare file name from inside it. Each command names
nothing the hooks' text check can see, and each would land a cross node a domain role
may not write. With the OS layer none lands, and the hooks record nothing about the
command: no refusal, so the layer and not the text check stopped it, and no error.
Without the layer each lands one, which shows the commands work.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session
from test_a_shell_command_cannot_write_the_proposals_inside_the_os_layer import (
    LANDED,
    _landed,
    _staged_file,
)

from physgate.hooks import graph

pytestmark = pytest.mark.integration


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


#: Each route, as the steps that take it: none names the proposals directory as the hooks read.
ROUTES = {
    "a-link-to-the-directory": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, shutil\n"
                "os.symlink(os.path.join('.phys' + 'gate', 'propo' + 'sals'), 'door')\n"
                f"shutil.copy('staged.txt', os.path.join('door', {LANDED!r}))"
            ),
        ),
    ],
    "a-hard-link-of-a-staged-file": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os\n"
                "d = os.path.join('.phys' + 'gate', 'propo' + 'sals')\n"
                f"os.link('staged.txt', os.path.join(d, {LANDED!r}))"
            ),
        ),
    ],
    "an-archive-unpacked-into-place": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, tarfile\n"
                "d = os.path.join('.phys' + 'gate', 'propo' + 'sals')\n"
                "with tarfile.open('staged.tar', 'w') as tar:\n"
                f"    tar.add('staged.txt', arcname=os.path.join(d, {LANDED!r}))"
            ),
        ),
        tool("Bash", command="tar -xf staged.tar"),
    ],
    "a-patch-applied": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                f"rel = '/'.join(['b', '.phys' + 'gate', 'propo' + 'sals', {LANDED!r}])\n"
                "body = open('staged.txt').read().rstrip('\\n')\n"
                "with open('staged.patch', 'w') as patch:\n"
                "    patch.write(f'--- /dev/null\\n+++ {rel}\\n@@ -0,0 +1 @@\\n+{body}\\n')"
            ),
        ),
        tool("Bash", command="patch -p1 < staged.patch"),
    ],
    "a-bare-name-from-inside-the-directory": lambda w: [
        _staged_file(w),
        tool(
            "Bash",
            command=python(
                "import os, shutil\n"
                "staged = os.path.abspath('staged.txt')\n"
                "os.chdir('.phys' + 'gate')\n"
                "os.chdir('propo' + 'sals')\n"
                f"shutil.copy(staged, {LANDED!r})"
            ),
        ),
    ],
}


def _standing(layout: Layout) -> None:
    """The proposals directory as a sandboxed session finds it: made before the session starts.

    The installer makes it only where the OS layer runs, so the control without the layer
    makes it here, and the routes take the same directory either way.
    """
    (layout.worktree / graph.PROPOSALS_DIR).mkdir(parents=True, exist_ok=True)


def _proposal_records(layout: Layout) -> list[dict[str, object]]:
    """What the hooks recorded of the proposal check, or of a check that failed to decide.

    The hooks keep only refusals and errors, so a command they accepted leaves no line;
    one line here means the text check, not the OS layer, is what stopped the command.
    """
    log_path = layout.sdir / "state" / "hooks.log.jsonl"
    if not log_path.exists():
        return []
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    return [r for r in records if r.get("hook") == "graph" or r.get("decision") == "error"]


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("route", list(ROUTES))
def test_with_the_layer_no_route_lands_a_proposal(layout: Layout, route: str) -> None:
    _standing(layout)
    run_session(layout, ROUTES[route](layout), layer=True)
    assert not _landed(layout), route
    assert (layout.worktree / graph.PROPOSALS_DIR).is_dir()
    assert _proposal_records(layout) == [], route


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("route", list(ROUTES))
def test_without_the_layer_each_route_lands_one_which_shows_the_probe_works(
    layout: Layout, route: str
) -> None:
    _standing(layout)
    run_session(layout, ROUTES[route](layout), layer=False)
    assert _landed(layout), route
    assert _proposal_records(layout) == [], route
