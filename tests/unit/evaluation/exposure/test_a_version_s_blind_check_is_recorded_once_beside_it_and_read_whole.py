"""A version's blind check is one record beside it: written once, read whole, imported once.

The record lies in the role's root, named by the version's id, never inside the version, which is
never written again. A second record of a version is refused and the first kept; a record changed
by hand, a link, an oversized file or one that is not this version's is refused as it is read, and
lies out of place in the role's root, so nothing starts on the store. ``tiers status`` shows each
version's check by its counts alone. A measured run on a version with no check record is refused:
a held-out tier nobody checked is not scored.

An earlier check's printed answer is taken in by ``physgate per-role record-check``, once, after it
is held to the version: an answer, for as many tasks as the held-out tier holds, each flagged
digest the digest of exactly one of its tasks. It prints counts and the record's digest only.
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


# -------------------------------------------------------------- the import of an earlier check


def _printed(made: StandInStore, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """What an earlier blind check printed of ``made``'s version: task 0 flagged."""
    body: dict[str, Any] = {
        "all_yes": 7,
        "answered": True,
        "flagged": [id_digest(made.tasks["held_out"][0].id)],
        "session": {"cap": 500000, "end": "ended", "tokens": 150878, "wall_clock_s": 165.2},
        "tasks": 8,
    }
    body.update(changes)
    return body


def _import(
    tmp_path: Path,
    made: StandInStore,
    printed: dict[str, Any] | str,
    capsys: pytest.CaptureFixture[str],
    **flags: str,
) -> tuple[int, dict[str, Any], str]:
    source = tmp_path / "check.json"
    source.write_text(printed if isinstance(printed, str) else json.dumps(printed) + "\n")
    given = {
        "--model": "claude-sonnet-5",
        "--implementer-model": "claude-opus-5-5",
        "--claude-version": "2.1.301",
        "--checked": "2026-11-19",
        "--commit": "2" * 40,
        **flags,
    }
    args = ["per-role", "record-check", "--role", "control", "--store", str(made.store)]
    args += ["--version", made.version, "--from", str(source)]
    for flag, value in given.items():
        args += [flag, value]
    try:
        code = main(args)
    except SystemExit:
        pytest.fail("per-role has no record-check command taking these arguments")
    out = capsys.readouterr().out
    return code, json.loads(out.strip().splitlines()[-1]), out


def test_an_earlier_check_s_answer_is_imported_once_and_prints_counts_alone(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    code, said, out = _import(tmp_path, unchecked, _printed(unchecked), capsys)
    assert code == 0, said
    assert {k: said[k] for k in ("tasks", "all_yes", "flagged", "source")} == {
        "tasks": 8,
        "all_yes": 7,
        "flagged": 1,
        "source": "imported",
    }
    assert id_digest(unchecked.tasks["held_out"][0].id) not in out, "a flagged digest is printed"
    record = _read(unchecked)
    assert record.source == "imported" and record.pins.model == "claude-sonnet-5"
    assert record.checked == "2026-11-19" and said["record"] == record.sha256
    assert record.flagged == (id_digest(unchecked.tasks["held_out"][0].id),)
    assert leftovers(unchecked.store)["work_left"] == 0
    again, said, _ = _import(tmp_path, unchecked, _printed(unchecked), capsys)
    assert (again, said.get("refused_because")) == (1, "check_recorded"), "imported twice"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("no answer", "check_gave_no_answer"),
        ("another count", "check_answer_not_the_version"),
        ("counts that do not add up", "check_answer_not_the_version"),
        ("a visible task flagged", "check_answer_not_the_version"),
        ("a digest of no task", "check_answer_not_the_version"),
        ("another version named", "check_answer_not_the_version"),
        ("not one line of JSON", "check_answer_unreadable"),
        ("the implementers' model", "checked_on_the_implementers_model"),
    ],
)
def test_an_answer_that_is_not_this_version_s_check_is_refused_and_nothing_recorded(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    case: str,
    reason: str,
) -> None:
    flags: dict[str, str] = {}
    printed: dict[str, Any] | str = _printed(unchecked)
    if case == "no answer":
        printed = {"answered": False, "session": {}, "tasks": 8}
    elif case == "another count":
        printed = _printed(unchecked, tasks=9, all_yes=8)
    elif case == "counts that do not add up":
        printed = _printed(unchecked, all_yes=6)
    elif case == "a visible task flagged":
        printed = _printed(unchecked, flagged=[id_digest(unchecked.tasks["visible"][0].id)])
    elif case == "a digest of no task":
        printed = _printed(unchecked, flagged=["0" * 16])
    elif case == "another version named":
        printed = _printed(unchecked, version="d" * 64)
    elif case == "not one line of JSON":
        printed = "the check printed this"
    else:
        flags["--model"] = "claude-opus-5-5"
    code, said, out = _import(tmp_path, unchecked, printed, capsys, **flags)
    assert (code, said.get("refused_because")) == (1, reason), "an answer not the version's"
    assert not _path(unchecked).exists(), "a refused answer was recorded"
    for task in unchecked.tasks["held_out"]:
        assert task.id not in out


def test_the_import_refuses_on_the_command_line_inside_a_harness_session(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", "1")
    code, said, _ = _import(tmp_path, unchecked, _printed(unchecked), capsys)
    assert (code, said.get("refused_because")) == (1, "inside_a_session")
    assert not os.path.lexists(_path(unchecked))
