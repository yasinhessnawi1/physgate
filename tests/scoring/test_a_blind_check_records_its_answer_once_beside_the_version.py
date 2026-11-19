"""A blind check that answers records its answer beside the version, and a version is checked once.

The session is the scripted stand-in the authoring rows use, so every step after it runs for
real. A check that answers leaves the version's check record in the role's root: the counts, the
flagged tasks by digest, the checking model and its pins, and when it ran; what it returns names
the version and the record's digest. A second check of the version is refused before its session
starts, the first record kept: running a check again until it passes is what the record stops. A
check that gives no answer leaves no record. The store holds a sound record in place.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _answers,
    _check,
    _plan,
    _setup,
    check_setup,
    check_work,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import QUESTIONS, blind_check
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.checks import check_path, read_check
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
    assert record.pins.implementer_model == "claude-opus-5-5" and record.pins.endpoint == "given"
    assert record.session.tokens == 1234
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
