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

from physgate.state.store import journal_records_after

#: The marker written into every planted target: it must never appear in a response.
MARKER = b"PLANTED-TARGET-MARKER"
RUN = "run-observe"
PRICES = "2026-09-27"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"runs": real_runs(base), "ui": fake_ui(base / "checkout")}


#: A node the observed run's journal holds, for the history route.
NODE = "electrical.node_s1_af41ca"


def _routes_reading(planted: str, session: str) -> list[str]:
    """The routes over one run that read ``planted``."""
    run = f"/api/runs/0/{RUN}"
    return {
        "run.json": [
            f"{run}/config",
            f"{run}/gate-events",
            f"{run}/cost/{PRICES}",
            f"{run}/trace",
            f"{run}/gate-checks",
        ],
        "events.jsonl": [
            f"{run}/events",
            f"{run}/ledger",
            f"{run}/gate-events",
            f"{run}/trajectories/{session}",
            f"{run}/cost/{PRICES}",
            f"{run}/trace",
            f"{run}/decisions",
            f"{run}/status",
            f"{run}/tokens",
            f"{run}/gate-checks",
            f"{run}/graph/history/{NODE}",
            f"{run}/queue",
            f"{run}/queue/items/0",
        ],
        "ledger.jsonl": [f"{run}/ledger"],
        "queue.jsonl": [f"{run}/queue", f"{run}/queue/items/0"],
        "queue_decisions.jsonl": [f"{run}/queue", f"{run}/queue/items/0"],
        "store/journal.jsonl": [
            f"{run}/graph",
            f"{run}/graph/at/1",
            f"{run}/graph/history/{NODE}",
            f"{run}/graph/diff/0/1",
        ],
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


PLANTED = (
    "run.json",
    "events.jsonl",
    "ledger.jsonl",
    "store/journal.jsonl",
    "stream",
    "queue.jsonl",
    "queue_decisions.jsonl",
)
TOWARD = ("held-out tier", "outside every root", "a credential in the run")


@pytest.mark.parametrize("toward", TOWARD)
@pytest.mark.parametrize("planted", PLANTED)
def test_a_route_refuses_a_file_it_reads_that_links_out_of_its_roots(
    built: dict[str, Path], tmp_path: Path, planted: str, toward: str
) -> None:
    world = _world(built, tmp_path)
    session = sealed_session(world["root"] / RUN)
    held = {line.node_id for line in journal_records_after(world["root"] / RUN / "store", 0)}
    assert NODE in held, f"the observed run's journal no longer holds {NODE}: {held}"
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


# -- the engine catalogue, read at start --------------------------------------------------------


@pytest.mark.parametrize("toward", ("held-out tier", "outside the checkout", "a credential"))
def test_an_engine_catalogue_planted_as_a_link_is_refused_at_start_and_never_opened(
    built: dict[str, Path], tmp_path: Path, toward: str
) -> None:
    """The catalogue is read once, at start, not by a route: a planted link is refused then.

    Its route then answers 422 with the reason and none of the target's bytes, and nothing,
    then or later, opens the target.
    """
    from dataclasses import replace

    from physgate.orchestrator.credentials import LOGIN_FILE
    from physgate.ui import engines

    world = _world(built, tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / "desktop" / "onboarding").mkdir(parents=True)
    if toward == "held-out tier":
        target = world["held"] / "target"
    elif toward == "outside the checkout":
        target = world["outside"] / "target"
    else:
        target = checkout / LOGIN_FILE
        target.write_bytes(MARKER + b"\n")
    (checkout / engines.CATALOGUE_FILE).symlink_to(target)
    context = context_over(world["root"], ui_root=built["ui"], held_out=(str(world["held"]),))
    with RECORDER.recording():
        held = engines.load(checkout, context.allowlist)
        with serving(replace(context, engines=held)) as live:
            status, _, body = live.request("GET", "/api/engines")
    assert held.state == "refused", held
    assert status == 422, body[:200]
    assert MARKER not in body
    real_target = str(target.resolve())
    tried = [p for p in RECORDER.opened if str(Path(p).resolve()) == real_target]
    assert tried == [], f"the planted target was opened: {tried}"


# -- the curated library ---------------------------------------------------------------------
#
# Every file a library route reads, planted the same three ways. A file a listing reads is
# refused in its own row (the listing answers, the row carries the error and none of the
# target's bytes); a file a route serves or describes is a 403. Either way the target is never
# opened.

#: Each library file a route reads, and per route whether it answers 403 or refuses in a row.
LIBRARY_PLANTS: dict[str, dict[str, str]] = {
    "control/standards.md": {
        "/api/library": "row",
        "/api/library/files/standards/control": "403",
        "/api/library/staged/cand-standards-control": "403",
    },
    "control/skill.md": {
        "/api/library": "row",
        "/api/library/files/skill/control": "403",
        "/api/library/staged/cand-skill-control": "403",
    },
    "electrical/bounds.toml": {
        "/api/library": "row",
        "/api/library/files/bounds/electrical": "403",
        "/api/library/ratings": "403",
    },
    "promotions.jsonl": {
        "/api/library": "403",
        "/api/library/files/standards/control": "403",
    },
    "staging/skill/cand-skill-control.json": {
        "/api/library/staged": "row",
        "/api/library/staged/cand-skill-control": "403",
    },
}


def _library_world(tmp_path: Path, toward: str) -> tuple[dict[str, Path], Path]:
    from ui_library_rig import build_library

    library = build_library(tmp_path / "checkout").root
    runs = tmp_path / "runs"
    (runs / "run-1").mkdir(parents=True)
    held = tmp_path / "held"
    outside = tmp_path / "outside"
    for place in (held, outside):
        place.mkdir()
        (place / "target").write_bytes(MARKER + b"\n")
    if toward == "held-out tier":
        target = held / "target"
    elif toward == "outside every root":
        target = outside / "target"
    else:
        target = runs / "run-1" / ".credentials.json"
        target.write_bytes(MARKER + b"\n")
    return {"library": library, "runs": runs, "held": held}, target


@pytest.mark.parametrize("toward", TOWARD)
@pytest.mark.parametrize("planted", sorted(LIBRARY_PLANTS))
def test_a_library_route_refuses_a_file_it_reads_that_links_out_of_its_roots(
    built: dict[str, Path], tmp_path: Path, planted: str, toward: str
) -> None:
    import json

    world, target = _library_world(tmp_path, toward)
    path = world["library"] / planted
    path.unlink()
    path.symlink_to(target)
    context = context_over(
        world["runs"],
        ui_root=built["ui"],
        held_out=(str(world["held"]),),
        library=world["library"],
    )
    routes = LIBRARY_PLANTS[planted]
    with serving(context) as live, RECORDER.recording():
        answers = {route: live.request("GET", route) for route in routes}
    for route, expected in routes.items():
        status, _, body = answers[route]
        assert MARKER not in body, route
        if expected == "403":
            assert status == 403, (route, status, body[:200])
            continue
        assert status == 200, (route, status, body[:200])
        answer = json.loads(body)
        rows = answer.get("documents", answer.get("candidates", []))
        refused = [
            row
            for row in rows
            if "error" in row
            and planted.endswith(row.get("path", row.get("name", "")).removeprefix("knowledge/"))
        ]
        assert refused, (route, rows)
    real_target = str(target.resolve())
    tried = [p for p in RECORDER.opened if str(Path(p).resolve()) == real_target]
    assert tried == [], f"a library route tried to open the planted target: {tried}"
