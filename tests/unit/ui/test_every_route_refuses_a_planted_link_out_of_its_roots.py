"""Every route holds every file it reads to the allowlist, proven per route by planting links.

The route sweep serves runs whose files are real files inside the root, so it cannot see a route
that skips the allowlist: for such files the check and its absence look the same. Here each
file a route reads is replaced by a link to the held-out tier, to a file outside every root, or
to a credential inside the run, and every route that reads it must answer 403, send back none of
the target's bytes, and never even try to open the target. A child run directory that is a link
out of its root must never be listed or served.

Two layers answer, and these tests are written so either one alone keeps them red when the other
goes missing: the route's own call to the allowlist (a 403 with the reason), and the request's
guard, which refuses any open outside what the request may read (a 500 naming the refusal).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from ui_rig import RECORDER, context_over, fake_ui, real_runs, sealed_session, serving

#: The marker written into every planted target: it must never appear in a response.
MARKER = b"PLANTED-TARGET-MARKER"
RUN = "run-observe"
PRICES = "2026-09-27"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"runs": real_runs(base), "ui": fake_ui(base / "checkout")}


def _routes_reading(planted: str, session: str) -> list[str]:
    """The routes over one run that read ``planted``."""
    run = f"/api/runs/0/{RUN}"
    return {
        "run.json": [f"{run}/config", f"{run}/gate-events", f"{run}/cost/{PRICES}"],
        "events.jsonl": [
            f"{run}/events",
            f"{run}/ledger",
            f"{run}/gate-events",
            f"{run}/trajectories/{session}",
            f"{run}/cost/{PRICES}",
        ],
        "ledger.jsonl": [f"{run}/ledger"],
        "store/journal.jsonl": [f"{run}/graph"],
        "stream": [f"{run}/trajectories/{session}"],
    }[planted]


def _world(built: dict[str, Path], tmp_path: Path) -> dict[str, Path]:
    """A root holding one copy of the observed run, a held-out tier and a directory outside."""
    root = tmp_path / "root"
    shutil.copytree(
        built["runs"] / RUN, root / RUN, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    held = tmp_path / "held"
    outside = tmp_path / "outside"
    for place in (held, outside):
        place.mkdir()
        (place / "target").write_bytes(MARKER + b"\n")
    return {"root": root, "held": held, "outside": outside}


def _plant(world: dict[str, Path], planted: str, toward: str, session: str) -> Path:
    """Replace the file ``planted`` with a link ``toward`` a target, and return the target."""
    run_dir = world["root"] / RUN
    relative = f"sessions/{session}/stdout.jsonl" if planted == "stream" else planted
    path = run_dir / relative
    if toward == "held-out tier":
        target = world["held"] / "target"
    elif toward == "outside every root":
        target = world["outside"] / "target"
    else:
        target = run_dir / "sessions" / session / "config" / ".credentials.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(MARKER + b"\n")
    path.unlink()
    path.symlink_to(target)
    return target


PLANTED = ("run.json", "events.jsonl", "ledger.jsonl", "store/journal.jsonl", "stream")
TOWARD = ("held-out tier", "outside every root", "a credential in the run")


@pytest.mark.parametrize("toward", TOWARD)
@pytest.mark.parametrize("planted", PLANTED)
def test_a_route_refuses_a_file_it_reads_that_links_out_of_its_roots(
    built: dict[str, Path], tmp_path: Path, planted: str, toward: str
) -> None:
    world = _world(built, tmp_path)
    session = sealed_session(world["root"] / RUN)
    target = _plant(world, planted, toward, session)
    context = context_over(world["root"], ui_root=built["ui"], held_out=(str(world["held"]),))
    routes = _routes_reading(planted, session)
    with serving(context) as live, RECORDER.recording():
        answers = [(route, *live.request("GET", route)) for route in routes]
    for route, status, _, body in answers:
        assert status == 403, (route, status, body[:200])
        assert MARKER not in body, route
    real_target = str(target.resolve())
    tried = [p for p in RECORDER.opened if str(Path(p).resolve()) == real_target]
    assert tried == [], f"a route tried to open the planted target: {tried}"


@pytest.mark.parametrize("toward", ("held-out tier", "outside every root"))
def test_a_child_run_directory_linked_out_of_its_root_is_never_listed_or_served(
    built: dict[str, Path], tmp_path: Path, toward: str
) -> None:
    world = _world(built, tmp_path)
    away = (world["held"] if toward == "held-out tier" else world["outside"]) / "a-run"
    shutil.copytree(world["root"] / RUN, away, symlinks=True)
    (world["root"] / "run-linked").symlink_to(away)
    context = context_over(world["root"], ui_root=built["ui"], held_out=(str(world["held"]),))
    with serving(context) as live, RECORDER.recording():
        listed = live.json("/api/runs")
        status, _, _ = live.request("GET", "/api/runs/0/run-linked/config")
    assert isinstance(listed, dict)
    assert [run["name"] for run in listed["runs"]] == [RUN]
    assert status == 404
    assert [
        p for p in RECORDER.opened if str(Path(p).resolve()).startswith(str(away.resolve()))
    ] == []


def test_the_guard_refuses_an_open_a_route_did_not_hold_to_the_allowlist(
    built: dict[str, Path], tmp_path: Path
) -> None:
    """The second layer alone: a route that reads past the allowlist is refused at the open."""
    from collections.abc import Mapping

    from physgate.ui.routes import Context, Response, Route, json_response
    from physgate.ui.table import ROUTES

    world = _world(built, tmp_path)

    def careless(context: Context, params: Mapping[str, str]) -> Response:
        return json_response({"read": (world["held"] / "target").read_text()})

    routes = (*ROUTES, Route("GET", "/careless", "read", careless))
    context = context_over(world["root"], ui_root=built["ui"], held_out=(str(world["held"]),))
    with serving(context, routes) as live:
        status, _, body = live.request("GET", "/careless")
    assert status == 500
    assert b"outside the roots it may read" in body
    assert MARKER not in body


def test_a_route_that_starts_a_thread_is_refused(built: dict[str, Path], tmp_path: Path) -> None:
    """A thread would run outside the request's guard, so a read route may not start one."""
    import threading
    from collections.abc import Mapping

    from physgate.ui.routes import Context, Response, Route, json_response
    from physgate.ui.table import ROUTES

    world = _world(built, tmp_path)
    written = world["root"] / RUN / "written-by-a-thread"

    def threaded(context: Context, params: Mapping[str, str]) -> Response:
        worker = threading.Thread(target=written.write_text, args=("x\n",))
        worker.start()
        worker.join()
        return json_response({})

    routes = (*ROUTES, Route("GET", "/threaded", "read", threaded))
    context = context_over(world["root"], ui_root=built["ui"])
    with serving(context, routes) as live:
        status, _, body = live.request("GET", "/threaded")
    assert status == 500
    assert b"started a thread" in body
    assert not written.exists()
