"""A blind check that answers records its answer beside the version, and a version is checked once.

The session is the scripted stand-in the authoring rows use, so every step after it runs for
real. A check that answers leaves the version's check record in the role's root: the counts, the
flagged tasks by digest, the checking model and its pins, and when it ran; what it returns names
the version and the record's digest, and the record names the session the check kept. A second
check of the version is refused before its session starts, the first record kept: running a check
again until it passes is what the record stops. So is a first check once the register holds a
measurement or an exposure of the version, or a run names it: what a check leaves out is chosen
before any result exists. A check that gives no answer leaves no record; one that flags none
records that it flagged none. The store holds a sound record in place.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _answers,
    _check,
    _held_tier,
    _plan,
    _setup,
    check_setup,
    check_work,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import QUESTIONS, blind_check
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.checks import CheckPins, check_path, read_check
from physgate.evaluation.tiers.exposure import mark_exposed, record_measurement
from physgate.evaluation.tiers.store import leftovers


def _one_flagged(keys: list[str]) -> dict[str, Any]:
    found = {k: dict.fromkeys(QUESTIONS, True) for k in keys}
    found[sorted(keys)[0]]["answerable_as_asked"] = False
    return found


def test_a_check_that_answers_leaves_its_record_beside_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _ = _check(tmp_path, monkeypatch, _answers(_one_flagged))
    store, version = _plan(tmp_path).store, str(out["version"])
    path = check_path(store, "control", version)
    assert path.is_file(), "the check's answer was not recorded"
    assert (
        path.parent == store / "control" and not (store / "control" / version / path.name).exists()
    )
    record = read_check(store, "control", version)
    assert record is not None and out["record"] == record.sha256
    assert (record.tasks, record.all_yes, list(record.flagged)) == (8, 7, out["flagged"])
    assert record.source == "check" and record.pins.model == "claude-sonnet-5"
    assert isinstance(record.pins, CheckPins), "a check's own record carries the pins it was given"
    assert record.pins.implementer_model == "claude-opus-5-5" and record.pins.endpoint == "given"
    assert record.session.tokens == 1234
    kept = _plan(tmp_path).root / "withheld" / "check" / "s-1" / "stdout.jsonl"
    assert record.kept.session_id == "s-1" and record.kept.bound_by == "ran"
    assert record.kept.stream_sha256 == hashlib.sha256(kept.read_bytes()).hexdigest()
    assert leftovers(store)["work_left"] == 0, "the record lies out of place"


def test_a_second_check_of_the_version_is_refused_before_its_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _ = _check(tmp_path, monkeypatch, _answers(_one_flagged))
    store, version = _plan(tmp_path).store, str(out["version"])
    assert check_path(store, "control", version).is_file(), "the first check left no record"
    before = check_path(store, "control", version).read_bytes()
    again = FakeSession(_answers(lambda keys: {k: dict.fromkeys(QUESTIONS, True) for k in keys}))
    monkeypatch.setattr(author_session, "run_session", again)
    setup = dataclasses.replace(
        check_setup(store, _setup(tmp_path / "private"), "again"),
        held_out_canaries=root_canaries(store / "control"),
    )
    with pytest.raises(AuthoringError) as refused:
        blind_check(
            store,
            "control",
            version,
            setup,
            check_work(store, "again"),
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    assert refused.value.context.get("refused_because") == "check_recorded", "checked twice"
    assert again.calls == [], "a second check's session ran"
    assert check_path(store, "control", version).read_bytes() == before


def test_a_check_that_gives_no_answer_leaves_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _ = _check(tmp_path, monkeypatch, _answers(lambda keys: [True] * len(keys)))
    assert out["answered"] is False
    store = _plan(tmp_path).store
    assert not any(p.name.endswith(".check.json") for p in (store / "control").iterdir())


def test_what_the_check_returns_and_records_names_no_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _ = _check(tmp_path, monkeypatch, _answers(_one_flagged))
    store, version = _plan(tmp_path).store, str(out["version"])
    assert check_path(store, "control", version).is_file(), "the check left no record"
    text = json.dumps(out) + check_path(store, "control", version).read_text()
    assert "control.t" not in text and "Hold the plant" not in text


def _first_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, before: Any) -> Any:  # noqa: ANN401
    """A version's first check, made after ``before`` did something to the store; its refusal."""
    plan, version = _held_tier(tmp_path, monkeypatch)
    before(plan.store, version, tmp_path)
    fake = FakeSession(_answers(_one_flagged))
    monkeypatch.setattr(author_session, "run_session", fake)
    setup = dataclasses.replace(
        check_setup(plan.store, _setup(tmp_path / "private")),
        held_out_canaries=root_canaries(plan.root),
    )
    with pytest.raises(AuthoringError) as refused:
        blind_check(
            plan.store,
            plan.role,
            version,
            setup,
            check_work(plan.store),
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    assert fake.calls == [], "a check's session ran after a result of its version existed"
    assert not check_path(plan.store, "control", version).exists(), "a check was recorded"
    return refused.value


def _measured(store: Path, version: str, _: Path) -> None:
    record_measurement(store, "control", version, measured="gaps", key="e" * 64)


def _exposed(store: Path, version: str, _: Path) -> None:
    mark_exposed(store, "control", version, by="a person", reason="opened a task file")


@pytest.mark.parametrize(
    ("before", "reason"),
    [(_measured, "version_measured"), (_exposed, "version_exposed")],
    ids=["a measurement", "an exposure"],
)
def test_no_first_check_is_made_once_a_result_of_the_version_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: Any,
    reason: str,  # noqa: ANN401
) -> None:
    refused = _first_check(tmp_path, monkeypatch, before)
    assert refused.context.get("refused_because") == reason, refused


def test_a_check_that_flags_none_records_that_it_flagged_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _ = _check(
        tmp_path,
        monkeypatch,
        _answers(lambda keys: {k: dict.fromkeys(QUESTIONS, True) for k in keys}),
    )
    record = read_check(_plan(tmp_path).store, "control", str(out["version"]))
    assert record is not None and (record.flagged, record.all_yes) == ((), 8)
