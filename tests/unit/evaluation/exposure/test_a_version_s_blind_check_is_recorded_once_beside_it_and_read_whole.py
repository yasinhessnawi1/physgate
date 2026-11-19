"""A version's blind check is one record beside it: written once, read whole, imported once.

The record lies in the role's root, named by the version's id, never inside the version, which is
never written again. A second record of a version is refused and the first kept; a record changed
by hand, a link, an oversized file or one that is not this version's is refused as it is read, and
lies out of place in the role's root, so nothing starts on the store. ``tiers status`` shows each
version's check by its counts alone. A measured run on a version with no check record is refused:
a held-out tier nobody checked is not scored.

The record is written whole: its bytes go to a temporary name beneath the role's withheld root and
are renamed into place under the writers' lock, so a crash leaves no record or a whole one, and a
record that came in the meantime is never replaced. A record that cannot be read is refused in
words that name the file and say what a person does about it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from exposure_fixtures import (
    StandInStore,
    api,
    config,
    record_check,
    refusal,
    stand_in_store,
    with_run_root,
)

from physgate.cli import main
from physgate.evaluation.tiers.store import leftovers, role_root, version_dir
from physgate.evaluation.tiers.task import id_digest

CHECKS = "physgate.evaluation.tiers.checks"


def _path(made: StandInStore) -> Path:
    path: Path = api(f"{CHECKS}.check_path")(made.store, "control", made.version)
    return path


def _read(made: StandInStore) -> Any:  # noqa: ANN401
    from physgate.evaluation.tiers.manifest import read_version

    manifest = read_version(version_dir(made.store, "control", made.version))
    return api(f"{CHECKS}.read_check")(made.store, "control", made.version, manifest=manifest)


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because"))


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "s", flagged=(0,))


@pytest.fixture
def unchecked(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "u", checked=False)


def test_the_record_lies_beside_its_version_and_holds_counts_and_digests_alone(
    made: StandInStore,
) -> None:
    path = _path(made)
    assert path.parent == role_root(made.store, "control"), "the record lies in the role's root"
    assert path.name == f"{made.version}.check.json"
    assert not (version_dir(made.store, "control", made.version) / path.name).exists()
    record = _read(made)
    assert (record.tasks, record.all_yes, record.flagged) == (
        8,
        7,
        (id_digest(made.tasks["held_out"][0].id),),
    )
    text = path.read_text()
    for task in made.tasks["held_out"]:
        assert task.id not in text and task.brief not in text, "a held-out task is named"
    assert leftovers(made.store)["work_left"] == 0, "a sound record is out of place"


def test_a_second_record_of_a_version_is_refused_and_the_first_kept(made: StandInStore) -> None:
    before = _path(made).read_bytes()
    with pytest.raises(api(f"{CHECKS}.CheckError")) as refused:
        record_check(made.store, made.version, [])
    assert _reason(refused.value) == "check_recorded", "a second check replaced the first"
    assert _path(made).read_bytes() == before


def _edit(made: StandInStore, how: str) -> None:
    path = _path(made)
    body = json.loads(path.read_text())
    if how == "a flagged task taken out":
        body["flagged"], body["all_yes"] = [], body["all_yes"] + 1
        path.write_text(json.dumps(body))
    elif how == "a count changed":
        body["all_yes"] = 8
        path.write_text(json.dumps(body))
    elif how == "a link":
        other = path.with_name("elsewhere.json")
        path.rename(other)
        path.symlink_to(other)
    elif how == "too large":
        path.write_text(json.dumps({**body, "padding": "x" * (128 * 1024)}))
    elif how == "not a record":
        path.write_text("not a record")
    elif how == "another tier digest":
        # Re-signed, so it names itself: it is the tier the version's manifest names that differs.
        path.unlink()
        record_check(made.store, made.version, [], tier_sha256="f" * 64)


@pytest.mark.parametrize(
    ("how", "reason"),
    [
        ("a flagged task taken out", "check_record_changed"),
        ("a count changed", "check_record_changed"),
        ("a link", "check_record_unreadable"),
        ("too large", "check_record_unreadable"),
        ("not a record", "check_record_unreadable"),
        ("another tier digest", "check_record_not_the_version"),
    ],
)
def test_a_record_changed_by_hand_or_not_the_version_s_is_refused_as_read(
    made: StandInStore, how: str, reason: str
) -> None:
    _edit(made, how)
    with pytest.raises(api(f"{CHECKS}.CheckError")) as refused:
        _read(made)
    assert _reason(refused.value) == reason, "a record that is not the check's own was read"
    if how == "too large":
        assert "larger than any record" in str(refused.value), "read past the record's bound"


@pytest.mark.parametrize("how", ["a flagged task taken out", "a link", "not a record"])
def test_a_record_that_does_not_read_lies_out_of_place_and_nothing_starts(
    made: StandInStore, how: str
) -> None:
    _edit(made, how)
    assert leftovers(made.store)["work_left"] >= 1, "a broken record was taken as in place"


def test_a_stray_file_under_a_record_s_name_lies_out_of_place(unchecked: StandInStore) -> None:
    stray = role_root(unchecked.store, "control") / f"{'e' * 64}.check.json"
    stray.write_text(json.dumps({"id": "a task's copy"}))
    assert leftovers(unchecked.store)["work_left"] == 1


def _status(capsys: pytest.CaptureFixture[str], store: Path) -> dict[str, Any]:
    main(["tiers", "status", "--store", str(store)])
    out = capsys.readouterr().out
    found: dict[str, Any] = json.loads(out.strip().splitlines()[-1])
    return found


def test_tiers_status_shows_each_version_s_check_by_its_counts_alone(
    made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["tiers", "status", "--store", str(made.store)])
    out = capsys.readouterr().out
    (version,) = json.loads(out.strip().splitlines()[-1])["versions"]
    assert version["check"] == {"tasks": 8, "all_yes": 7, "flagged": 1, "source": "check"}
    assert id_digest(made.tasks["held_out"][0].id) not in out, "status names a flagged task"
    for task in made.tasks["held_out"]:
        assert task.id not in out


def test_tiers_status_shows_a_version_with_no_check_and_a_record_refused(
    unchecked: StandInStore, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    (version,) = _status(capsys, unchecked.store)["versions"]
    assert version["check"] is None
    _edit(made, "a count changed")
    (version,) = _status(capsys, made.store)["versions"]
    assert version["check"] == {"refused_because": "check_record_changed"}


def test_a_measured_run_on_a_version_with_no_check_record_is_refused(
    tmp_path: Path, unchecked: StandInStore
) -> None:
    runs = with_run_root(unchecked, tmp_path / "runs")
    said = refusal(config(unchecked.tasks["visible"][0], unchecked), runs / "r1")
    assert said is not None and "(held_out_unchecked)" in said, "an unchecked version was measured"


def test_a_measured_run_on_a_version_whose_record_was_changed_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    assert refusal(run, runs / "r1") is None
    _edit(made, "a count changed")
    said = refusal(run, runs / "r1")
    assert said is not None and "(check_record_changed)" in said


# -------------------------------------------------------------- written whole, once


def _stray_names(made: StandInStore) -> list[str]:
    """Every name the write may have left beside the record or beneath the withheld root."""
    from physgate.evaluation.tiers.store import withheld_root

    return sorted(
        p.name
        for place in (role_root(made.store, "control"), withheld_root(made.store, "control"))
        for p in place.iterdir()
        if ".check." in p.name and not p.name.endswith(".check.json")
    )


def test_the_record_is_written_whole_and_leaves_no_temporary_name(
    unchecked: StandInStore,
) -> None:
    record = record_check(unchecked.store, unchecked.version, [])
    path = _path(unchecked)
    assert path.stat().st_nlink == 1, "the record has a second name"
    assert _stray_names(unchecked) == [], "the write left a temporary name"
    assert _read(unchecked) == record
    assert leftovers(unchecked.store)["work_left"] == 0


def test_a_write_that_fails_before_the_record_is_in_place_leaves_none(
    unchecked: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A crash after the bytes are written and before they are put in place: no record, not an
    # empty one, and the store is not stopped by what was left.
    checks = __import__(CHECKS, fromlist=["os"])

    def crashed(*_: Any, **__: Any) -> None:  # noqa: ANN401
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(checks.os, "rename", crashed)
    with pytest.raises(api(f"{CHECKS}.CheckError")) as refused:
        record_check(unchecked.store, unchecked.version, [])
    monkeypatch.undo()
    assert _reason(refused.value) == "check_record_unwritten"
    assert not os.path.lexists(_path(unchecked)), "a cut write left a record"
    assert _stray_names(unchecked) == [], "a cut write left its temporary name"
    assert _read(unchecked) is None and leftovers(unchecked.store)["work_left"] == 0


def test_a_record_that_came_while_another_was_written_is_never_replaced(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The record is there, unseen by the writer's first look; the look under the lock still
    # finds it, and the record is not replaced.
    before = _path(made).read_bytes()
    checks = __import__(CHECKS, fromlist=["os"])
    real = os.path.lexists
    looks: list[str] = []

    def first_look_misses(path: Any) -> bool:  # noqa: ANN401
        looks.append(str(path))
        return False if len(looks) == 1 else real(path)

    monkeypatch.setattr(checks.os.path, "lexists", first_look_misses)
    with pytest.raises(api(f"{CHECKS}.CheckError")) as refused:
        record_check(made.store, made.version, [])
    monkeypatch.undo()
    assert _reason(refused.value) == "check_recorded", "a record was replaced"
    assert _path(made).read_bytes() == before
    assert _stray_names(made) == []


def test_the_harness_puts_a_record_in_place_without_a_second_name(
    unchecked: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks = __import__(CHECKS, fromlist=["os"])

    def linked(*_: Any, **__: Any) -> None:  # noqa: ANN401
        pytest.fail("the record was put in place by a second name")

    monkeypatch.setattr(checks.os, "link", linked)
    record_check(unchecked.store, unchecked.version, [])
    assert _path(unchecked).stat().st_nlink == 1


@pytest.mark.parametrize("how", ["not a record", "a flagged task taken out"])
def test_a_record_that_cannot_be_read_says_which_file_and_what_a_person_does(
    made: StandInStore, how: str
) -> None:
    _edit(made, how)
    with pytest.raises(api(f"{CHECKS}.CheckError")) as refused:
        _read(made)
    words = str(refused.value)
    assert str(_path(made)) in words, "the refusal does not name the file"
    assert "delete it by hand" in words and "deliberate act" in words, words
    assert "refused once the register holds a measurement" in words, words
