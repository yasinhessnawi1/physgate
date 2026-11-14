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
    check_setup,
    check_work,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import QUESTIONS
from physgate.evaluation.tiers.authoring import AuthoringError, sha256sums
from physgate.evaluation.tiers.canaries import root_canaries


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
    assert sorted(p.name for p in _root(tmp_path).iterdir()) == sorted(
        ["withheld", "work", out["version"]]
    )
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
        ("firmware/withheld/pool", "pool_left"),
        ("control/withheld/pool.spent", "pool_left"),
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
    assert not (_root(tmp_path) / "withheld" / "pool").exists()
    assert not (_root(tmp_path) / "withheld" / "pool.spent").exists()


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
    pool = _store(tmp_path) / "control" / "withheld" / "pool"
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
    # What the session record does not carry is said to be missing, never left out.
    gap = "not recorded by the session record"
    assert all(s.get("turns") == gap and s.get("secret_scan") == gap for s in sessions)
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


def _blind_check(
    tmp_path: Path, version: str, held_out: tuple[Path, ...] | None = None
) -> dict[str, Any]:
    """The blind check on ``version`` of the store, as the command runs it.

    Its session withholds what the command's does unless ``held_out`` names what it withholds.
    """
    setup = dataclasses.replace(
        check_setup(_store(tmp_path), _setup(tmp_path / "private")),
        held_out_canaries=root_canaries(_root(tmp_path)),
    )
    if held_out is not None:
        setup = dataclasses.replace(setup, held_out=tuple(str(p) for p in held_out))
    check: Any = author_session.blind_check
    try:
        out: dict[str, Any] = check(
            _store(tmp_path),
            "control",
            version,
            setup,
            check_work(_store(tmp_path)),
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
    assert (_root(tmp_path) / "withheld" / "check" / "c-1" / "stdout.jsonl").is_file()
    assert not check_work(_store(tmp_path)).exists()


@pytest.mark.parametrize(
    "left", ["firmware/withheld/pool", "control/.version-0123abcd", "control/withheld/pool"]
)
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
    raised: BaseException | None = None
    try:
        _blind_check(tmp_path, out["version"])
    except Exception as exc:  # noqa: BLE001 - anything but the named refusal fails the row
        raised = exc
    # Read before the session starts: refused as the version it is, and no session ran.
    assert isinstance(raised, error), (
        f"not refused as a version that is not its manifest: {raised!r}"
    )
    assert raised.context.get("refused_because") == "tier_changed"
    assert fake.calls == []


@pytest.mark.parametrize(
    ("withholds", "reason"),
    [
        ("the tier alone", "withheld_root_not_named"),
        ("both tiers", "withheld_root_not_named"),
        ("the tier and the withheld root", "protected_tier_not_named"),
    ],
)
def test_the_blind_check_s_session_withholds_what_a_run_on_the_role_s_root_withholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, withholds: str, reason: str
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    version = _root(tmp_path).resolve() / out["version"]
    withheld = _root(tmp_path).resolve() / "withheld"
    held = {
        "the tier alone": (version / "held_out",),
        "both tiers": (version / "held_out", version / "validation"),
        "the tier and the withheld root": (version / "held_out", withheld),
    }[withholds]
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError) as refused:
        _blind_check(tmp_path, out["version"], held_out=held)
    assert refused.value.context.get("refused_because") == reason
    assert fake.calls == []


def test_the_blind_check_runs_when_its_session_withholds_the_role_s_root_but_its_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    # The version whole and the withheld root: all of the role's root but the work root.
    version = _root(tmp_path).resolve() / out["version"]
    held = (version, _root(tmp_path).resolve() / "withheld")
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    checked = _blind_check(tmp_path, out["version"], held_out=held)
    assert checked["answered"] and len(fake.calls) == 1


def test_a_blind_check_working_outside_the_role_s_work_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    setup = dataclasses.replace(
        check_setup(_store(tmp_path), _setup(tmp_path / "private")),
        held_out_canaries=root_canaries(_root(tmp_path)),
    )
    with pytest.raises(AuthoringError) as refused:
        author_session.blind_check(
            _store(tmp_path),
            "control",
            out["version"],
            setup,
            tmp_path / "scratch" / "check",
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    assert refused.value.context.get("refused_because") == "work_outside_the_work_root"
    assert fake.calls == []


def test_the_blind_check_command_works_in_the_work_root_and_withholds_all_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from physgate.evaluation.per_role import cli

    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    store = _store(tmp_path).resolve()
    given: list[Any] = []

    def installed(args: argparse.Namespace, run: Any) -> int:  # noqa: ANN401
        held = getattr(cli, "session_held_out", None)
        assert held is not None, "the command's withheld roots are not built"
        run(dataclasses.replace(_setup(tmp_path / "private"), held_out=held(args)))
        return 0

    def recording(*args: Any, **_kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        given.append(args)
        return {}

    (store / "firmware" / "withheld").mkdir(parents=True)
    monkeypatch.setattr(cli, "_with_install", installed)
    monkeypatch.setattr(author_session, "blind_check", recording)
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    args = parser.parse_args(
        ["per-role", "blind-check", "--role", "control", "--cap", "1", "--version"]
        + [out["version"], "--store", str(store), "--work", str(tmp_path / "w")]
    )
    args.func(args)
    (call,) = given
    work, held = Path(call[4]), call[3].held_out
    work_root = store / "control" / "work"
    assert work.parent == work_root, f"the check works at {work}, not in the work root"
    version = store / "control" / out["version"]
    # All of the store but the check's own work: the version whole, its manifest and visible
    # tier included, the withheld root, and every other role's root.
    expected = (store / "control" / "withheld", version, store / "firmware")
    assert sorted(held) == sorted(str(p) for p in expected)


def test_a_blind_check_whose_session_does_not_withhold_all_of_the_role_s_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    root = _root(tmp_path).resolve()
    version = root / out["version"]
    (root / "work" / "check-other" / "worktree").mkdir(parents=True)
    # What a run withholds, without the version's manifest and visible tier or another
    # check's work.
    held = (version / "held_out", version / "validation", root / "withheld")
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    with pytest.raises(AuthoringError) as refused:
        _blind_check(tmp_path, out["version"], held_out=held)
    assert refused.value.context.get("refused_because") == "role_root_entry_not_withheld"
    assert fake.calls == []


def test_a_manifest_changed_while_the_check_ran_refuses_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    manifest = _root(tmp_path) / out["version"] / "tierset.json"

    def answer_and_tamper(worktree: Path) -> None:
        _answers(_all_yes)(worktree)
        manifest.write_bytes(manifest.read_bytes().replace(b"control", b"Control", 1))

    fake = FakeSession(answer_and_tamper, session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    try:
        checked = _blind_check(tmp_path, out["version"])
    except AuthoringError as exc:
        checked = exc.context
    assert checked.get("refused_because") == "version_changed", (
        f"the check's answer was taken after its version changed: {checked}"
    )
    assert (_root(tmp_path) / "withheld" / "check" / "c-1" / "stdout.jsonl").is_file()


def test_a_version_written_on_a_bare_role_s_root_makes_its_withheld_and_work_roots(
    tmp_path: Path,
) -> None:
    from physgate.evaluation.tiers.store import write_version
    from physgate.evaluation.tiers.task import canonical_json

    prepared = tmp_path / "prepared"
    prepared.mkdir()
    _tasks(24)(prepared)
    root = _root(tmp_path)
    root.mkdir(parents=True)
    write_version(
        root,
        sorted(p for p in prepared.iterdir() if p.is_dir()),
        role="control",
        seed=3,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": []}),
    )
    for name in ("withheld", "work"):
        assert (root / name).is_dir(), f"the role's {name} root is not there once a version is"


def _checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: Any) -> dict[str, Any]:
    """A version cut, then a blind check whose session runs ``write``; its result or refusal."""
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    monkeypatch.setattr(author_session, "run_session", FakeSession(write, session_id="c-1"))
    try:
        return _blind_check(tmp_path, out["version"])
    except AuthoringError as exc:
        return {**exc.context, "raised": True}


def _version(tmp_path: Path) -> Path:
    (found,) = [p for p in _root(tmp_path).iterdir() if len(p.name) == 64]
    return found


def test_the_check_s_session_writes_nowhere_in_the_store_but_its_own_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    fake = FakeSession(_answers(_all_yes), session_id="c-1")
    monkeypatch.setattr(author_session, "run_session", fake)
    checked = _blind_check(tmp_path, out["version"])
    assert checked["answered"]
    (setup,) = fake.setups
    store = _store(tmp_path).resolve()
    assert getattr(setup, "write_protected", ()) == (str(store),), "the store is not protected"
    assert getattr(setup, "writable_within", ()) == (str(check_work(store).resolve()),)


@pytest.mark.parametrize(
    "how", ["removed", "renamed in another case", "a version's name appears in another case"]
)
def test_a_version_removed_or_renamed_while_the_check_ran_refuses_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    import shutil

    def answer_and_move(worktree: Path) -> None:
        _answers(_all_yes)(worktree)
        version = _version(tmp_path)
        if how == "removed":
            shutil.rmtree(version)
        elif how == "renamed in another case":
            version.rename(version.with_name(version.name.upper()))
        else:
            (version.parent / ("F" * 64)).mkdir()

    checked = _checked(tmp_path, monkeypatch, answer_and_move)
    assert checked.get("raised"), f"the check's answer was taken after a version was {how}"
    # Renamed, its visible tier is no longer a version's, so the canary walk refuses first.
    expected = "canary_list_missing" if how == "renamed in another case" else "version_changed"
    assert checked.get("refused_because") == expected, checked
    assert (_root(tmp_path) / "check.working").is_file(), "the record went, though a version moved"


def test_a_task_copy_dropped_in_the_role_s_root_refuses_the_answer_and_stays_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.tiers.store import leftovers

    def answer_and_drop(worktree: Path) -> None:
        _answers(_all_yes)(worktree)
        (_root(tmp_path) / "copy.json").write_bytes((worktree / "tasks.json").read_bytes())

    checked = _checked(tmp_path, monkeypatch, answer_and_drop)
    assert checked.get("refused_because") == "role_root_changed", (
        f"the check's answer was taken after a task copy was dropped in the role's root: {checked}"
    )
    # Its record stays for a person, so nothing starts on the store until one has looked.
    record = _root(tmp_path) / "check.working"
    assert record.is_file() and "copy.json" in record.read_text()
    assert json.loads(record.read_text()).get("session") == "ended", record.read_text()
    assert checked.get("session_ended") == "ended", checked
    assert leftovers(_store(tmp_path))["work_left"] >= 1
    assert not check_work(_store(tmp_path)).exists(), "the check's work stayed out"


class _Stopped(Exception):  # noqa: N818 - stands for the session's own failure
    pass


@pytest.mark.parametrize(
    "ending",
    ["an exception", "a stop", "a timeout", "its stream showed a canary"],
)
def test_the_role_s_root_is_looked_at_again_however_the_check_s_session_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    import subprocess

    def tamper_and_end(worktree: Path) -> None:
        _answers(_all_yes)(worktree)
        manifest = _version(tmp_path) / "tierset.json"
        manifest.write_bytes(manifest.read_bytes().replace(b"control", b"Control", 1))
        if ending == "an exception":
            raise _Stopped("the session failed")
        if ending == "a stop":
            raise KeyboardInterrupt
        if ending == "a timeout":
            raise subprocess.TimeoutExpired("claude", 1.0)

    _, _, out = _author(tmp_path, monkeypatch, _tasks(24))
    fake = FakeSession(tamper_and_end, session_id="c-1")
    if ending == "its stream showed a canary":
        real = fake.__call__

        def seen(*args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
            return {**real(*args, **kwargs), "held_out_seen": True}

        monkeypatch.setattr(author_session, "run_session", seen)
    else:
        monkeypatch.setattr(author_session, "run_session", fake)
    raised: BaseException | None = None
    try:
        _blind_check(tmp_path, out["version"])
    except BaseException as exc:  # noqa: BLE001 - a stop is the case under test
        raised = exc
    assert isinstance(raised, AuthoringError), (
        f"{ending}: the check ended without looking at the role's root again: {raised!r}"
    )
    # A refusal the check already raised keeps its own reason; any other end is the change's.
    expected = "held_out_seen" if ending == "its stream showed a canary" else "version_changed"
    assert raised.context.get("refused_because") == expected
    record = _root(tmp_path) / "check.working"
    assert record.is_file(), "the record went, though the root changed"
    # The refusal replaces a stop, so the record says which the session's end was.
    ended = {
        "an exception": "failed",
        "a stop": "stopped",
        "a timeout": "failed",
        "its stream showed a canary": "refused",
    }[ending]
    assert json.loads(record.read_text()).get("session") == ended, record.read_text()
    if ending != "its stream showed a canary":
        assert raised.context.get("session_ended") == ended, raised.context


def test_an_author_whose_session_does_not_withhold_every_role_s_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _store(tmp_path) / "firmware" / "withheld" / "check" / "c-1"
    other.mkdir(parents=True)
    (other / "stdout.jsonl").write_text("another role's held-out tasks")
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    setup = dataclasses.replace(_setup(tmp_path / "private"), held_out=(str(_root(tmp_path)),))
    (tmp_path / "scratch").mkdir()
    with pytest.raises(AuthoringError) as refused:
        author_session.author(_plan(tmp_path), setup)
    assert refused.value.context.get("refused_because") == "store_not_withheld"
    assert fake.calls == []


def test_an_author_refuses_a_store_where_another_role_s_root_would_trip_its_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    other = _store(tmp_path) / "firmware" / "withheld"
    other.mkdir(parents=True)
    os.symlink("/etc/hosts", other / "a-link")
    fake = FakeSession(_tasks(24))
    monkeypatch.setattr(author_session, "run_session", fake)
    (tmp_path / "scratch").mkdir()
    with pytest.raises(AuthoringError) as refused:
        author_session.author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert refused.value.context.get("refused_because") == "root_would_trip_the_session"
    assert "a-link" in refused.value.context.get("problems", "")
    assert fake.calls == []


def test_the_author_command_withholds_the_whole_store_and_makes_the_role_s_root(
    tmp_path: Path,
) -> None:
    import argparse

    from physgate.evaluation.per_role import cli

    store = _store(tmp_path).resolve()
    store.mkdir(parents=True)
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    args = parser.parse_args(
        ["per-role", "author", "--role", "control", "--cap", "1", "--store", str(store)]
        + ["--work", str(tmp_path / "w"), "--seed", "1", "--role-python", "python3"]
    )
    held = cli.session_held_out(args)
    assert held == (str(store),), f"the author's session withholds {held}, not the whole store"
    for name in ("withheld", "work"):
        assert (store / "control" / name).is_dir(), f"the role's {name} root is not made first"


def test_an_author_s_first_session_makes_the_role_s_withheld_and_work_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, out = _author(tmp_path, monkeypatch, _tasks(12))
    assert out["status"] == "pooled"
    for name in ("withheld", "work"):
        assert (_root(tmp_path) / name).is_dir(), f"the role's {name} root is not made with it"
