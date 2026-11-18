"""The Evidence screen's gap trend: what the trend's one reader published, or why it is not shown.

The server cannot run the reader: the trend's head and the register it is held to lie beneath
the role's withheld root, which no root of the server may reach. So ``GET /api/evidence/gaps``
serves what a person published from the reader at a terminal, found under its role's name at the
top of a root, and held to the publication's own parser, handed in by the composition root. Per
role, in the order the gaps name them: no publication (said so, never as an empty trend); the
weeks as published, with the time they were read; or a refusal in a sentence, when the reader
refused the trend as it was published, when the file is not one its writer could have written
(cut, edited, another role's, too large), when it is a link out of the roots, or when two roots
each hold one. Nothing is computed here, and nothing of the store is named.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from ui_rig import context_over, fake_ui, serving

GAPS_TESTS = Path(__file__).resolve().parents[1] / "gaps"
if str(GAPS_TESTS) not in sys.path:
    sys.path.insert(0, str(GAPS_TESTS))

from gap_fixtures import StandInStore, api, design, measured, stand_in_store  # noqa: E402

from physgate.evaluation.tiers.store import withheld_root  # noqa: E402

ROUTE = "/api/evidence/gaps"
ROLES = ["control", "firmware"]
NOW = datetime(2026, 11, 18, 10, 2, tzinfo=UTC)
PUBLISH = "physgate.evaluation.gaps.published.publish_trend"
NAME = "physgate.evaluation.gaps.published.published_name"
APPEND = "physgate.evaluation.gaps.measure.append_gap_line"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A store with a two-line control trend, the fixture build, and the trend's bytes."""
    base = tmp_path_factory.mktemp("gaps-route")
    made = stand_in_store(base / "st")
    withheld = withheld_root(made.store, "control")
    keys = []
    for name in ("h1", "h2"):
        held = measured(made, "held_out", base / name)
        keys.append(
            api("physgate.evaluation.tiers.measure.write_vector")(
                withheld, version=made.version, tier="held_out", runs=held.runs, trials=held.trials
            )
        )
    visible = measured(made, "visible", base / "v")
    found = api("physgate.evaluation.gaps.measure.measure")(
        api("physgate.evaluation.gaps.measure.GapsDesign").model_validate_json(
            json.dumps(design(made, visible, validation_tasks=None))
        ),
        runs=visible.runs,
        trials=visible.trials,
        held_out=withheld / "gaps" / f"{keys[0]}.json",
        validation=None,
    )
    trend = base / "gaps.jsonl"
    for n, day in ((1, date(2026, 11, 2)), (2, date(2026, 11, 9))):
        line = found.model_copy(
            update={"manifest_ids": (f"{n:064x}",), "keys": {"held_out": keys[n - 1]}}
        )
        api(APPEND)(trend, line, today=day)
    return {"made": made, "trend": trend, "ui": fake_ui(base / "checkout")}


def _folder(tmp_path: Path, name: str = "evidence") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _publish(world: dict[str, Any], folder: Path, trend: Path | None = None) -> Path:
    made: StandInStore = world["made"]
    path: Path = api(PUBLISH)(
        trend or world["trend"], store=made.store, role="control", out=folder, now=NOW
    )
    return path


def _answer(world: dict[str, Any], *roots: Path) -> tuple[int, bytes, dict[str, Any]]:
    with serving(context_over(*roots, ui_root=world["ui"])) as live:
        status, _, body = live.request("GET", ROUTE)
    answer: dict[str, Any] = json.loads(body) if status == 200 else {}
    return status, body, answer


def _role(answer: dict[str, Any], role: str) -> dict[str, Any]:
    (found,) = [entry for entry in answer.get("roles", []) if entry.get("role") == role] or [{}]
    return found


def test_with_nothing_published_each_role_says_so_and_holds_no_week(
    world: dict[str, Any], tmp_path: Path
) -> None:
    status, body, answer = _answer(world, _folder(tmp_path))
    assert status == 200, body[:300]
    assert set(answer) == {"roles"}, answer
    assert answer["roles"] == [{"role": role, "state": "none"} for role in ROLES]


def test_a_published_trend_is_served_as_its_parser_reads_it_with_the_time_it_was_read(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    path = _publish(world, folder)
    parsed = api("physgate.evaluation.gaps.published.read_published")(path.read_bytes(), "control")
    status, body, answer = _answer(world, folder)
    assert status == 200, body[:300]
    assert _role(answer, "control") == {
        "role": "control",
        "state": "read",
        "read_at": parsed.model_dump(mode="json")["read_at"],
        "weeks": parsed.model_dump(mode="json")["weeks"],
    }
    assert _role(answer, "firmware") == {"role": "firmware", "state": "none"}
    weeks = _role(answer, "control")["weeks"]
    assert [w["week"] for w in weeks] == ["2026-W45", "2026-W46", "2026-W47"]
    assert weeks[0]["lines"][0]["numbers"]["reward_hacking"]["gap"] == pytest.approx(
        parsed.weeks[0].lines[0].numbers.reward_hacking.gap
    )


def test_a_trend_the_reader_refused_is_served_as_the_reader_s_sentence_and_no_week(
    world: dict[str, Any], tmp_path: Path
) -> None:
    cut = tmp_path / "cut.jsonl"
    cut.write_bytes(world["trend"].read_bytes() + b'{"format": 1')
    folder = _folder(tmp_path)
    published = json.loads(_publish(world, folder, cut).read_text())
    status, body, answer = _answer(world, folder)
    assert status == 200, body[:300]
    assert _role(answer, "control") == {
        "role": "control",
        "state": "refused",
        "error": published["refused"]["error"],
        "reason": published["refused"]["refused_because"],
        "read_at": published["read_at"],
    }
    assert "cut" in _role(answer, "control")["error"]


@pytest.mark.parametrize("how", ["cut", "edited", "another-role-s", "too-large"])
def test_a_publication_its_writer_could_not_have_written_is_refused_whole(
    world: dict[str, Any], tmp_path: Path, how: str
) -> None:
    folder = _folder(tmp_path)
    path = _publish(world, folder)
    data = path.read_bytes()
    if how == "cut":
        path.write_bytes(data[: len(data) // 2])
    elif how == "edited":
        body = json.loads(data)
        body["read_at"] = "the other day"
        path.write_text(json.dumps(body))
    elif how == "another-role-s":
        firmware = folder / api(NAME)("firmware")
        path.rename(firmware)
        path = firmware
    else:
        path.write_bytes(data + b" " * (5 * 1024 * 1024))
    status, body, answer = _answer(world, folder)
    assert status == 200, body[:300]
    role = "firmware" if how == "another-role-s" else "control"
    entry = _role(answer, role)
    assert entry.get("state") == "refused", entry
    assert set(entry) == {"role", "state", "error", "reason", "read_at"}, entry
    assert entry["read_at"] is None
    assert entry["error"], entry
    assert b'"weeks"' not in body, "a part of a refused publication was served"


def test_two_roots_that_each_hold_a_role_s_publication_are_refused_not_chosen_between(
    world: dict[str, Any], tmp_path: Path
) -> None:
    first, second = _folder(tmp_path, "one"), _folder(tmp_path, "two")
    _publish(world, first)
    _publish(world, second)
    status, body, answer = _answer(world, first, second)
    assert status == 200, body[:300]
    entry = _role(answer, "control")
    assert entry.get("state") == "refused", entry
    assert "two" in entry["error"], entry
    assert b'"weeks"' not in body


def test_the_answer_names_no_place_of_the_store_or_the_folders(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    _publish(world, folder)
    status, body, _ = _answer(world, folder)
    assert status == 200, body[:300]
    said = body.decode()
    made: StandInStore = world["made"]
    for word in (str(made.store), "withheld", str(folder), str(tmp_path), str(world["trend"])):
        assert word not in said, f"the answer holds {word}"


def test_a_publication_not_at_the_top_of_a_root_is_not_read(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    _publish(world, _folder(folder, "deeper"))
    status, body, answer = _answer(world, folder)
    assert status == 200, body[:300]
    assert _role(answer, "control") == {"role": "control", "state": "none"}


def _answer_or_fail(world: dict[str, Any], folder: Path, fifo: Path | None = None) -> Any:  # noqa: ANN401
    """The answer, or the row fails if the server is still reading after the client's timeout.

    A route that opened a pipe to read would wait for a writer for ever: the pipe is then opened
    for writing and closed here, so the server's thread ends and the row fails on its assertion.
    """
    import os

    with serving(context_over(folder, ui_root=world["ui"])) as live:
        try:
            status, _, body = live.request("GET", ROUTE)
        except TimeoutError:
            if fifo is not None:
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            pytest.fail("the route waited on the published trend's place and never answered")
    assert status == 200, body[:300]
    return json.loads(body)


def test_a_link_in_place_of_the_publication_is_not_followed_even_inside_the_root(
    world: dict[str, Any], tmp_path: Path
) -> None:
    folder = _folder(tmp_path)
    kept = _publish(world, _folder(folder, "kept"))
    (folder / kept.name).symlink_to(kept)
    entry = _role(_answer_or_fail(world, folder), "control")
    assert entry.get("state") == "refused", entry
    assert "link" in entry["error"], entry


def test_a_pipe_in_place_of_the_publication_is_refused_without_waiting_on_it(
    world: dict[str, Any], tmp_path: Path
) -> None:
    import os

    folder = _folder(tmp_path)
    fifo = folder / api(NAME)("control")
    os.mkfifo(fifo)
    entry = _role(_answer_or_fail(world, folder, fifo), "control")
    assert entry.get("state") == "refused", entry
    assert "regular file" in entry["error"], entry


def test_a_publication_with_a_second_name_on_disk_is_refused_in_words(
    world: dict[str, Any], tmp_path: Path
) -> None:
    import os

    folder = _folder(tmp_path)
    path = _publish(world, folder)
    os.link(path, folder / "another-name.json")
    entry = _role(_answer_or_fail(world, folder), "control")
    assert entry.get("state") == "refused", entry
    assert "more than one name" in entry["error"], entry
