"""The gap trend, published for the Evidence page as its one reader read it, or why it could not be.

The page's server reads beneath the folders it is given and nothing else, and never the role's
withheld root, where the trend's head and the register lie; so it cannot run the reader itself.
A person runs it at a terminal instead (``physgate gaps trend --publish DIR``): the reader's
weeks, as :func:`gap_weeks` gives them through the day it was read (a week with no line shown
missing), are written whole to ``DIR`` under a name of the role's, with the time they were read.
A trend the reader refuses is published as that refusal, in place of whatever was published
before, so a page never shows numbers the reader would now refuse. The publication names no
store, no path and no reason of the register; it is never written inside a session, nor into the
store or a folder that holds it, since the page's server would then read the store. Its own
parser refuses anything its writer could not have written, a cut file, and another role's.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root

PUBLISH = "physgate.evaluation.gaps.published.publish_trend"
PARSE = "physgate.evaluation.gaps.published.read_published"
NAME = "physgate.evaluation.gaps.published.published_name"
WRITE = "physgate.evaluation.tiers.measure.write_vector"
APPEND = "physgate.evaluation.gaps.measure.append_gap_line"
MEASURE = "physgate.evaluation.gaps.measure.measure"
DESIGN = "physgate.evaluation.gaps.measure.GapsDesign"
READ = "physgate.evaluation.gaps.read_gap_trend"
WEEKS = "physgate.evaluation.gaps.gap_weeks"
#: When the trend is read in these rows: a Wednesday of the ISO week 2026-W47.
NOW = datetime(2026, 11, 18, 10, 2, tzinfo=UTC)


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))


def _found(tmp_path: Path, made: StandInStore) -> Any:  # noqa: ANN401
    """What ``physgate gaps`` measured on a run set, before anything is appended."""
    visible = measured(made, "visible", tmp_path / "v")
    withheld = withheld_root(made.store, "control")
    runs = measured(made, "held_out", tmp_path / "h")
    key = api(WRITE)(
        withheld, version=made.version, tier="held_out", runs=runs.runs, trials=runs.trials
    )
    body = design(made, visible, validation_tasks=None)
    return api(MEASURE)(
        api(DESIGN).model_validate_json(json.dumps(body)),
        runs=visible.runs,
        trials=visible.trials,
        held_out=withheld / "gaps" / f"{key}.json",
        validation=None,
    )


def _trend(tmp_path: Path, made: StandInStore) -> Path:
    """A trend of two lines, in the ISO weeks 2026-W45 and 2026-W46."""
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    for n, day in ((1, date(2026, 11, 2)), (2, date(2026, 11, 9))):
        line = found.model_copy(
            update={"manifest_ids": (f"{n:064x}",), "keys": {"held_out": f"{n + 7:064x}"}}
        )
        api(APPEND)(trend, line, today=day)
    return trend


def _publish(trend: Path, made: StandInStore, out: Path, role: str = "control") -> Path:
    path: Path = api(PUBLISH)(trend, store=made.store, role=role, out=out, now=NOW)
    return path


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "evidence"
    out.mkdir()
    return out


def test_the_publication_is_the_reader_s_weeks_through_the_day_it_was_read(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    path = _publish(trend, made, out)
    assert path == out / api(NAME)("control"), "the publication is not under the role's name"
    published = json.loads(path.read_text())
    lines = api(READ)(trend, store=made.store, role="control")
    weeks = api(WEEKS)(lines, through=NOW.date())
    assert published["weeks"] == [week.model_dump(mode="json") for week in weeks]
    assert [w["week"] for w in published["weeks"]] == ["2026-W45", "2026-W46", "2026-W47"]
    assert [w["missing"] for w in published["weeks"]] == [False, False, True]
    assert published["refused"] is None
    assert published["role"] == "control"
    assert datetime.fromisoformat(published["read_at"]) == NOW


def test_the_publication_names_no_store_path_or_register_line(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = _trend(tmp_path, made)
    said = _publish(trend, made, _out(tmp_path)).read_text()
    for word in (str(made.store), "withheld", str(trend), '"by"', '"reason"', '"prev"', '"keys"'):
        assert word not in said, f"the publication holds {word}"


def test_a_trend_not_begun_is_published_as_no_week(tmp_path: Path, made: StandInStore) -> None:
    published = json.loads(_publish(tmp_path / "none.jsonl", made, _out(tmp_path)).read_text())
    assert published["weeks"] == [], published
    assert published["refused"] is None


def test_a_trend_the_reader_refuses_is_published_as_its_refusal_in_place_of_the_last(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    path = _publish(trend, made, out)
    assert json.loads(path.read_text())["weeks"], "the first publication holds no week"
    trend.write_bytes(trend.read_bytes() + b'{"format": 1, "n"')  # a write stopped part way
    with pytest.raises(Exception) as caught:
        api(READ)(trend, store=made.store, role="control")
    assert _publish(trend, made, out) == path
    published = json.loads(path.read_text())
    assert published["weeks"] is None, "numbers the reader now refuses are still published"
    assert published["refused"] == {
        "refused_because": _reason(caught.value),
        "error": str(caught.value),
    }
    assert "cut" in published["refused"]["error"]


def test_the_publication_is_replaced_whole_and_leaves_nothing_beside_it(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    _publish(trend, made, out)
    _publish(trend, made, out)
    assert sorted(os.listdir(out)) == [api(NAME)("control")]


def test_the_publication_is_made_by_a_person_never_inside_a_session(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path / "session-tmp"))
    with pytest.raises(Exception) as caught:
        _publish(trend, made, out)
    assert _reason(caught.value) == "inside_a_session", caught.value
    assert os.listdir(out) == []


@pytest.mark.parametrize("where", ["in-the-store", "holding-the-store", "missing", "a-link"])
def test_the_publication_is_written_only_to_a_folder_of_its_own(
    tmp_path: Path, made: StandInStore, where: str
) -> None:
    trend = _trend(tmp_path, made)
    folder = _out(tmp_path)
    out = {
        "in-the-store": made.store / "control",
        "holding-the-store": made.store.parent,
        "missing": tmp_path / "not-there",
        "a-link": tmp_path / "link",
    }[where]
    if where == "a-link":
        out.symlink_to(folder, target_is_directory=True)
    before = {p for p in tmp_path.rglob("*") if p.name.startswith("gap-trend")}
    with pytest.raises(Exception) as caught:
        _publish(trend, made, out)
    assert _reason(caught.value) == "publish_refused", caught.value
    after = {p for p in tmp_path.rglob("*") if p.name.startswith("gap-trend")}
    assert after == before, f"a publication was written {where}"


def test_its_parser_takes_what_its_writer_wrote(tmp_path: Path, made: StandInStore) -> None:
    path = _publish(_trend(tmp_path, made), made, _out(tmp_path))
    parsed = api(PARSE)(path.read_bytes(), "control")
    assert parsed.model_dump(mode="json") == json.loads(path.read_text())


def _edited(published: dict[str, Any], how: str) -> bytes:
    body = dict(published)
    if how == "cut":
        return json.dumps(body).encode()[:-9]
    if how == "an-unknown-field":
        body["store"] = "/somewhere"
    elif how == "weeks-and-a-refusal":
        body["refused"] = {"refused_because": "trend_broken", "error": "it was changed"}
    elif how == "neither":
        body["weeks"] = None
    elif how == "another-form":
        body["format"] = 2
    elif how == "a-number-unmarked":
        body["weeks"][0]["lines"][0]["numbers"]["reward_hacking"]["gap"] = "0.4"
    return json.dumps(body).encode()


@pytest.mark.parametrize(
    "how",
    [
        "cut",
        "an-unknown-field",
        "weeks-and-a-refusal",
        "neither",
        "another-form",
        "a-number-unmarked",
    ],
)
def test_its_parser_refuses_what_its_writer_could_not_have_written(
    tmp_path: Path, made: StandInStore, how: str
) -> None:
    path = _publish(_trend(tmp_path, made), made, _out(tmp_path))
    with pytest.raises(Exception) as caught:
        api(PARSE)(_edited(json.loads(path.read_text()), how), "control")
    assert _reason(caught.value) == "publication_unreadable", caught.value


def test_its_parser_refuses_another_role_s_publication(tmp_path: Path, made: StandInStore) -> None:
    path = _publish(_trend(tmp_path, made), made, _out(tmp_path))
    with pytest.raises(Exception) as caught:
        api(PARSE)(path.read_bytes(), "firmware")
    assert _reason(caught.value) == "publication_unreadable", caught.value
    assert "another role's" in str(caught.value)


def test_the_command_prints_the_publication_and_writes_it_only_when_asked(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    argv = ["gaps", "trend", "--store", str(made.store), "--role", "control", "--trend", str(trend)]
    assert main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [w["week"] for w in printed["weeks"]][:2] == ["2026-W45", "2026-W46"]
    assert os.listdir(out) == [], "the command wrote without --publish"
    assert main([*argv, "--publish", str(out)]) == 0
    capsys.readouterr()
    assert json.loads((out / api(NAME)("control")).read_text())["weeks"][:2] == printed["weeks"][:2]


def test_the_command_says_a_refusal_and_exits_one(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    trend = _trend(tmp_path, made)
    trend.write_bytes(trend.read_bytes() + b"{")
    out = _out(tmp_path)
    argv = ["gaps", "trend", "--store", str(made.store), "--role", "control", "--trend", str(trend)]
    assert main([*argv, "--publish", str(out)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["refused"]["refused_because"] == "trend_unreadable", printed
    assert json.loads((out / api(NAME)("control")).read_text())["refused"] == printed["refused"]
