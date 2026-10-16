"""A run whose sessions record series seals each record, lists it, and reruns exactly.

Through the real loop, the real change check, real git and the real collection, with a
stand-in session that runs a stand-in recording script (no physics; numbers made up and
labelled so). The series seals are part of the exact rerun comparison: a rerun whose record
differs is not called exact, and the comparison names where they part.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from observe_rig import fake_driver, fake_run, target_repo

from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.rerun import rerun
from physgate.orchestrator.events import Merged, ProposalsChecked, SessionEnded, read_events
from physgate.series.reader import attempt_records, read_record

BRIEF = "Build two modules.\n"
ELSEWHERE = "elsewhere"


@pytest.fixture(autouse=True)
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


def _recorded(tmp_path: Path, repo: Path, seed: int) -> Path:
    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    return fake_run(tmp_path, "run-a", repo, overrides={"brief_sha256": digest}, records=seed)


def _rerun(tmp_path: Path, run: Path, repo: Path, seed: int) -> Any:  # noqa: ANN401
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    return rerun(
        run,
        brief=brief,
        run_id="run-r",
        run_dir=tmp_path / ELSEWHERE / "run-r",
        target=repo,
        install=tmp_path / "install",
        review_root=tmp_path / "review-scratch",
        driver=fake_driver(tmp_path / ELSEWHERE, repo, records=seed),
    )


def test_every_session_s_record_is_sealed_checked_merged_and_listed(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    run = _recorded(tmp_path, repo, seed=7)
    events = read_events(run / "events.jsonl")
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert len(ended) == 2
    assert all([r.record_id for r in e.series.records] == ["step"] for e in ended)
    assert all(e.series.refused == () for e in ended)
    checked = [e for e in events if isinstance(e, ProposalsChecked)]
    assert [c.refused_by for c in checked] == [None, None]
    assert len([e for e in events if isinstance(e, Merged)]) == 2
    for session in ended:
        (entry,) = attempt_records(events, session.subtask_id, session.attempt)
        record = read_record(entry.path(run), entry.seal())
        assert record.inputs["seed"].value == 7
    hashes = read_manifest(run).artefacts.series
    assert sorted((h.subtask_id, h.sha256) for h in hashes) == sorted(
        (e.subtask_id, e.series.records[0].sha256) for e in ended
    )
    branch = f"physgate/{json.loads((run / 'run.json').read_text())['run_id']}/run"
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", branch],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert not [f for f in listed if f.startswith(".physgate/series")]
    assert not [f for f in listed if "__pycache__" in f and f.startswith(".physgate/lib")]


def test_a_rerun_that_records_the_same_series_is_exact(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    run = _recorded(tmp_path, repo, seed=7)
    result = _rerun(tmp_path, run, repo, seed=7)
    assert result.level == "exact" and result.reproduced and result.first is None


def test_a_rerun_whose_record_differs_is_not_exact_and_says_where(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    run = _recorded(tmp_path, repo, seed=7)
    result = _rerun(tmp_path, run, repo, seed=8)
    assert result.level == "exact" and not result.reproduced
    assert result.first is not None
    assert (result.first.record, result.first.field) == ("events", "series.records[0].sha256")
    recorded = read_events(run / "events.jsonl")[result.first.index]
    assert isinstance(recorded, SessionEnded)


class KilledError(Exception):
    """The orchestrator's process, killed."""


def _killed_and_resumed(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch, *, after_collecting: bool
) -> Path:
    """A run killed in its second subtask's session, before or after it collected; resumed."""
    import observe_rig

    digest = hashlib.sha256(BRIEF.encode()).hexdigest()
    cfg = observe_rig.start(tmp_path, "run-k", repo, brief_sha256=digest)
    real_collect = observe_rig.collect

    def killed(worktree: Path, **kwargs: Any) -> Any:  # noqa: ANN401
        if not str(kwargs["subtask_id"]).startswith("s2"):
            return real_collect(worktree, **kwargs)
        if after_collecting:
            real_collect(worktree, **kwargs)
        raise KilledError

    monkeypatch.setattr(observe_rig, "collect", killed)
    with pytest.raises(KilledError):
        observe_rig.drive(tmp_path, cfg, repo, records=7)
    monkeypatch.setattr(observe_rig, "collect", real_collect)
    assert observe_rig.drive(tmp_path, cfg, repo, records=7, resume=True) == "done"
    return tmp_path / "run-k"


def _second(run: Path) -> list[SessionEnded]:
    events = read_events(run / "events.jsonl")
    return [e for e in events if isinstance(e, SessionEnded) and e.subtask_id.startswith("s2")]


def test_a_record_left_by_a_killed_session_is_set_aside_not_taken_as_the_next_one_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = _killed_and_resumed(tmp_path, repo, monkeypatch, after_collecting=False)
    (ended,) = _second(run)
    assert [r.record_id for r in ended.series.records] == ["step"]
    assert [(e.name, e.reason) for e in ended.series.discarded][0] == (
        "step.json",
        "left in the outbox before this session began",
    )
    (entry,) = attempt_records(read_events(run / "events.jsonl"), ended.subtask_id, 1)
    assert entry.session_id == ended.session_id


def test_a_record_collected_but_never_sealed_is_never_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = target_repo(tmp_path)
    run = _killed_and_resumed(tmp_path, repo, monkeypatch, after_collecting=True)
    (ended,) = _second(run)
    collected = sorted((run / "series" / ended.subtask_id / "1").iterdir())
    assert len(collected) == 2  # the killed session's, and the resumed one's
    (entry,) = attempt_records(read_events(run / "events.jsonl"), ended.subtask_id, 1)
    assert entry.session_id == ended.session_id
    assert read_record(entry.path(run), entry.seal()).id == "step"
