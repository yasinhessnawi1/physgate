"""Every route the server answers is enumerated, and none of them writes.

The sweep sends every method in ``METHODS`` to every route in the table, with valid and with
hostile parameters, and holds the result to two detectors that do not depend on the server's
guard: a snapshot of every file under the roots, the fixture build and this repository, before
and after; and an audit-hook recorder of every write-capable open and filesystem change in the
process. The recorder exists because the snapshot cannot see everything: opening an existing
file for appending and writing nothing leaves its bytes, its mtime and its ctime unchanged
(measured on this machine), so only an observer of the open itself catches that route.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ui_rig import METHODS, RECORDER, context_over, fake_ui, serving, snapshot, write_run

from physgate.ui.exceptions import UnregisteredKindError
from physgate.ui.routes import PARAMETERS, ROUTES, Context, Response, Route, json_response

REPO = Path(__file__).resolve().parents[3]

#: A valid value per parameter type, and hostile ones that must match nothing.
VALID = {"index": "0", "name": "run-1", "asset": "app.js"}
HOSTILE = (
    "..",
    "%2e%2e",
    "%252e%252e",
    "..%2f..%2fheld",
    "%2fetc%2fpasswd",
    "a%00b",
    ".hidden",
    "%",
    "%ZZ",
)


def _targets(route: Route) -> list[str]:
    """The route's path with valid parameters, and with each hostile spelling in each slot."""

    def build(fill: dict[str, str]) -> str:
        parts = [fill.get(name, name) if kind else name for name, kind in route.segments]
        return "/" + "/".join(parts)

    valid = {name: VALID[kind] for name, kind in route.segments if kind}
    targets = [build(valid)]
    for name, kind in route.segments:
        if kind:
            targets += [build({**valid, name: bad}) for bad in HOSTILE]
    return targets


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "runs"
    root.mkdir()
    write_run(root / "run-1", "run-1")
    held = tmp_path / "held"
    held.mkdir()
    (held / "scenario.json").write_text("{}\n")
    ui = fake_ui(tmp_path / "checkout")
    return {"root": root, "held": held, "ui": ui}


def _context(world: dict[str, Path]) -> Context:
    return context_over(world["root"], ui_root=world["ui"], held_out=(str(world["held"]),))


def test_the_table_is_not_empty_and_every_route_is_a_read() -> None:
    assert ROUTES, "an empty table would make every other test here vacuous"
    assert {route.kind for route in ROUTES} == {"read"}
    assert {route.method for route in ROUTES} == {"GET"}


def test_every_parameter_pattern_refuses_every_hostile_spelling() -> None:
    from urllib.parse import unquote

    for pattern in PARAMETERS.values():
        for bad in HOSTILE:
            assert pattern.fullmatch(unquote(bad)) is None, bad


def test_no_route_with_any_method_changes_any_file(world: dict[str, Path]) -> None:
    watched = (world["root"], world["held"], world["ui"], REPO / "src", REPO / "tests")
    before = snapshot(*watched)
    answered = 0
    with serving(_context(world)) as live, RECORDER.recording() as writes:
        for route in ROUTES:
            for target in _targets(route):
                for method in METHODS:
                    status, _, _ = live.request(method, target)
                    assert status != 500, (method, target)
                    answered += 1
    assert answered >= len(ROUTES) * len(METHODS)
    assert writes == [], writes
    assert snapshot(*watched) == before


def test_a_method_the_table_does_not_name_is_405_with_allow_never_501(
    world: dict[str, Path],
) -> None:
    with serving(_context(world)) as live:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "PROPFIND", "FROB"):
            for target in ("/", "/api/runs", "/no/such/path"):
                status, headers, _ = live.request(method, target)
                assert status == 405, (method, target, status)
                assert headers["allow"] == "GET, HEAD"


def test_every_read_route_answers_get_and_head_alike(world: dict[str, Path]) -> None:
    with serving(_context(world)) as live:
        for route in ROUTES:
            target = _targets(route)[0]
            get_status, get_headers, body = live.request("GET", target)
            head_status, head_headers, head_body = live.request("HEAD", target)
            assert get_status == head_status == 200, target
            assert head_body == b""
            assert get_headers["content-length"] == head_headers["content-length"] == str(len(body))


@pytest.mark.parametrize(
    "target",
    [
        "/api/runs/..%2f..%2fheld",
        "/assets/..%2f..%2fheld%2fscenario.json",
        "/assets/%252e%252e%252fheld",
        "/assets/a%00b",
        "/../held/scenario.json",
        "//held/scenario.json",
        "/assets/../../held/scenario.json",
        "/ASSETS/app.js",
        "/api/runs/",
    ],
)
def test_a_request_naming_the_held_out_tier_in_any_spelling_reads_nothing_there(
    world: dict[str, Path], target: str
) -> None:
    with serving(_context(world)) as live, RECORDER.recording():
        status, _, body = live.request("GET", target)
    assert status in (400, 404), (target, status)
    assert b"scenario" not in body


def test_an_absolute_form_request_target_is_refused(world: dict[str, Path]) -> None:
    with serving(_context(world)) as live:
        status, _, _ = live.request("GET", f"http://127.0.0.1:{live.port}/api/runs")
    assert status == 400


def test_a_route_of_a_kind_with_no_policy_cannot_be_declared() -> None:
    def act(context: Context, params: object) -> Response:
        return json_response({})

    with pytest.raises(UnregisteredKindError, match="no policy"):
        Route("GET", "/act", "act", act)  # type: ignore[arg-type]


def test_a_planted_route_that_writes_through_get_is_refused_by_the_guard(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """The guard aborts a read route's write before it happens, so nothing changes on disk.

    The recorder sees the attempted open either way; the snapshot shows the guard stopped it.
    """
    target = world["root"] / "run-1" / "run.json"

    def appends(context: Context, params: object) -> Response:
        with open(target, "a"):
            pass
        return json_response({})

    routes = (*ROUTES, Route("GET", "/planted", "read", appends))
    before = snapshot(world["root"])
    with serving(_context(world), routes) as live, RECORDER.recording() as writes:
        status, _, body = live.request("GET", "/planted")
    assert status == 500
    assert b"opened a file for writing" in body
    assert writes, "the recorder must see the attempted open"
    assert snapshot(world["root"]) == before
