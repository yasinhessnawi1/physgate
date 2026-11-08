"""The pool never outlives the split, and a round's tiers are one version of the store.

An author pools what holds in its role's root and, once twenty-four are there, writes them as
one version: three tiers, the manifest and the round's provenance record, whole under a
temporary name and renamed last; the pool goes after the rename, with what the draw did not
take. A pool other than the author's own, a pool already drawn from, or a version still being
written holds tasks that become held-out ones with no canary yet, so no authoring or
blind-check session starts on a store that holds one. The version's visible tier is the one
tier under the root that names no canaries; a list-less tier anywhere else still refuses.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _answers,
    _setup,
    _tasks,
    _write_task,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import QUESTIONS, root_canaries
from physgate.evaluation.tiers.authoring import AuthoringError, sha256sums


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _store(tmp_path: Path) -> Path:
    return tmp_path / "private" / "store"


def _plan(tmp_path: Path, **changes: Any) -> Any:
    base: dict[str, Any] = {
        "role": "control",
        "implementer_model": "claude-opus-5-5",
        "work": tmp_path / "scratch" / "work",
        "store": _store(tmp_path),
        "seed": 5,
        "cap": 4_000_000,
    }
    base.update(changes)
    try:
        return author_session.AuthoringPlan(**base)
    except TypeError as exc:
        pytest.fail(f"an authoring plan names no tier-set store: {exc}")


def _author(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write: Any,
    session_id: str = "s-1",
    **changes: Any,
) -> tuple[Any, FakeSession, dict[str, Any]]:
    fake = FakeSession(write, session_id=session_id)
    monkeypatch.setattr(author_session, "run_session", fake)
    plan = _plan(tmp_path, **changes)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    setup = dataclasses.replace(
        _setup(tmp_path / "private"), held_out_canaries=root_canaries(_store(tmp_path) / "control")
    )
    out: dict[str, Any] = author_session.author(plan, setup)
    return plan, fake, out


def _root(tmp_path: Path) -> Path:
    return _store(tmp_path) / "control"


def test_twenty_four_pooled_tasks_become_one_version_and_no_pool_outlives_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(26), count=26)
    assert out["status"] == "split" and out.get("version") is not None
    version = _root(tmp_path) / out["version"]
    assert sorted(p.name for p in _root(tmp_path).iterdir()) == sorted(["author", out["version"]])
    assert out["pool"] == 0 and out.get("left_with_the_pool") == 2
    held = sorted(p.name for p in (version / "held_out").iterdir() if p.is_dir())
    assert len(held) == 8 and out["visible"] == sorted(
        p.name for p in (version / "visible").iterdir()
    )
    assert out["held_out_check"]["references_held"] == 8
    printed = json.dumps(out)
    assert not [name for name in held if name in printed]
    manifest = _api("physgate.evaluation.tiers.manifest.read_version")(version)
    assert manifest.version == out["version"] and manifest.held_out.count == 8
    assert out["held_out_sha256"] == manifest.held_out.sha256


@pytest.mark.parametrize(
    ("left", "reason"),
    [
        ("firmware/pool", "pool_left"),
        ("control/pool.spent", "pool_left"),
        ("control/.version-0123abcd", "temporary_version_left"),
    ],
    ids=["another role's pool", "a spent pool", "a version being written"],
)
def test_an_author_refuses_while_the_store_holds_what_only_a_split_in_progress_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, left: str, reason: str
) -> None:
    (_store(tmp_path) / left).mkdir(parents=True)
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError) as refused:
        author_session.author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert refused.value.context.get("refused_because") == reason
    assert fake.calls == []


def test_an_author_adds_to_its_own_role_s_pool_and_the_version_takes_it_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, first = _author(tmp_path, monkeypatch, _tasks(10))
    assert first["status"] == "pooled" and first["pool"] == 10

    def more(worktree: Path) -> None:
        for n in range(10, 24):
            _write_task(worktree / f"control.t{n:02d}", n)

    _, _, second = _author(
        tmp_path, monkeypatch, more, session_id="s-2", work=tmp_path / "scratch" / "work2"
    )
    assert second["status"] == "split" and second.get("left_with_the_pool") == 0
    assert not (_root(tmp_path) / "pool").exists()
    assert not (_root(tmp_path) / "pool.spent").exists()


def test_a_task_whose_id_folds_to_one_already_pooled_is_refused_at_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _author(tmp_path, monkeypatch, _tasks(3))

    def respelt(worktree: Path) -> None:
        _write_task(worktree / "control_t01", 5)
        _write_task(worktree / "control.t03", 6)

    _, _, out = _author(
        tmp_path, monkeypatch, respelt, session_id="s-2", work=tmp_path / "scratch" / "work2"
    )
    assert out["pooled"] == 1 and out["refused_because"].get("id_already_pooled") == 1, out
    pool = _store(tmp_path) / "control" / "pool"
    assert sorted(p.name for p in pool.iterdir() if p.is_dir()) == [
        "control.t00",
        "control.t01",
        "control.t02",
        "control.t03",
    ]


def test_the_version_s_provenance_names_every_session_of_its_round_and_its_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _author(tmp_path, monkeypatch, _tasks(10))

    def more(worktree: Path) -> None:
        for n in range(10, 24):
            _write_task(worktree / f"control.t{n:02d}", n)

    _, _, out = _author(
        tmp_path, monkeypatch, more, session_id="s-2", work=tmp_path / "scratch" / "work2"
    )
    version = _root(tmp_path) / out["version"]
    provenance = json.loads((version / "provenance.json").read_text())
    sessions = provenance["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-1", "s-2"]
    stream = hashlib.sha256(b"the stream\n").hexdigest()
    assert all(s["files"]["stdout.jsonl"] == stream for s in sessions)
    assert all(s["tokens"] == 1234 for s in sessions)
    manifest = _api("physgate.evaluation.tiers.manifest.read_version")(version)
    assert (
        manifest.provenance_sha256
        == hashlib.sha256((version / "provenance.json").read_bytes()).hexdigest()
    )


def test_after_a_version_is_cut_a_further_round_starts_looking_for_its_canaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    version = _root(tmp_path) / out["version"]
    listed = sorted(
        c
        for tier in ("validation", "held_out")
        for c in json.loads((version / tier / "canaries.json").read_text())
    )
    # The version's visible tier names no canaries, and is no list-less tier.
    assert sorted(root_canaries(_root(tmp_path))) == listed
    _, fake, again = _author(
        tmp_path,
        monkeypatch,
        _tasks(3),
        session_id="s-2",
        work=tmp_path / "scratch" / "work2",
    )
    assert again["status"] == "pooled" and len(fake.calls) == 1


@pytest.mark.parametrize(
    "place",
    [
        "visible",
        "notes/visible",
        f"elsewhere/{'a' * 64}/visible",
        f"control/{'a' * 64}/visible",
        ".version-0123abcd/visible",
    ],
    ids=[
        "at the root",
        "in a folder",
        "a version's name, not in a version's place",
        "a version's place, one level down",
        "unfinished",
    ],
)
def test_a_list_less_tier_called_visible_anywhere_but_a_version_refuses(
    tmp_path: Path, place: str
) -> None:
    root = _root(tmp_path)
    _write_task(root / place / "control.t00", 0)
    with pytest.raises(AuthoringError) as refused:
        root_canaries(root)
    assert refused.value.context.get("refused_because") == "canary_list_missing"


def _blind_check(tmp_path: Path, version: str) -> dict[str, Any]:
    """The blind check on ``version`` of the store, as the command runs it."""
    setup = dataclasses.replace(
        _setup(tmp_path / "private"), held_out_canaries=root_canaries(_root(tmp_path))
    )
    check: Any = author_session.blind_check
    try:
        out: dict[str, Any] = check(
            _store(tmp_path),
            "control",
            version,
            setup,
            tmp_path / "scratch" / "check",
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    except TypeError as exc:
        pytest.fail(f"the blind check is not given a version of the store: {exc}")
    return out


def _all_yes(keys: list[str]) -> dict[str, Any]:
    return {k: dict.fromkeys(QUESTIONS, True) for k in keys}


def test_the_blind_check_runs_on_a_version_and_keeps_its_stream_in_the_role_s_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    checked = _blind_check(tmp_path, out["version"])
    assert checked["answered"] and checked["tasks"] == 8 and checked["all_yes"] == 8
    assert (_root(tmp_path) / "check" / "c-1" / "stdout.jsonl").is_file()
    assert not (tmp_path / "scratch" / "check").exists()


@pytest.mark.parametrize("left", ["firmware/pool", "control/.version-0123abcd"])
def test_the_blind_check_refuses_while_the_store_holds_a_split_s_leftovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, left: str
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    (_store(tmp_path) / left).mkdir(parents=True)
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError) as refused:
        _blind_check(tmp_path, out["version"])
    assert refused.value.context.get("refused_because") in {"pool_left", "temporary_version_left"}
    assert fake.calls == []


def test_the_blind_check_refuses_a_version_that_is_not_its_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    tier = _root(tmp_path) / out["version"] / "held_out"
    task = sorted(p for p in tier.iterdir() if p.is_dir())[0]
    (task / "references" / "good" / "answer.json").write_text("{}")
    (tier / "SHA256SUMS").write_text(sha256sums(tier))
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    error = _api("physgate.evaluation.tiers.manifest.TierSetError")
    with pytest.raises(error) as refused:
        _blind_check(tmp_path, out["version"])
    assert refused.value.context.get("refused_because") == "tier_changed"
    assert fake.calls == []
