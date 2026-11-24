"""Through the real binary: a role session whose run root is withheld whole keeps every denial.

A measured run withholds every run root of the store it names whole from its sessions, and a
role session's worktree lies inside one of them, in its own run's directory. The OS layer then
denies the run root and opens the worktree again. An opening re-opens what lies beneath it, so
this row asks the layer itself whether the denials that lie inside the worktree (the answer-key
corpora, the series outbox, which commands write blind) still hold there, and whether a sibling
run's record beside the session's own run is reached.

Every path is joined at run time inside an interpreter fed a program, the residual the first
layer cannot see, so whatever stops a read here is the OS layer. Every read aims at a file
holding a marker; each attempt also reads a file of the worktree's own in the same command, so a
command that never ran cannot pass for a denial. Without the layer the same commands reach each
marker, which shows the probe works.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import MARKER, Layout, layer_here, make_layout, python, run_session

pytestmark = pytest.mark.integration

#: The places read, each beside the worktree's own file: inside the worktree, under a denial of
#: its own, and beside the session's run, in the run root withheld whole.
INSIDE = {
    "corpora": ("corpora", "x.json"),
    "outbox": (".physgate", "series", "r.json"),
}
SIBLING = ("sibling-run", "run.json")
OWN = "own.txt"
OWN_MARK = "OWN-WORKTREE-FILE"


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here (judged when the test runs, not at collection)."""
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        for parts in INSIDE.values():
            target = made.worktree.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(MARKER + "\n")
        sibling = made.root.joinpath(*SIBLING)
        sibling.parent.mkdir(parents=True)
        sibling.write_text(MARKER + "\n")
        (made.worktree / OWN).write_text(OWN_MARK + "\n")
        yield made


def _whole(layout: Layout) -> dict[str, object]:
    """The run root withheld whole (the test's root, holding the run), the run its own place."""
    return {"withheld_whole": (str(layout.root),), "own_place": str(layout.root / "run")}


def _reads(layout: Layout) -> list[dict[str, object]]:
    # The run root is the worktree's third parent, found at run time: named in the program's
    # text, the first layer would refuse the command by its name.
    up = len(layout.worktree.relative_to(layout.root).parts)
    targets = {
        **{name: ("w", parts) for name, parts in INSIDE.items()},
        "sibling": (f"functools.reduce(lambda p, _: os.path.dirname(p), range({up}), w)", SIBLING),
    }
    steps = []
    for name, (base, parts) in targets.items():
        # Each part written reversed and turned round at run time: no protected name is in the
        # program's text for the first layer to refuse it by.
        reversed_parts = [part[::-1] for part in parts]
        program = (
            "import functools, os\n"
            f"w = {str(layout.worktree)!r}\n"
            f"print(open(os.path.join(w, {OWN!r})).read().strip())\n"
            f"p = os.path.join({base}, *(q[::-1] for q in {reversed_parts!r}))\n"
            "try:\n    print(open(p).read())\n"
            "except OSError as e:\n    print('denied:', e.strerror)\n"
        )
        steps.append(tool("Bash", command=python(program), description=name))
    return steps


def _told(layout: Layout, *, layer: bool) -> dict[str, str]:
    run = run_session(layout, _reads(layout), layer=layer, fields=_whole(layout))
    told = run["told"]
    assert isinstance(told, list) and len(told) == len(INSIDE) + 1, told
    return dict(zip([*INSIDE, "sibling"], (str(t) for t in told), strict=True))


@pytest.mark.usefixtures("layer")
def test_with_the_layer_no_denial_inside_the_worktree_is_lost_and_no_sibling_run_is_read(
    layout: Layout,
) -> None:
    told = _told(layout, layer=True)
    for name, said in told.items():
        # The command ran: it read the worktree's own file first.
        assert OWN_MARK in said, (name, said)
        assert MARKER not in said, (name, said)


def test_without_the_layer_every_marker_is_reached_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    told = _told(layout, layer=False)
    for name, said in told.items():
        assert OWN_MARK in said and MARKER in said, (name, said)
