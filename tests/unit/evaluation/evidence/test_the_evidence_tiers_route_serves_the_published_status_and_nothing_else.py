"""The Evidence screen's tier versions: what a person published from ``tiers status``, or why not.

The server never reads the tier store: the check record lies in a role's root and the register
beneath its withheld root, which no root of the server may reach. So ``GET /api/evidence/tiers``
serves what a person published at a terminal, found under its role's name at the top of a root,
held to the publication's own parser, which the composition root hands in. Per role, in the order
the publication names them: no publication (said so); the version id, the three tiers' task
counts, the blind check's counts and source, the exposure word, the version's state, whether a
measured run names it and when it was read; or a refusal in a fixed sentence. The answer copies
those named fields alone, opens nothing but the publication files, and names no task, canary,
path or digest but the version id: not in its answer, and not in the server's log.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ui_rig import RECORDER, Live, composed, context_over, fake_ui, opened_outside, serving

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import StandInStore, api, stand_in_store  # noqa: E402

from physgate.ui.server import make_server  # noqa: E402

ROUTE = "/api/evidence/tiers"
ROLES = ["control", "firmware"]
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
PUBLISH = "physgate.evaluation.tiers.published.publish_status"
NAME = "physgate.evaluation.tiers.published.published_name"
SENTENCES = "physgate.evaluation.tiers.published.SENTENCES"
STORE_MARK = "zqstoremarkzq"
#: The exact key sets the route serves, at every depth.
READ_KEYS = {
    "role",
    "state",
    "read_at",
    "version",
    "counts",
    "check",
    "exposure",
    "version_state",
    "measured",
}
REFUSED_KEYS = {"role", "state", "error", "reason", "read_at"}
#: A place on disk, planted in a file as a value its writer could not have written.
PLANTED = "/srv/zqplantedzq/held_out/task.json"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A marked store of one checked version, one held-out task flagged; and the fixture build."""
    base = tmp_path_factory.mktemp("tiers-route")
    made = stand_in_store(base / STORE_MARK, marked=True, flagged=(0,))
    return {"made": made, "ui": fake_ui(base / "checkout")}


@pytest.fixture(autouse=True)
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The places the harness knows of, as folders of the row's own.

    The rows' folders lie in the machine's shared temporary directory, where the publish command
    refuses to write.
    """
    from types import SimpleNamespace

    from physgate.evaluation.gaps import published

    known = SimpleNamespace(
        harness=tmp_path / "code" / "harness",
        review_root=tmp_path / "home" / "review-scratch",
        shared_temps=(tmp_path / "shared-tmp",),
    )
    monkeypatch.setattr(published, "known_places", lambda: known)


def _folder(tmp_path: Path, name: str = "tier-status") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _publish(world: dict[str, Any], folder: Path) -> dict[str, dict[str, Any]]:
    made: StandInStore = world["made"]
    api(PUBLISH)(made.store, out=folder, now=NOW)
    return {role: json.loads((folder / api(NAME)(role)).read_bytes()) for role in ROLES}


def _answer(world: dict[str, Any], *roots: Path, held: tuple[str, ...] = ()) -> dict[str, Any]:
    with serving(context_over(*roots, ui_root=world["ui"], held_out=held)) as live:
        status, _, body = live.request("GET", ROUTE)
    assert status == 200, body[:300]
    answer: dict[str, Any] = json.loads(body)
    answer["_body"] = body
    return answer


def _role(answer: dict[str, Any], role: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = answer["roles"]
    (found,) = [entry for entry in entries if entry.get("role") == role] or [{}]
    return found


def _markers(world: dict[str, Any], tmp_path: Path) -> list[str]:
    """Every marker a served byte must not hold: tasks, briefs, canaries, places."""
    made: StandInStore = world["made"]
    return [
        "zqmark",
        "Stabilise plant",
        *made.canaries,
        STORE_MARK,
        str(made.store),
        str(tmp_path),
        "withheld",
        "zqplanted",
    ]


def test_with_nothing_published_each_role_says_so(world: dict[str, Any], tmp_path: Path) -> None:
    answer = _answer(world, _folder(tmp_path))
    assert answer["roles"] == [{"role": role, "state": "none"} for role in ROLES]
    assert set(answer) == {"roles", "_body"}


def test_a_published_status_is_served_as_its_named_fields_alone(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    published = _publish(world, folder)
    answer = _answer(world, folder)
    control = _role(answer, "control")
    assert control == {
        "role": "control",
        "state": "read",
        "read_at": published["control"]["read_at"],
        "version": world["made"].version,
        "counts": {"visible": 8, "validation": 8, "held_out": 8},
        "check": {"tasks": 8, "all_yes": 7, "left_out": 1, "source": "check"},
        "exposure": "none",
        "version_state": "fresh",
        "measured": False,
    }
    assert set(control) == READ_KEYS
    firmware = _role(answer, "firmware")
    assert firmware == {
        "role": "firmware",
        "state": "refused",
        "error": api(SENTENCES)["no_fresh_version"],
        "reason": "no_fresh_version",
        "read_at": published["firmware"]["read_at"],
    }


def test_the_answer_holds_no_marker_and_no_digest_but_the_version_id(
    world: dict[str, Any], tmp_path: Path
) -> None:
    import re

    folder = _folder(tmp_path)
    _publish(world, folder)
    body = _answer(world, folder)["_body"].decode()
    for marker in _markers(world, tmp_path):
        assert marker not in body, f"the answer holds {marker}"
    assert set(re.findall(r"[0-9a-f]{64}", body)) == {world["made"].version}


def test_the_route_opens_the_publication_files_and_nothing_else(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    _publish(world, folder)
    (folder / "beside.json").write_text("{}")
    store = str(world["made"].store)
    with (
        serving(context_over(folder, ui_root=world["ui"], held_out=(store,))) as live,
        RECORDER.recording(),
    ):
        status, _, body = live.request("GET", ROUTE)
    assert status == 200, body[:300]
    real = os.path.realpath(tmp_path)
    mine = {os.path.realpath(p) for p in RECORDER.opened if os.path.realpath(p).startswith(real)}
    expected = {os.path.realpath(folder / api(NAME)(role)) for role in ROLES}
    assert mine == expected, sorted(mine)
    assert opened_outside(RECORDER.listed, (folder,), (Path(store),)) == []
    assert opened_outside(RECORDER.opened, (folder,), (Path(store),)) == []


def test_two_roots_that_each_hold_a_role_s_publication_are_refused_not_chosen_between(
    world: dict[str, Any], tmp_path: Path
) -> None:
    first, second = _folder(tmp_path, "one"), _folder(tmp_path, "two")
    _publish(world, first)
    _publish(world, second)
    entry = _role(_answer(world, first, second), "control")
    assert set(entry) == REFUSED_KEYS, entry
    assert entry["reason"] == "publications_more_than_one"
    assert world["made"].version not in json.dumps(entry)


def _refused_entry(world: dict[str, Any], tmp_path: Path, folder: Path) -> dict[str, Any]:
    answer = _answer(world, folder)
    entry = _role(answer, "control")
    assert entry.get("state") == "refused", entry
    assert set(entry) == REFUSED_KEYS, entry
    assert entry["read_at"] is None
    body = answer["_body"].decode()
    for marker in _markers(world, tmp_path):
        assert marker not in body, f"the answer holds {marker}"
    assert world["made"].version not in body, "a part of a refused publication was served"
    return entry


def _plant(folder: Path, how: str) -> None:
    path = folder / "tier-status-control.json"
    data = path.read_bytes()
    body = json.loads(data)
    if how == "cut":
        path.write_bytes(data[: len(data) // 2])
        return
    if how == "not-json":
        path.write_bytes(b"\x00not json")
        return
    if how == "too-large":
        path.write_bytes(data + b" " * (8 * 1024))
        return
    if how == "an-extra-key":
        body["store"] = PLANTED
    elif how == "a-value-of-another-kind":
        body["counts"]["held_out"] = PLANTED
    elif how == "a-free-word":
        body["exposure"] = PLANTED
    elif how == "a-path-for-the-time":
        body["read_at"] = PLANTED
    elif how == "a-time-in-another-form":
        body["read_at"] = "2026-11-24T12:00:00+00:00"
    elif how == "a-count-of-thousands-of-digits":
        text = json.dumps(body).replace('"visible": 8', '"visible": ' + "7" * 3500)
        path.write_text(text)
        return
    path.write_text(json.dumps(body))


#: A publication edited into one its writer could not have written, each way.
PLANTS = [
    "cut",
    "not-json",
    "too-large",
    "an-extra-key",
    "a-value-of-another-kind",
    "a-free-word",
    "a-path-for-the-time",
    "a-time-in-another-form",
    "a-count-of-thousands-of-digits",
]


@pytest.mark.parametrize("how", PLANTS)
def test_a_publication_its_writer_could_not_have_written_is_refused_in_a_sentence_naming_no_path(
    world: dict[str, Any], tmp_path: Path, how: str
) -> None:
    folder = _folder(tmp_path)
    _publish(world, folder)
    _plant(folder, how)
    entry = _refused_entry(world, tmp_path, folder)
    assert entry["reason"] == "publication_unreadable", entry
    assert "/" not in entry["error"], entry
    assert "7777" not in _answer(world, folder)["_body"].decode()


def test_a_publication_whose_place_the_guard_refuses_at_the_open_is_a_refused_role_not_a_failure(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The allowlist judged the place, then it was swapped before the open, so the request's guard
    # refuses the open itself: the role is refused in a fixed sentence, the other still read.
    from physgate.ui.paths import Allowlist

    folder = _folder(tmp_path)
    _publish(world, folder)
    swapped = str(folder / api(NAME)("control"))
    readable = Allowlist.readable

    def judged_then_swapped(self: Allowlist, path: str) -> bool:
        return os.path.realpath(path) != os.path.realpath(swapped) and readable(self, path)

    monkeypatch.setattr(Allowlist, "readable", judged_then_swapped)
    answer = _answer(world, folder)
    entry = _role(answer, "control")
    assert entry.get("state") == "refused", entry
    assert set(entry) == REFUSED_KEYS, entry
    assert entry["reason"] == "publication_refused", entry
    assert "/" not in entry["error"] and world["made"].version not in entry["error"], entry
    assert _role(answer, "firmware").get("reason") == "no_fresh_version"


def test_a_link_in_place_of_the_publication_toward_the_held_out_tier_is_refused_unopened(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    made: StandInStore = world["made"]
    target = made.store / "control" / made.version / "held_out" / "canaries.json"
    assert target.is_file(), "the row needs a held-out file to link toward"
    (folder / api(NAME)("control")).symlink_to(target)
    with RECORDER.recording():
        entry = _refused_entry(world, tmp_path, folder)
    assert entry["reason"] == "publication_refused", entry
    opened = [p for p in RECORDER.opened if os.path.realpath(p) == os.path.realpath(target)]
    assert opened == [], "the route opened the held-out file the link points at"


def test_a_link_in_place_of_the_publication_is_not_followed_even_inside_the_root(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    kept = _folder(folder, "kept")
    _publish(world, kept)
    (folder / api(NAME)("control")).symlink_to(kept / api(NAME)("control"))
    entry = _refused_entry(world, tmp_path, folder)
    assert "never followed" in entry["error"], entry


def test_a_pipe_in_place_of_the_publication_is_refused_without_waiting_on_it(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    fifo = folder / api(NAME)("control")
    os.mkfifo(fifo)
    try:
        entry = _refused_entry(world, tmp_path, folder)
    except TimeoutError:
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        pytest.fail("the route waited on the publication's place and never answered")
    assert "regular file" in entry["error"], entry


def test_a_publication_with_a_second_name_on_disk_is_refused_in_words(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    _publish(world, folder)
    os.link(folder / api(NAME)("control"), folder / "another-name.json")
    entry = _refused_entry(world, tmp_path, folder)
    assert "more than one name" in entry["error"], entry


@contextmanager
def _logging(world: dict[str, Any], folder: Path) -> Iterator[Live]:
    """The command's table served over ``folder`` with the server's log on, as a person runs it."""
    context = context_over(folder, ui_root=world["ui"])
    server = make_server(context, bind="127.0.0.1", port=0, routes=composed(), quiet=False)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield Live(port=int(server.server_address[1]), token=server.act_token)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.mark.parametrize("planted", [False, True])
def test_the_server_s_log_names_no_marker_of_the_store_or_a_planted_file(
    world: dict[str, Any], tmp_path: Path, capfd: pytest.CaptureFixture[str], planted: bool
) -> None:
    folder = _folder(tmp_path)
    _publish(world, folder)
    if planted:
        _plant(folder, "an-extra-key")
    capfd.readouterr()
    with _logging(world, folder) as live:
        status, _, _ = live.request("GET", ROUTE)
    assert status == 200
    out, err = capfd.readouterr()
    logged = out + err
    assert ROUTE in logged, "the row needs the server's own log of the request"
    for marker in _markers(world, tmp_path):
        assert marker not in logged, f"the server's log holds {marker}"
    assert world["made"].version not in logged
