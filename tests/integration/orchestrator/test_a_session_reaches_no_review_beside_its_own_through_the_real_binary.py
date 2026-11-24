"""Through the real binary: a session reaches no review an earlier trial left, in a run root or not.

A measured run's reviews run inside its own run directory, in a run root withheld whole from
every later session. An earlier trial's review there holds its packet (the brief and the answer)
and the place apart with the key for labels. A review root outside the run roots (the standing
root, which a raw session is given as review material) holds the same for a run made by hand.
So this row installs a role session as a later trial's is, and asks the OS layer itself for each:
- its run root withheld whole, its run its own place;
- its own review root inside its run, not made yet;
- a standing-like review root outside the run root, and one that does not exist, as review
  material.

It also shows the layer starts when a review root it is given is not there yet.

Every path is joined at run time inside an interpreter fed a program, the residual the first
layer cannot see, so whatever stops a read here is the OS layer. Each attempt first reads a file
of the worktree's own in the same command, so a command that never ran cannot pass for a denial.
Without the layer the same commands reach each marker, which shows the probe works.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

# The OS layer's role-session rig, which the hook layer's own real-binary rows run on.
HOOK_ROWS = Path(__file__).resolve().parents[1] / "hooks"
if str(HOOK_ROWS) not in sys.path:
    sys.path.insert(0, str(HOOK_ROWS))

from fake_messages_api import tool  # noqa: E402
from os_layer_rig import MARKER, Layout, layer_here, make_layout, python, run_session  # noqa: E402

pytestmark = pytest.mark.integration

REVIEW = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
#: What an earlier trial's review left, beneath its review root.
LEFT = {
    "brief": (REVIEW, "read", "brief.md"),
    "key": ("sentinel-apart", "labels.key"),
}
OWN = "own.txt"
OWN_MARK = "OWN-WORKTREE-FILE"


@dataclass
class Reviews:
    layout: Layout
    #: The earlier trial's review root, beside the session's run in the run root.
    sibling: Path
    #: A review root outside the run root, given as review material, and one not there.
    standing: Path
    absent: Path


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here (judged when the test runs, not at collection)."""
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def reviews(tmp_path: Path) -> Iterator[Reviews]:
    # Beside the run root, never in it: the rig withholds its whole root.
    outside = tmp_path.parent / f"{tmp_path.name}-standing"
    with make_layout(tmp_path) as made:
        sibling = made.root / "sibling-run" / "review"
        standing = outside / "review-scratch"
        for root in (sibling, standing):
            for parts in LEFT.values():
                target = root.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(MARKER + "\n")
        (made.worktree / OWN).write_text(OWN_MARK + "\n")
        try:
            yield Reviews(made, sibling, standing, outside / "not-made-yet")
        finally:
            shutil.rmtree(outside, ignore_errors=True)


def _fields(reviews: Reviews) -> dict[str, object]:
    """The run root withheld whole, the run its own place, and the review roots it is given."""
    root = reviews.layout.root
    return {
        "withheld_whole": (str(root),),
        "own_place": str(root / "run"),
        "extra_review_material": (
            str(root / "run" / "review"),
            str(reviews.standing),
            str(reviews.absent),
        ),
    }


def _targets(reviews: Reviews) -> dict[str, Path]:
    return {
        f"{where} {what}": base.joinpath(*parts)
        for where, base in (("sibling", reviews.sibling), ("standing", reviews.standing))
        for what, parts in LEFT.items()
    }


def _reads(reviews: Reviews) -> list[dict[str, object]]:
    steps = []
    worktree = reviews.layout.worktree
    for name, target in _targets(reviews).items():
        # The path written reversed and turned round at run time: no protected name is in the
        # program's text for the first layer to refuse it by.
        program = (
            "import os\n"
            f"w = {str(worktree)!r}\n"
            f"print(open(os.path.join(w, {OWN!r})).read().strip())\n"
            f"p = {str(target)[::-1]!r}[::-1]\n"
            "try:\n    print(open(p).read())\n"
            "except OSError as e:\n    print('denied:', e.strerror)\n"
        )
        steps.append(tool("Bash", command=python(program), description=name))
    return steps


def _told(reviews: Reviews, *, layer: bool) -> dict[str, str]:
    run = run_session(reviews.layout, _reads(reviews), layer=layer, fields=_fields(reviews))
    told = run["told"]
    names = list(_targets(reviews))
    assert isinstance(told, list) and len(told) == len(names), told
    return dict(zip(names, (str(t) for t in told), strict=True))


@pytest.mark.usefixtures("layer")
def test_with_the_layer_no_review_beside_the_session_s_own_is_read(reviews: Reviews) -> None:
    told = _told(reviews, layer=True)
    for name, said in told.items():
        # The command ran: it read the worktree's own file first.
        assert OWN_MARK in said, (name, said)
        assert MARKER not in said, (name, said)


def test_without_the_layer_every_marker_is_reached_which_shows_the_probe_works(
    reviews: Reviews,
) -> None:
    told = _told(reviews, layer=False)
    for name, said in told.items():
        assert OWN_MARK in said and MARKER in said, (name, said)
