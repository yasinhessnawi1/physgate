"""The gap trend: one writer (``gaps --append``), one reader (``read_gap_trend``), missing weeks.

``--append`` writes one line per run set, naming the vectors' keys and the version's measurement
count; it writes no register line of its own, since each vector's writing was the look. Each
line holds its place and the digest of the line before it, and a head beneath the role's withheld
root, where no session writes, records how many lines the trend holds and the last one's digest.
The writer takes the trend's lock. The reader is given the store and the role by its caller,
never by a line: it holds the trend to its chain and its head, so a line edited, dropped or cut
is refused (a cut or a line past the head in words that say the repair); it refuses a run set
already in the file and a line whose vectors were measured on another version; it gives a
line's numbers only when every key it names is a gaps measurement of its version in that
store's register, and says beside a line when its version has been marked exposed since. What
it returns holds no register line, no path beneath a withheld root, no name and no reason.
``gap_weeks`` shows a week with no line as missing, never filled in. The counting rule's
per-task fields are the census of ``DRIFT``.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import Measured, StandInStore, api, design, measured, stand_in_store

from physgate.cli import main
from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.tiers.store import withheld_root

WRITE = "physgate.evaluation.tiers.measure.write_vector"
READ = "physgate.evaluation.gaps.read_gap_trend"
APPEND = "physgate.evaluation.gaps.measure.append_gap_line"
MEASURE = "physgate.evaluation.gaps.measure.measure"
DESIGN = "physgate.evaluation.gaps.measure.GapsDesign"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _read(trend: Path, made: StandInStore, role: str = "control") -> Any:  # noqa: ANN401
    """The reader, given the store and the role by its caller."""
    return api(READ)(trend, store=made.store, role=role)


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))


def _vector(made: StandInStore, tier: str, m: Measured) -> Path:
    withheld = withheld_root(made.store, "control")
    key = api(WRITE)(withheld, version=made.version, tier=tier, runs=m.runs, trials=m.trials)
    return withheld / "gaps" / f"{key}.json"


def _append(
    tmp_path: Path, made: StandInStore, trend: Path, name: str = "a"
) -> tuple[int, dict[str, Any]]:
    # A second run set starts its tasks from another commit, so its runs, and their manifest
    # ids, are not the first set's.
    other: dict[str, Any] = {} if name == "a" else {"target_head": "d" * 40}
    visible = measured(made, "visible", tmp_path / f"v{name}", **other)
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / f"h{name}"))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / f"w{name}"))
    path = tmp_path / f"design-{name}.json"
    path.write_text(json.dumps(design(made, visible)))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs), "--trials"]
    argv += [str(visible.trials), "--held-out", str(held), "--validation", str(valid)]
    code = main([*argv, "--append", str(trend)])
    return code, {"argv": argv, "keys": {held.stem, valid.stem}}


def _found(tmp_path: Path, made: StandInStore, name: str = "a") -> Any:  # noqa: ANN401
    """What ``physgate gaps`` measured on a fresh run set, before anything is appended."""
    visible = measured(made, "visible", tmp_path / f"v{name}")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / f"h{name}"))
    body = design(made, visible, validation_tasks=None)
    return api(MEASURE)(
        api(DESIGN).model_validate_json(json.dumps(body)),
        runs=visible.runs,
        trials=visible.trials,
        held_out=held,
        validation=None,
    )


def _registered(made: StandInStore) -> int:
    lines = api("physgate.evaluation.tiers.exposure.register_lines")(made.store, "control")
    return len(lines)


def test_append_writes_one_line_naming_its_keys_and_no_register_line(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    visible = measured(made, "visible", tmp_path / "v")
    held = _vector(made, "held_out", measured(made, "held_out", tmp_path / "h"))
    valid = _vector(made, "validation", measured(made, "validation", tmp_path / "w"))
    before = _registered(made)
    path = tmp_path / "design.json"
    path.write_text(json.dumps(design(made, visible)))
    argv = ["gaps", "--design", str(path), "--runs", str(visible.runs), "--trials"]
    argv += [str(visible.trials), "--held-out", str(held), "--validation", str(valid)]
    assert main([*argv, "--append", str(trend)]) == 0
    assert _registered(made) == before, "--append wrote a register line of its own"
    written = trend.read_text().splitlines()
    assert len(written) == 1
    line = json.loads(written[0])
    assert set(line["keys"].values()) == {held.stem, valid.stem}
    assert line["measurements"] == 2, "the line does not carry the version's count"
    (got,) = _read(trend, made)
    assert got.numbers is not None and got.measurements == 2
    assert got.numbers.reward_hacking.gap == pytest.approx(line["numbers"]["reward_hacking"]["gap"])


def test_the_same_run_set_is_refused_a_second_time(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    code, first = _append(tmp_path, made, trend)
    assert code == 0
    assert main([*first["argv"], "--append", str(trend)]) == 1, "a run set was appended twice"
    assert len(trend.read_text().splitlines()) == 1
    trend.write_text(trend.read_text() * 2)
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    assert "line 2" in str(caught.value), caught.value


@pytest.mark.parametrize("which", [0, 1], ids=["an-earlier-line", "the-last-line"])
def test_a_line_whose_number_was_edited_is_refused(
    tmp_path: Path, made: StandInStore, which: int
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    assert _append(tmp_path, made, trend, "b")[0] == 0
    lines = trend.read_text().splitlines(keepends=True)
    line = json.loads(lines[which])
    keys = dict(line["keys"])
    line["numbers"]["reward_hacking"]["gap"] += 0.25
    assert line["keys"] == keys, "the row edits a number only"
    lines[which] = json.dumps(line) + "\n"
    trend.write_text("".join(lines))
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    assert _reason(caught.value) == "trend_broken", caught.value


def test_a_dropped_last_line_is_refused_in_words_that_say_the_repair(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    head = withheld_root(made.store, "control") / "trend.head"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    assert _append(tmp_path, made, trend, "b")[0] == 0
    trend.write_text(trend.read_text().splitlines(keepends=True)[0])
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    assert _reason(caught.value) == "trend_broken", caught.value
    said = str(caught.value)
    assert "removed" in said and "head" in said and "starts again" in said, said
    trend.unlink()  # one repair the words say: the trend and its head go, and it starts again
    head.unlink()
    assert _read(trend, made) == ()
    assert _append(tmp_path, made, trend, "c")[0] == 0
    assert len(_read(trend, made)) == 1


def test_a_line_of_another_role_is_refused_under_a_head_that_matches(
    tmp_path: Path, made: StandInStore
) -> None:
    # The control role's trend and head, copied beneath the firmware role's withheld root: the
    # chain and the head hold, and only the line's own role tells it is not firmware's.
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    other = withheld_root(made.store, "firmware")
    other.mkdir(parents=True)
    head = withheld_root(made.store, "control") / "trend.head"
    (other / "trend.head").write_bytes(head.read_bytes())
    with pytest.raises(Exception) as caught:
        _read(trend, made, "firmware")
    assert _reason(caught.value) == "trend_broken", caught.value
    assert "another role's" in str(caught.value), caught.value


def test_the_register_read_is_the_caller_s_store_never_one_a_line_names(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    elsewhere = stand_in_store(tmp_path / "elsewhere")
    with pytest.raises(Exception) as caught:
        _read(trend, elsewhere)
    assert _reason(caught.value) == "trend_broken", caught.value
    assert "no head" in str(caught.value), caught.value
    assert "store" not in json.loads(trend.read_text()), "a line names a store"


def test_a_cut_last_line_is_refused_in_words_that_say_the_repair(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    whole = trend.read_text()
    trend.write_text(whole + whole[:40])
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    said = str(caught.value)
    assert "cut" in said and "removes" in said, said
    with pytest.raises(Exception) as appended:
        api(APPEND)(trend, _found(tmp_path, made, "b"))
    assert "cut" in str(appended.value), appended.value
    trend.write_text(whole)  # the repair the words say
    assert len(_read(trend, made)) == 1


def test_a_line_past_the_head_is_refused_in_words_that_say_the_repair(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    head = withheld_root(made.store, "control") / "trend.head"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    assert head.exists(), "the trend keeps no head beneath the role's withheld root"
    first = head.read_bytes()
    assert _append(tmp_path, made, trend, "b")[0] == 0
    head.write_bytes(first)  # a write stopped between its line and its head
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    said = str(caught.value)
    assert "past" in said and "removes" in said, said


def test_the_trend_writer_waits_for_the_trend_s_lock(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    fd = os.open(withheld_root(made.store, "control") / "trend.lock", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        writer = threading.Thread(target=api(APPEND), args=(trend, found))
        writer.start()
        writer.join(1.0)
        waited = writer.is_alive()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    writer.join(30.0)
    assert waited, "the writer appended while another held the trend's lock"
    assert len(trend.read_text().splitlines()) == 1


def test_a_line_whose_keys_the_register_lacks_carries_no_number(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    api(APPEND)(trend, found.model_copy(update={"keys": {"held_out": "f" * 64}}))
    (got,) = _read(trend, made)
    assert got.numbers is None, "a line with no measurement behind it was shown as a number"
    assert got.unverified


def test_a_key_counted_as_another_kind_of_measurement_verifies_nothing(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    api("physgate.evaluation.tiers.exposure.record_measurement")(
        made.store, "control", made.version, measured="experiment", key="e" * 64
    )
    api(APPEND)(trend, found.model_copy(update={"keys": {"held_out": "e" * 64}}))
    (got,) = _read(trend, made)
    assert got.numbers is None, "a key measured as an experiment verified a gaps line"


def test_a_line_whose_vectors_were_measured_on_another_version_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    api(APPEND)(trend, found.model_copy(update={"version": "a" * 64}))
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    assert "version" in str(caught.value)


def test_a_line_whose_version_was_exposed_since_says_so(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    api("physgate.evaluation.tiers.exposure.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened a task file"
    )
    (got,) = _read(trend, made)
    said = getattr(got, "exposed_since", None)
    assert said and "exposed" in said, "the reader does not say the version was seen since"
    assert got.numbers is not None, "the line stands, with what is known said beside it"


def test_what_the_reader_returns_holds_no_register_line_path_name_or_reason(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend)[0] == 0
    (got,) = _read(trend, made)
    dumped = got.model_dump_json()
    for word in ("withheld", str(made.store), '"by"', '"reason"', '"prev"', '"kind"'):
        assert word not in dumped, f"the reader returns {word}"
    fields = set(type(got).model_fields)
    assert fields.isdisjoint({"by", "reason", "store", "path", "register"}), fields


def test_a_week_with_no_line_is_shown_missing(tmp_path: Path, made: StandInStore) -> None:
    trend = tmp_path / "gaps.jsonl"
    found = _found(tmp_path, made)
    for n, day in ((1, date(2026, 11, 2)), (3, date(2026, 11, 16))):
        line = found.model_copy(
            update={"manifest_ids": (f"{n:064x}",), "keys": {"held_out": f"{n + 1:064x}"}}
        )
        api(APPEND)(trend, line, today=day)
    lines = _read(trend, made)
    weeks = api("physgate.evaluation.gaps.gap_weeks")(lines)
    assert [w.week for w in weeks] == ["2026-W45", "2026-W46", "2026-W47"]
    assert [w.missing for w in weeks] == [False, True, False]
    assert weeks[1].lines == ()
    later = api("physgate.evaluation.gaps.gap_weeks")(lines, through=date(2026, 12, 2))
    assert [w.week for w in later][-2:] == ["2026-W48", "2026-W49"] and later[-1].missing


def test_the_per_task_fields_are_the_census_of_drift() -> None:
    per_task = api("physgate.evaluation.tiers.measure.PER_TASK")
    held = api("physgate.evaluation.tiers.measure.HELD_EQUAL")
    assert set(per_task) == {"brief_sha256", "target_head"} and set(per_task) <= set(DRIFT)
    assert tuple(held) == tuple(f for f in DRIFT if f not in per_task)


def _stale_head_once(
    monkeypatch: pytest.MonkeyPatch, trend: Path, made: StandInStore, *, writer_starts: bool
) -> None:
    """The reader's first look at the head finds the one before the last line's.

    As if a first writer had appended its line and not yet moved the head. ``writer_starts``:
    that writer made the trend's lock as it began, so it is there when the reader looks again.
    """
    import hashlib

    from physgate.evaluation.gaps import measure

    real = measure._head_of
    lock = withheld_root(made.store, "control") / "trend.lock"
    first = trend.read_bytes().splitlines(keepends=True)[0]
    looks: list[int] = []

    def head_of(fd: int | None) -> tuple[int, str] | None:
        looks.append(1)
        if len(looks) == 1:
            if writer_starts:
                lock.touch()
            return 1, hashlib.sha256(first).hexdigest()
        return real(fd)

    monkeypatch.setattr(measure, "_head_of", head_of)


def test_a_reader_that_found_no_lock_reads_again_under_the_lock_a_first_writer_made(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    assert _append(tmp_path, made, trend, "b")[0] == 0
    # As before the trend's first writer made its lock: a reader then reads unlocked.
    (withheld_root(made.store, "control") / "trend.lock").unlink()
    _stale_head_once(monkeypatch, trend, made, writer_starts=True)
    try:
        got = _read(trend, made)
    except Exception as exc:  # noqa: BLE001 - the refusal is the failure this row names
        pytest.fail(f"the reader refused what it read before the first writer ended: {exc}")
    assert len(got) == 2


def test_a_reader_with_no_lock_still_refuses_a_line_past_the_head_when_no_writer_began(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    assert _append(tmp_path, made, trend, "b")[0] == 0
    (withheld_root(made.store, "control") / "trend.lock").unlink()
    _stale_head_once(monkeypatch, trend, made, writer_starts=False)
    with pytest.raises(Exception) as caught:
        _read(trend, made)
    assert "past" in str(caught.value), caught.value


def test_a_link_in_place_of_the_trend_s_lock_is_refused_never_followed(
    tmp_path: Path, made: StandInStore
) -> None:
    trend = tmp_path / "gaps.jsonl"
    assert _append(tmp_path, made, trend, "a")[0] == 0
    lock = withheld_root(made.store, "control") / "trend.lock"
    elsewhere = tmp_path / "elsewhere.lock"
    elsewhere.write_bytes(b"")
    lock.unlink()
    lock.symlink_to(elsewhere)
    try:
        _read(trend, made)
    except Exception as exc:  # noqa: BLE001 - the refusal is what this row reads
        caught: BaseException | None = exc
    else:
        caught = None
    assert caught is not None, "the reader took a lock through a link in its place"
    assert _reason(caught) == "trend_broken", caught
    assert "lock" in str(caught), caught
