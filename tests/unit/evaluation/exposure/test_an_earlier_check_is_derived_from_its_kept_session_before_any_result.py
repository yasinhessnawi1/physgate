"""An earlier blind check's record is derived from its kept session, once, before any result.

``physgate per-role record-check`` takes nothing a person writes but the implementers' model: the
answer is the one the kept session's stream shows it wrote to its answer file by its file-write
tool, the flagged tasks are computed again from it and the version's held-out tier, and the model,
the binary, the time and the spend are the session's own. The record names the session, its
stream's digest, and how the session is tied to the version: by its whole read of the tasks it
was given, held to what the version's held-out tier gives a check now, or else by its answer's
keys alone, the digests of the version's held-out task ids. The line the check printed, given,
must agree with it exactly; where a tool call named the answer file after its last write, it
must be given.

No session, or more than one that answered, and nothing is recorded: a person must look. A
session that ended without an answer, answered on another tier, or whose stream showed a canary
is passed over. And once the register holds a measurement or an exposure of the version, or a
run or a raw record names it, the import is refused, as the check itself is: what is left out is
chosen before any result exists. It prints counts and the record's digest only.
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
    harness_run,
    stand_in_store,
    with_run_root,
)
from kept_check_fixtures import (
    ANSWERED,
    SPENT,
    all_yes,
    given,
    kept_session,
    printed,
)

from physgate.cli import main
from physgate.evaluation.tiers.check_tasks import QUESTIONS
from physgate.evaluation.tiers.store import leftovers, withheld_root
from physgate.evaluation.tiers.task import id_digest

CHECKS = "physgate.evaluation.tiers.checks"
EXPOSURE = "physgate.evaluation.tiers.exposure"
OTHER = "0b7f3c6e-1d2a-4e9b-8c5f-6a7d8e9f0a1b"


@pytest.fixture
def unchecked(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "u", checked=False)


def _path(made: StandInStore) -> Path:
    path: Path = api(f"{CHECKS}.check_path")(made.store, "control", made.version)
    return path


def _read(made: StandInStore) -> Any:  # noqa: ANN401
    return api(f"{CHECKS}.read_check")(made.store, "control", made.version)


def _first(made: StandInStore) -> str:
    """The digest the stand-in answer flags: the first of the version's held-out keys."""
    return sorted(given(made.store, made.version))[0]


def _import(
    tmp_path: Path,
    made: StandInStore,
    capsys: pytest.CaptureFixture[str],
    *,
    line: dict[str, Any] | str | None = None,
    implementer: str = "claude-opus-5-5",
) -> tuple[int, dict[str, Any], str]:
    args = ["per-role", "record-check", "--role", "control", "--store", str(made.store)]
    args += ["--version", made.version, "--implementer-model", implementer]
    if line is not None:
        source = tmp_path / "printed.json"
        source.write_text(line if isinstance(line, str) else json.dumps(line) + "\n")
        args += ["--from", str(source)]
    try:
        code = main(args)
    except SystemExit:
        pytest.fail("per-role has no record-check command taking these arguments")
    out = capsys.readouterr().out
    return code, json.loads(out.strip().splitlines()[-1]), out


def _names_no_task(made: StandInStore, out: str) -> None:
    for task in made.tasks["held_out"]:
        assert task.id not in out and id_digest(task.id) not in out, "the import named a task"


def test_the_record_is_derived_from_the_kept_session_alone_and_prints_counts(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    here = kept_session(unchecked.store, unchecked.version)
    code, said, out = _import(tmp_path, unchecked, capsys)
    assert code == 0, said
    assert {k: said[k] for k in ("tasks", "all_yes", "flagged", "source")} == {
        "tasks": 8,
        "all_yes": 7,
        "flagged": 1,
        "source": "imported",
    }
    _names_no_task(unchecked, out)
    record = _read(unchecked)
    assert said["record"] == record.sha256
    assert record.flagged == (_first(unchecked),), "the flagged task is not the session's"
    assert (record.pins.model, record.pins.claude_version) == ("claude-sonnet-5", "2.1.322")
    assert record.pins.implementer_model == "claude-opus-5-5"
    assert record.checked == ANSWERED, "the time is not the one the stream gives the answer"
    assert record.session.model_dump(exclude_none=True) == SPENT
    import hashlib

    stream = hashlib.sha256((here / "stdout.jsonl").read_bytes()).hexdigest()
    assert (record.kept.session_id, record.kept.stream_sha256) == (here.name, stream)
    assert record.kept.bound_by == "tasks_read", "the whole read of the tasks did not bind it"
    assert leftovers(unchecked.store)["work_left"] == 0


def test_a_session_whose_stream_holds_no_whole_read_is_bound_by_its_answer_s_keys(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, read="part")
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert code == 0, said
    assert _read(unchecked).kept.bound_by == "answer_keys", "a part read bound it by content"


def test_a_printed_line_that_agrees_is_taken_and_one_that_does_not_refuses(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    other = sorted(given(unchecked.store, unchecked.version))[1]
    for line in (
        printed([other]),
        printed([_first(unchecked)], session={**SPENT, "tokens": 1}),
        printed([]),
        "the check printed this",
    ):
        code, said, _ = _import(tmp_path, unchecked, capsys, line=line)
        assert (code, said.get("refused_because")) == (1, "check_answer_disagrees"), line
        assert not os.path.lexists(_path(unchecked)), "a line that disagreed was recorded"
    code, said, _ = _import(tmp_path, unchecked, capsys, line=printed([_first(unchecked)]))
    assert code == 0, said


def test_no_kept_session_that_answered_and_nothing_is_recorded(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_missing")
    kept_session(unchecked.store, unchecked.version, write="none")
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_missing")
    assert not os.path.lexists(_path(unchecked))


def test_two_sessions_that_answered_are_refused_for_a_person_to_look_at(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    kept_session(unchecked.store, unchecked.version, all_yes, session_id=OTHER)
    code, said, out = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_sessions_several")
    assert "a person must look" in said["error"]
    assert not os.path.lexists(_path(unchecked))
    _names_no_task(unchecked, out)


def test_one_that_answered_beside_sessions_that_did_not_is_the_one_imported(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, write="none", session_id=OTHER)
    # A session whose stream showed a canary: the check did not take its answer.
    seen = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"
    kept_session(unchecked.store, unchecked.version, all_yes, session_id=seen)
    record = json.loads(
        (withheld_root(unchecked.store, "control") / "check" / seen / "record.json").read_text()
    )
    record["held_out_seen"] = True
    (withheld_root(unchecked.store, "control") / "check" / seen / "record.json").write_text(
        json.dumps(record)
    )
    # A session the runner could not record: its check took no answer.
    (withheld_root(unchecked.store, "control") / "check" / "unrecorded-0123456789ab").mkdir()
    answered = kept_session(unchecked.store, unchecked.version)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert code == 0, said
    assert _read(unchecked).kept.session_id == answered.name
    assert _read(unchecked).flagged == (_first(unchecked),)


def test_an_answer_on_another_tier_is_not_this_version_s(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # The keys of another tier: a check of another version, passed over.
    tasks = {"0" * 16: {"brief": "another tier's task"}}
    kept_session(unchecked.store, unchecked.version, read="none", tasks=tasks)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_missing")


def test_a_whole_read_of_other_tasks_under_the_same_keys_is_not_this_version_s_check(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    tasks = given(unchecked.store, unchecked.version)
    first = sorted(tasks)[0]
    tasks[first] = {**tasks[first], "brief": "another brief under the same key"}
    kept_session(unchecked.store, unchecked.version, tasks=tasks)
    code, said, out = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_not_the_version")
    assert not os.path.lexists(_path(unchecked))
    assert "another brief" not in out


def test_a_write_that_was_refused_is_not_the_answer(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # After the answer landed, a second write of another answer, which the hook refused.
    kept_session(unchecked.store, unchecked.version, refused_after=all_yes)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert code == 0, said
    assert _read(unchecked).flagged == (_first(unchecked),), "a refused write was taken"


def test_a_tool_call_on_the_answer_after_its_write_needs_the_printed_line(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    after = [("Bash", {"command": "python3 -m json.tool answers.json", "description": "x"})]
    kept_session(unchecked.store, unchecked.version, after=after)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_answer_not_derivable")
    assert not os.path.lexists(_path(unchecked))
    code, said, _ = _import(tmp_path, unchecked, capsys, line=printed([_first(unchecked)]))
    assert code == 0, said


def test_a_read_of_the_answer_after_its_write_changes_nothing(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(
        unchecked.store, unchecked.version, after=[("Read", {"file_path": "answers.json"})]
    )
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert code == 0, said


def test_an_answer_written_by_a_shell_command_alone_cannot_be_told(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, write="shell")
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_unclear")
    assert "a person must look" in said["error"]


def test_a_session_on_the_implementers_model_is_refused(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, model="claude-opus-5-5")
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "checked_on_the_implementers_model")


def test_a_version_with_a_record_is_not_imported_again(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    assert _import(tmp_path, unchecked, capsys)[0] == 0
    before = _path(unchecked).read_bytes()
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_recorded"), "imported twice"
    assert _path(unchecked).read_bytes() == before


def _measured(made: StandInStore, tmp_path: Path) -> None:
    api(f"{EXPOSURE}.record_measurement")(
        made.store, "control", made.version, measured="gaps", key="e" * 64
    )


def _exposed(made: StandInStore, tmp_path: Path) -> None:
    api(f"{EXPOSURE}.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened a task file"
    )


def _a_run(made: StandInStore, tmp_path: Path) -> None:
    harness_run(with_run_root(made, tmp_path / "runs"), made.tasks["visible"][0], made)


def _a_raw_record(made: StandInStore, tmp_path: Path) -> None:
    from physgate.evaluation.tiers.heldout import tier_digest

    place = withheld_root(made.store, "control") / "baseline" / "round" / "t0"
    place.mkdir(parents=True)
    digests = [tier_digest(Path(root)) for root in made.held_out]
    raw = {"held_out_seen": False, "held_out_sha256": digests, "pins": {}}
    (place / "raw.json").write_text(json.dumps(raw))


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_measured, "version_measured"),
        (_exposed, "version_exposed"),
        (_a_run, "version_has_runs"),
        (_a_raw_record, "version_has_runs"),
    ],
    ids=["a measurement", "an exposure", "a run", "a raw record"],
)
def test_nothing_is_imported_once_a_result_of_the_version_exists(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    result: Any,  # noqa: ANN401
    reason: str,
) -> None:
    kept_session(unchecked.store, unchecked.version)
    result(unchecked, tmp_path)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, reason), "imported after a result"
    assert not os.path.lexists(_path(unchecked)), "a check was chosen after a result existed"


def test_the_import_refuses_on_the_command_line_inside_a_harness_session(
    tmp_path: Path,
    unchecked: StandInStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept_session(unchecked.store, unchecked.version)
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", "1")
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "inside_a_session")
    assert not os.path.lexists(_path(unchecked))


def test_an_answer_that_flags_none_is_imported_with_none_left_out(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, all_yes)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert code == 0 and (said["flagged"], said["all_yes"]) == (0, 8), said
    assert _read(unchecked).flagged == ()


def test_the_answer_is_read_as_the_check_reads_its_answer_file(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # Strings where booleans belong: the check gives no answer, so there is none to import.
    def strings(keys: list[str]) -> dict[str, Any]:
        return {k: dict.fromkeys(QUESTIONS, "yes") for k in keys}

    kept_session(unchecked.store, unchecked.version, strings)
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_missing")


def test_a_kept_session_that_is_not_one_session_s_is_refused_for_a_person_to_look_at(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version, record={"session_id": OTHER})
    code, said, _ = _import(tmp_path, unchecked, capsys)
    assert (code, said.get("refused_because")) == (1, "check_session_unclear")
    assert not os.path.lexists(_path(unchecked))


def test_the_printed_answer_is_the_last_line_of_what_the_check_printed(
    tmp_path: Path, unchecked: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    kept_session(unchecked.store, unchecked.version)
    line = "a line before the answer\n" + json.dumps(printed([_first(unchecked)])) + "\n"
    code, said, _ = _import(tmp_path, unchecked, capsys, line=line)
    assert code == 0, said
