"""The gap trend, published for the Evidence page as its one reader read it, or why it could not be.

The page's server reads beneath the folders it is given and nothing else, and never the role's
withheld root, where the trend's head and the register lie; so it cannot run the reader itself.
A person runs it at a terminal instead (``physgate gaps trend --publish DIR``): the reader's
weeks, as :func:`gap_weeks` gives them through the day it was read (a week with no line shown
missing), are written whole to ``DIR`` under a name of the role's, with the time they were read.
A trend the reader refuses is published as that refusal, in place of whatever was published
before, so a page never shows numbers the reader would now refuse, and so is any failure once the
folder is judged: a publish that fails leaves no older copy to read as current. The publication
names no store, no path and no reason of the register; it is never written inside a session, nor
into the store or a folder that holds it, since the page's server would then read the store, nor
into any place the harness knows a run's sessions, a reviewer or a commit reach: a run's
directory or a folder of runs, a git checkout or worktree (the harness's own, a run's target), an
installation, a review root, the machine's shared temporary directories, or a folder the
operator UI would refuse to read. Its own parser refuses anything its writer could not have
written, a cut file, and another role's.
"""

from __future__ import annotations

import errno
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from gap_fixtures import StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.gaps import published as published_module
from physgate.evaluation.gaps.vector import GapsError
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


@pytest.fixture(autouse=True)
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The places the harness knows of on this machine, as folders of the row's own.

    The machine's own are the checkout these rows run from, the home's review root and the shared
    temporary directories, and every row's folder lies in one of those; a row that needs them
    real undoes this.
    """
    known = SimpleNamespace(
        harness=tmp_path / "code" / "harness",
        review_root=tmp_path / "home" / "review-scratch",
        shared_temps=(tmp_path / "shared-tmp",),
    )
    monkeypatch.setattr(published_module, "known_places", lambda: known, raising=False)
    return known


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))


def _vector(tmp_path: Path, made: StandInStore, name: str) -> Path:
    """A held-out vector written from a fresh run set: one more look, under a key of its own."""
    withheld = withheld_root(made.store, "control")
    runs = measured(made, "held_out", tmp_path / name)
    key = api(WRITE)(
        withheld, version=made.version, tier="held_out", runs=runs.runs, trials=runs.trials
    )
    return withheld / "gaps" / f"{key}.json"


def _trend(tmp_path: Path, made: StandInStore) -> Path:
    """A trend of two lines with their numbers, in the ISO weeks 2026-W45 and 2026-W46."""
    trend = tmp_path / "gaps.jsonl"
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(tmp_path, made, "h1")
    found = api(MEASURE)(
        api(DESIGN).model_validate_json(json.dumps(design(made, visible, validation_tasks=None))),
        runs=visible.runs,
        trials=visible.trials,
        held_out=held,
        validation=None,
    )
    second = _vector(tmp_path, made, "h2")
    for n, day, key in ((1, date(2026, 11, 2), held.stem), (2, date(2026, 11, 9), second.stem)):
        line = found.model_copy(update={"manifest_ids": (f"{n:064x}",), "keys": {"held_out": key}})
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
    assert all(line["numbers"] for w in published["weeks"] for line in w["lines"]), "no numbers"
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
    try:
        again = _publish(trend, made, out)
    except Exception as exc:  # noqa: BLE001 - a raised refusal is the failure this row names
        pytest.fail(f"the reader's refusal was raised, not published: {exc}")
    assert again == path
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


#: A review's directory as the review places name one: the instrument's id, with what it reads.
REVIEW = "r0123456789ab"


def _place(tmp_path: Path, places: SimpleNamespace, where: str) -> Path:
    """The folder to publish into, in a place of the kind ``where`` names, as its maker makes it."""
    runs, installs, reviews = tmp_path / "runs", tmp_path / "installs", tmp_path / "reviews"
    (runs / "run-1").mkdir(parents=True)
    (runs / "run-1" / "run.json").write_text("{}")
    (runs / "inject-1").mkdir()
    (runs / "inject-1" / "instrument.json").write_text("{}")
    (installs / "install").mkdir(parents=True)
    (installs / "install" / "physgate-install-manifest.json").write_text("{}")
    (reviews / REVIEW / "read").mkdir(parents=True)
    (tmp_path / "target" / ".git").mkdir(parents=True)
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / ".git").write_text("gitdir: elsewhere\n")
    places.harness.mkdir(parents=True)
    places.review_root.mkdir(parents=True)
    places.shared_temps[0].mkdir()
    out: Path = {
        "in-a-run-directory": runs / "run-1" / "evidence",
        "a-run-directory-itself": runs / "run-1",
        "in-an-instrument-run": runs / "inject-1" / "evidence",
        "beside-runs": runs,
        "in-a-target-checkout": tmp_path / "target" / "evidence",
        "in-a-worktree": tmp_path / "worktree" / "evidence",
        "in-the-harness-checkout": places.harness / "evidence",
        "holding-the-harness-checkout": places.harness.parent,
        "in-an-installation": installs / "install" / "evidence",
        "beside-an-installation": installs,
        "in-the-review-root": places.review_root / "evidence",
        "holding-the-review-root": places.review_root.parent,
        "in-a-review": reviews / REVIEW / "read",
        "beside-reviews": reviews,
        "in-the-shared-temp": places.shared_temps[0] / "evidence",
        "in-a-corpus": tmp_path / "corpora" / "evidence",
    }[where]
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize(
    "where",
    [
        "in-a-run-directory",
        "a-run-directory-itself",
        "in-an-instrument-run",
        "beside-runs",
        "in-a-target-checkout",
        "in-a-worktree",
        "in-the-harness-checkout",
        "holding-the-harness-checkout",
        "in-an-installation",
        "beside-an-installation",
        "in-the-review-root",
        "holding-the-review-root",
        "in-a-review",
        "beside-reviews",
        "in-the-shared-temp",
        "in-a-corpus",
    ],
)
def test_the_publication_is_refused_in_any_place_a_run_a_reviewer_or_a_commit_reaches(
    tmp_path: Path, made: StandInStore, places: SimpleNamespace, where: str
) -> None:
    trend = _trend(tmp_path, made)
    out = _place(tmp_path, places, where)
    try:
        _publish(trend, made, out)
    except Exception as exc:  # noqa: BLE001 - the refusal is what this row reads
        caught: BaseException | None = exc
    else:
        caught = None
    assert caught is not None, f"a publication was written {where}"
    assert _reason(caught) == "publish_refused", caught
    written = [p for p in tmp_path.rglob("*") if p.name.startswith("gap-trend")]
    assert written == [], f"a publication was written {where}"
    said = str(caught)
    assert str(tmp_path) not in said, f"the refusal echoes a path: {said}"
    assert "given no run" in said, f"the refusal does not say what the command cannot know: {said}"


def test_a_folder_of_its_own_beside_those_places_is_published_into(
    tmp_path: Path, made: StandInStore, places: SimpleNamespace
) -> None:
    trend = _trend(tmp_path, made)
    _place(tmp_path, places, "in-a-run-directory")
    out = _out(tmp_path)
    assert _publish(trend, made, out) == out / api(NAME)("control")


def test_the_places_the_command_knows_are_the_harness_s_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from physgate.orchestrator.run_config import harness_root
    from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs
    from physgate.reviewers.places import standing_root

    monkeypatch.undo()
    places_of = getattr(published_module, "known_places", None)
    assert callable(places_of), "the command reads no place the harness knows of"
    known = places_of()
    assert known.harness == harness_root()
    assert known.review_root == standing_root(Path.home())
    assert set(known.shared_temps) == {Path(p) for p in (*shared_temp_dirs(), *claude_temp_dirs())}


def test_the_command_s_help_says_which_folder_to_publish_into_and_what_it_cannot_know(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["gaps", "trend", "--help"])
    said = " ".join(capsys.readouterr().out.split())
    assert "given no run" in said, said
    assert "physgate ui --root" in said, said


def _failing_reader(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def read(*_: object, **__: object) -> object:
        raise exc

    monkeypatch.setattr(published_module, "read_gap_trend", read)


def test_a_publish_that_fails_after_the_folder_is_judged_replaces_the_copy_with_its_refusal(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    path = _publish(trend, made, out)
    assert json.loads(path.read_text())["weeks"], "the first publication holds no week"
    _failing_reader(monkeypatch, RuntimeError(f"broke reading {trend}"))
    try:
        _publish(trend, made, out)
    except Exception as exc:  # noqa: BLE001 - a raised failure is the failure this row names
        pytest.fail(f"the failure was raised and the older copy left in place: {exc!r}")
    published = json.loads(path.read_text())
    assert published["weeks"] is None, "an older copy still reads as current"
    assert published["refused"]["refused_because"] == "publish_failed", published
    assert str(tmp_path) not in published["refused"]["error"], published
    assert sorted(os.listdir(out)) == [api(NAME)("control")]


def test_a_publication_that_cannot_be_written_removes_the_copy_before_it(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    trend = _trend(tmp_path, made)
    out = _out(tmp_path)
    path = _publish(trend, made, out)

    def replace(*_: object, **__: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(Exception) as caught:
        _publish(trend, made, out)
    monkeypatch.undo()
    assert _reason(caught.value) == "publish_failed", caught.value
    assert not path.exists(), "the copy published before is left to read as current"
    assert os.listdir(out) == [], "the failed write left a file beside it"
    assert str(tmp_path) not in str(caught.value), caught.value


#: Sentences that name a place on disk in every form the reader's could, the place last.
PLACES_IN_WORDS = {
    "relative": "runs/run-1/gaps.jsonl",
    "dot-relative": "./gaps.jsonl",
    "home": "~/runs/gaps.jsonl",
    "a-user-s-home": "~someone",
    "windows": "C:\\Users\\someone\\gaps.jsonl",
    "windows-forward": "D:/runs/gaps.jsonl",
    "after-a-backtick": "`/srv/runs/gaps.jsonl`",
    "after-a-bracket": "[/srv/runs/gaps.jsonl]",
    "after-a-quote": "'runs/gaps.jsonl'",
}


@pytest.mark.parametrize("form", sorted(PLACES_IN_WORDS))
def test_a_refusal_that_names_a_place_in_any_form_is_published_without_it(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    place = PLACES_IN_WORDS[form]
    _failing_reader(
        monkeypatch,
        GapsError(f"the trend at {place} cannot be read", refused_because="trend_unreadable"),
    )
    published = json.loads(_publish(tmp_path / "gaps.jsonl", made, _out(tmp_path)).read_text())
    refused = published["refused"]
    assert refused["refused_because"] == "trend_unreadable", refused
    assert place not in refused["error"], f"the {form} place is published: {refused['error']}"
    assert "gaps.jsonl" not in refused["error"], refused["error"]
    assert refused["error"], refused


def test_a_reason_that_names_a_place_is_published_without_it(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _failing_reader(monkeypatch, GapsError("it cannot be read", refused_because="at /srv/runs"))
    published = json.loads(_publish(tmp_path / "gaps.jsonl", made, _out(tmp_path)).read_text())
    assert "/srv" not in json.dumps(published["refused"]), published["refused"]
    assert published["refused"]["refused_because"] == "GapsError", published["refused"]


def test_a_refusal_that_names_no_place_is_published_in_its_own_words(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    said = "the head records 2 line(s), read on 2026/11/18, and the trend holds 3; 1/4 is past it"
    _failing_reader(monkeypatch, GapsError(said, refused_because="trend_broken"))
    published = json.loads(_publish(tmp_path / "gaps.jsonl", made, _out(tmp_path)).read_text())
    assert published["refused"] == {"refused_because": "trend_broken", "error": said}


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


def test_a_refusal_whose_sentence_names_a_place_on_disk_is_published_without_it(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = _trend(tmp_path, made)
    withheld = withheld_root(made.store, "control")
    moved = withheld.with_name("withheld-moved")
    withheld.rename(moved)
    withheld.symlink_to(moved, target_is_directory=True)
    with pytest.raises(Exception) as caught:
        api(READ)(trend, store=made.store, role="control")
    assert str(made.store) in str(caught.value), "the row needs a sentence that names a place"
    published = json.loads(_publish(trend, made, _out(tmp_path)).read_text())
    refused = published["refused"]
    assert refused["refused_because"] == _reason(caught.value)
    assert str(made.store) not in refused["error"] and str(tmp_path) not in refused["error"]
    assert refused["error"], refused
