"""An import refuses in words, never in a traceback, and looks for a result again as it writes.

A kept stream that cannot be read as one (a written answer holding a lone surrogate, which no
file holds; a line nested past what the parser reads) is the reader's own refusal, and the
command ends in a plain one for any refusal of the import. A new check's printed line carries
the version and its own record's digest, and still agrees with its kept session. The look for
"no result yet" is made again under the record's writers' lock, just before the record is put
in place, and the import holds the role's work root as the check does, so a result that came
after the first look is not missed. A run root the look cannot read is named, with what a person
does about it. A record whose directory could not be synced after it was put in place is said to
be there.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
from pathlib import Path
from typing import Any

import pytest
from exposure_fixtures import (
    StandInStore,
    api,
    record_check,
    stand_in_store,
    with_run_root,
)
from kept_check_fixtures import given, kept_session, printed

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root

CHECKS = "physgate.evaluation.tiers.checks"
SESSIONS = "physgate.evaluation.tiers.check_sessions"
EXPOSURE = "physgate.evaluation.tiers.exposure"
STORE = "physgate.evaluation.tiers.store"
UNCLEAR = "check_session_unclear"


@pytest.fixture
def unchecked(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "u", checked=False)


def _path(made: StandInStore) -> Path:
    path: Path = api(f"{CHECKS}.check_path")(made.store, "control", made.version)
    return path


def _first(made: StandInStore) -> str:
    return sorted(given(made.store, made.version))[0]


def _reason(call: Any) -> str | None:  # noqa: ANN401
    """The refusal ``call`` ends in: its ``refused_because``, the type of anything else raised."""
    check_error = api(f"{CHECKS}.CheckError")
    try:
        call()
    except check_error as exc:
        return str(exc.context.get("refused_because"))
    except Exception as exc:  # noqa: BLE001 - what escaped is what the row is about
        return type(exc).__name__
    return None


def _import(
    tmp_path: Path,
    made: StandInStore,
    capsys: pytest.CaptureFixture[str],
    *,
    line: dict[str, Any] | None = None,
) -> tuple[int | None, dict[str, Any], str | None]:
    """The command's exit code and its last line, or what escaped it in place of both."""
    args = ["per-role", "record-check", "--role", "control", "--store", str(made.store)]
    args += ["--version", made.version, "--implementer-model", "claude-opus-5-5"]
    if line is not None:
        source = tmp_path / "printed.json"
        source.write_text(json.dumps(line) + "\n")
        args += ["--from", str(source)]
    try:
        code = main(args)
    except Exception as exc:  # noqa: BLE001 - a traceback is what the row is about
        capsys.readouterr()
        return None, {}, type(exc).__name__
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1]) if out else {}, None


def _rewrite_stream(here: Path, change: Any) -> None:  # noqa: ANN401
    """The kept stream with each line passed through ``change``, a line in, lines out."""
    stream = here / "stdout.jsonl"
    lines = [json.loads(raw) for raw in stream.read_text().splitlines()]
    out: list[str] = []
    for line in lines:
        out += change(line)
    stream.write_text("".join(f"{raw}\n" for raw in out))


def _lone_surrogate(here: Path) -> None:
    """The answer's write holds a lone surrogate: escaped in the stream, as JSON allows."""

    def change(line: dict[str, Any]) -> list[str]:
        for block in line.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("name") == "Write":
                block["input"]["content"] = '{"\ud800": 1}'
        return [json.dumps(line)]

    _rewrite_stream(here, change)


def _nested_line(here: Path) -> None:
    """A line nested far past what the parser reads, before the stream's last line."""

    def change(line: dict[str, Any]) -> list[str]:
        if (line.get("type"), line.get("subtype")) == ("system", "init"):
            return [json.dumps(line), "[" * 200_000 + "]" * 200_000]
        return [json.dumps(line)]

    _rewrite_stream(here, change)


@pytest.mark.parametrize(
    "spoil", [_lone_surrogate, _nested_line], ids=["a lone surrogate", "a line nested deep"]
)
def test_a_stream_that_cannot_be_read_as_one_is_the_reader_s_own_refusal(
    unchecked: StandInStore,
    spoil: Any,  # noqa: ANN401
) -> None:
    here = kept_session(unchecked.store, unchecked.version)
    spoil(here)
    reason = _reason(lambda: api(f"{SESSIONS}.read_kept")(here))
    assert reason == UNCLEAR, f"a stream that cannot be read is not the reader's refusal: {reason}"


@pytest.mark.parametrize(
    "spoil", [_lone_surrogate, _nested_line], ids=["a lone surrogate", "a line nested deep"]
)
def test_the_import_ends_in_a_plain_refusal_for_a_stream_that_cannot_be_read(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    spoil: Any,  # noqa: ANN401
) -> None:
    spoil(kept_session(unchecked.store, unchecked.version))
    code, said, escaped = _import(tmp_path, unchecked, capsys)
    assert escaped is None, f"the import ended in a traceback ({escaped}), not a plain refusal"
    assert (code, said.get("refused_because")) == (1, UNCLEAR)
    assert not os.path.lexists(_path(unchecked))


def test_any_error_of_the_import_ends_in_a_plain_refusal(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def breaks(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("something the import did not foresee")

    monkeypatch.setattr(f"{CHECKS}.import_check", breaks)
    code, said, escaped = _import(tmp_path, unchecked, capsys)
    assert escaped is None, f"the import ended in a traceback ({escaped}), not a plain refusal"
    assert code == 1 and said.get("refused_because") == "import_failed", said
    assert "RuntimeError" in str(said.get("error")), said


def test_a_printed_line_nested_past_any_does_not_agree(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    source = tmp_path / "nested.json"
    source.write_text("[" * 30_000 + "]" * 30_000 + "\n")
    args = ["per-role", "record-check", "--role", "control", "--store", str(unchecked.store)]
    args += ["--version", unchecked.version, "--implementer-model", "claude-opus-5-5"]
    escaped = None
    try:
        code = main([*args, "--from", str(source)])
    except Exception as exc:  # noqa: BLE001 - a traceback is what the row is about
        escaped, code = type(exc).__name__, None
    assert escaped is None, f"a nested printed line ended in a traceback ({escaped})"
    said = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (code, said.get("refused_because")) == (1, "check_answer_disagrees"), said
    assert not os.path.lexists(_path(unchecked))


def test_a_new_check_s_own_printed_line_agrees_with_its_kept_session(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # A session of the new kind that needs the line: a call that is no read followed its write.
    # Its line names the version and the digest of the record the check wrote (since removed).
    after = [("Bash", {"command": "python3 tidy.py", "description": "x"})]
    kept_session(unchecked.store, unchecked.version, after=after)
    line = printed([_first(unchecked)], version=unchecked.version, record="c" * 64)
    code, said, escaped = _import(tmp_path, unchecked, capsys, line=line)
    assert escaped is None, escaped
    assert code == 0, f"a new check's own printed line did not agree with its session: {said}"
    # What it names as its record is a record's digest, or the line is not the check's.
    other = stand_in_store(tmp_path / "o", checked=False)
    kept_session(other.store, other.version, after=after)
    line = printed([_first(other)], version=other.version, record="not a digest")
    code, said, _ = _import(tmp_path, other, capsys, line=line)
    assert (code, said.get("refused_because")) == (1, "check_answer_disagrees"), said


def _measure(made: StandInStore) -> None:
    api(f"{EXPOSURE}.record_measurement")(
        made.store, "control", made.version, measured="gaps", key="e" * 64
    )


def test_a_measurement_after_the_first_look_is_seen_as_the_record_is_written(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exposure = __import__(EXPOSURE, fromlist=["results_refusal"])
    real = exposure.results_refusal
    looks: list[str] = []

    def then_measured(store: Path, role: str, version: str) -> Any:  # noqa: ANN401
        found = real(store, role, version)
        looks.append(version)
        if len(looks) == 1:
            # Between the first look and the write: a measurement of the version is counted.
            _measure(unchecked)
        return found

    monkeypatch.setattr(exposure, "results_refusal", then_measured)
    kept_session(unchecked.store, unchecked.version)
    code, said, escaped = _import(tmp_path, unchecked, capsys)
    assert escaped is None, escaped
    assert (code, said.get("refused_because")) == (1, "version_measured"), (
        "a result that came after the first look was missed as the record was written"
    )
    assert not os.path.lexists(_path(unchecked)), "a check was recorded after a result existed"


def test_the_record_writer_looks_for_a_result_again_under_its_lock(tmp_path: Path) -> None:
    # The check and the import both put their record in place through the writer.
    made = stand_in_store(tmp_path / "w", checked=False)
    _measure(made)
    reason = _reason(lambda: record_check(made.store, made.version, []))
    assert reason == "version_measured", (
        f"the writer put a record in place after a result: {reason}"
    )
    assert not os.path.lexists(_path(made))


def test_the_writer_s_look_and_its_rename_hold_the_register_from_its_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No measurement or exposure line can be appended between the writer's look and the
    # rename: a writer of the register, trying its lock as the look is made, is held off.
    made = stand_in_store(tmp_path / "h", checked=False)
    exposure = __import__(EXPOSURE, fromlist=["results_refusal"])
    real = exposure.results_refusal
    held: list[bool] = []

    def a_writer_tries(store: Path, role: str, version: str) -> Any:  # noqa: ANN401
        lock = os.open(withheld_root(store, "control") / "register.lock", os.O_RDWR)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(lock)
        return real(store, role, version)

    monkeypatch.setattr(exposure, "results_refusal", a_writer_tries)
    record_check(made.store, made.version, [])
    assert held == [True], "a writer of the register could append between the look and the write"


def test_the_import_holds_the_work_root_as_the_check_does(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    with api(f"{STORE}.holding_work_root")(unchecked.store, "control"):
        code, said, escaped = _import(tmp_path, unchecked, capsys)
    assert escaped is None, escaped
    assert (code, said.get("refused_because")) == (1, "session_lives"), (
        "the import was made while another session's place in the work root was held"
    )
    assert not os.path.lexists(_path(unchecked))


def test_a_run_root_that_is_gone_is_named_with_what_a_person_does(
    tmp_path: Path, unchecked: StandInStore
) -> None:
    root = with_run_root(unchecked, tmp_path / "runs")
    root.rmdir()
    found = api(f"{EXPOSURE}.results_refusal")(unchecked.store, "control", unchecked.version)
    assert found is not None and found[0] == "run_roots_unread", found
    assert str(root) in found[1], f"the refusal does not name the root: {found[1]}"
    assert "a person" in found[1].lower(), (
        f"the refusal does not say what a person does: {found[1]}"
    )


def test_a_run_root_past_the_walk_s_bound_is_named_with_what_a_person_does(
    tmp_path: Path, unchecked: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = with_run_root(unchecked, tmp_path / "runs")
    for n in range(5):
        (root / f"entry-{n}").write_text("x")
    monkeypatch.setattr(__import__(EXPOSURE, fromlist=["MOST_ENTRIES"]), "MOST_ENTRIES", 3)
    error = api(f"{EXPOSURE}.ExposureError")
    with pytest.raises(error) as refused:
        api(f"{EXPOSURE}.results_refusal")(unchecked.store, "control", unchecked.version)
    words = str(refused.value)
    assert "entries" in words and str(root) in words, f"the root is not named: {words}"
    assert "a person" in words.lower(), f"the refusal does not say what a person does: {words}"


def test_a_record_whose_directory_sync_failed_is_said_to_be_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = stand_in_store(tmp_path / "y", checked=False)
    checks = __import__(CHECKS, fromlist=["_sync_directory"])

    def fails(_directory: Path) -> None:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(checks, "_sync_directory", fails)
    check_error = api(f"{CHECKS}.CheckError")
    with pytest.raises(check_error) as refused:
        record_check(made.store, made.version, [])
    assert os.path.lexists(_path(made)), "the record was not put in place"
    reason = refused.value.context.get("refused_because")
    assert reason == "check_record_unsynced", f"a record in place is reported as {reason}"
    assert "is written" in str(refused.value), str(refused.value)
    monkeypatch.undo()
    assert api(f"{CHECKS}.read_check")(made.store, "control", made.version) is not None
