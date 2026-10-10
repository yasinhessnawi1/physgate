"""The guard's read rule, held where a handler that skips the allowlist would try to get past it.

Each test plants a careless read route: one that reads or lists a path without asking the
allowlist, the regression the guard exists for. Three ways round the rule are closed here:
- its exception for the interpreter's own files is never wider than the refusals: a held-out
  tier, a corpus or a credential lying under the interpreter's prefixes is still refused;
- a directory listing is held to the same rule as an open, since it names the files inside;
- a relative path is refused, because the audit event carries no directory handle and the
  working directory is the wrong thing to judge it by.
What the rule cannot see is said in the guard's own docstring: Python raises no audit event
for stat.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from ui_rig import RECORDER, context_over, fake_ui, opened_outside, serving, write_run

from physgate.ui import paths
from physgate.ui.routes import Context, Response, Route, json_response
from physgate.ui.table import ROUTES

MARKER = "PLANTED-TARGET-MARKER"


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "runs"
    write_run(root / "run-1", "run-1")
    held = tmp_path / "held"
    held.mkdir()
    (held / "target").write_text(MARKER + "\n")
    return {"root": root, "held": held, "ui": fake_ui(tmp_path / "checkout")}


def _careless(
    world: dict[str, Path], reach: Callable[[], object], held: Path | None = None
) -> tuple[int, dict[str, str], bytes]:
    """Serve one careless read route that calls ``reach``, and answer GET on it."""

    def careless(context: Context, params: Mapping[str, str]) -> Response:
        return json_response({"got": repr(reach())})

    routes = (*ROUTES, Route("GET", "/careless", "read", careless))
    tier = str(held if held is not None else world["held"])
    context = context_over(world["root"], ui_root=world["ui"], held_out=(tier,))
    with serving(context, routes) as live:
        return live.request("GET", "/careless")


# -- the exception is never wider than the refusals ------------------------------------------


@pytest.fixture
def interpreter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory the server treats as one of the interpreter's own prefixes."""
    prefix = tmp_path / "interpreter"
    prefix.mkdir()
    monkeypatch.setattr(paths, "INTERPRETER_PATHS", (*paths.INTERPRETER_PATHS, str(prefix)))
    return prefix


def test_an_interpreter_file_is_readable(world: dict[str, Path], interpreter: Path) -> None:
    (interpreter / "module.py").write_text("x = 1\n")
    status, _, _ = _careless(world, lambda: (interpreter / "module.py").read_text())
    assert status == 200


def test_a_held_out_tier_under_the_interpreter_is_still_refused(
    world: dict[str, Path], interpreter: Path
) -> None:
    tier = interpreter / "held"
    tier.mkdir()
    (tier / "target").write_text(MARKER + "\n")
    status, _, body = _careless(world, lambda: (tier / "target").read_text(), held=tier)
    assert status == 500
    assert b"outside the roots it may read" in body
    assert MARKER.encode() not in body


@pytest.mark.parametrize("planted", ["corpora/answers.json", ".env", "config/.credentials.json"])
def test_a_corpus_or_a_secret_under_the_interpreter_is_still_refused(
    world: dict[str, Path], interpreter: Path, planted: str
) -> None:
    target = interpreter / planted
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(MARKER + "\n")
    status, _, body = _careless(world, target.read_text)
    assert status == 500
    assert MARKER.encode() not in body


# -- listings are held like opens ---------------------------------------------------------------


@pytest.mark.parametrize(
    "lister",
    [
        lambda d: os.listdir(d),
        lambda d: [e.name for e in os.scandir(d)],
        lambda d: list(os.walk(d)),
        lambda d: list(Path(d).iterdir()),
    ],
    ids=["listdir", "scandir", "walk", "iterdir"],
)
def test_listing_the_held_out_tier_is_refused(
    world: dict[str, Path], lister: Callable[[Path], object]
) -> None:
    status, _, body = _careless(world, lambda: lister(world["held"]))
    assert status == 500
    assert b"listed a directory outside the roots" in body
    assert b"target" not in body


def test_listing_by_descriptor_is_refused(world: dict[str, Path]) -> None:
    def by_descriptor() -> object:
        fd = os.open(world["root"], os.O_RDONLY)
        try:
            return os.listdir(fd)
        finally:
            os.close(fd)

    status, _, body = _careless(world, by_descriptor)
    assert status == 500
    assert b"listed a directory" in body


def test_listing_a_root_is_allowed(world: dict[str, Path]) -> None:
    assert _careless(world, lambda: os.listdir(world["root"]))[0] == 200


# -- relative paths are refused ------------------------------------------------------------------


def test_a_relative_open_through_a_directory_handle_is_refused(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative open through a directory handle is refused, never misjudged.

    The process's working directory sits inside the root, so ``../held/target`` judged against
    it would land inside the root too; opened through a handle on the root, the same path
    reaches the held-out tier. The audit event carries the relative path and no handle, so the
    only sound answer is to refuse a relative path outright.
    """
    monkeypatch.chdir(world["root"] / "run-1")
    assert (Path.cwd().parent / "held" / "target").resolve().is_relative_to(world["root"].resolve())

    def through_handle() -> object:
        fd = os.open(world["root"], os.O_RDONLY)
        try:
            inner = os.open("../held/target", os.O_RDONLY, dir_fd=fd)
            try:
                return os.read(inner, 100)
            finally:
                os.close(inner)
        finally:
            os.close(fd)

    status, _, body = _careless(world, through_handle)
    assert status == 500
    assert b"outside the roots it may read" in body
    assert MARKER.encode() not in body


def test_a_plain_relative_open_is_refused_even_inside_a_root(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain relative open is refused, even where it would land inside a root.

    Nothing a route does should depend on the server's working directory.
    """
    monkeypatch.chdir(world["root"] / "run-1")
    (world["root"] / "run-1" / "relative.txt").write_text("inside the root\n")
    status, _, body = _careless(world, lambda: open("relative.txt").read())  # noqa: SIM115
    assert status == 500
    assert b"outside the roots it may read" in body


# -- the test-side detector judges the refusals first too -----------------------------------------


def test_the_sweep_s_detector_flags_a_refused_path_under_the_interpreter() -> None:
    """The rig's own check judges the refusals before the interpreter's exception.

    A secret, a corpus or a refused tier under the interpreter's prefix is flagged, not let
    through.
    """
    import sys

    prefix = Path(os.path.realpath(sys.prefix))
    tier = prefix / "held-tier"
    planted = [str(prefix / ".env"), str(prefix / "corpora" / "a.json"), str(tier / "x")]
    flagged = opened_outside(planted, roots=(), refused=(tier,))
    assert len(flagged) == 3
    assert opened_outside([str(prefix / "lib" / "os.py")], roots=(), refused=(tier,)) == []


def test_the_recorder_sees_listings(world: dict[str, Path]) -> None:
    with RECORDER.recording():
        os.listdir(world["root"])
    assert str(world["root"]) in RECORDER.listed
