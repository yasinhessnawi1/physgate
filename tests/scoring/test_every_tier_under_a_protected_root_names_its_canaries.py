"""Every tier under a protected root names its canaries, and every session there looks for them.

A session's record says it saw no held-out task only by looking for every canary of every
tier it could reach. The runner learns them from the lists the harness writes, so a tier that
holds tasks but no list (the split stopped between the tier and its list, or the list was
removed by hand) would leave the gate looking for nothing while the record reads clean. Such
a tier refuses the session, before it starts and again once it is over, and so does a list
that went while it ran; a directory that holds no task is no tier and refuses nothing.

The split leaves each protected tier's list inside the tier, where the walk reads it and every
layer of the protection refuses it to a session. The folders the walk leaves out (the pool and
the sessions' streams) hold no canary of ours: canaries are given at the split.

The blind check is held to the same: its setup carries every canary under the root, and a
check whose stream showed one, or cannot say it did not, or under whose root the canaries
grew while it ran, gives no answer. Its stream is still kept inside the protected root.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _held_tier,
    _plan,
    _setup,
    _tasks,
    _write_task,
)
from test_what_an_author_s_watch_could_not_hold_is_never_pooled import ABSENT, _Ending, _listed

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import (
    QUESTIONS,
    author,
    blind_check,
    root_canaries,
)
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.store import SESSION_FOLDERS, pool_dir
from physgate.evaluation.tiers.task import load_task

CANARY = "5f0c3a9e1b7d4c2a8e6f0b1d3c5a7e9f"
OTHER = "0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a"


def _root(tmp_path: Path) -> Path:
    root = _plan(tmp_path).root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _harness_lists(root: Path) -> list[Path]:
    """The canary lists under ``root``, outside the folders sessions fill."""
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and (p.name == "canaries.json" or p.name.endswith(".canaries.json"))
        and p.relative_to(root).parts[0] not in SESSION_FOLDERS
    )


def _reason(root: Path) -> str:
    try:
        return f"taken: {root_canaries(root)}"
    except AuthoringError as exc:
        return exc.context.get("refused_because", "no reason")


def _author(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canaries: tuple[str, ...] = (),
    seen: bool | None = False,
    write: Any = None,  # noqa: ANN401
) -> tuple[_Ending, dict[str, Any] | None, dict[str, str] | None]:
    session = _Ending(write or _tasks(2), "ended", seen)
    session.calls.clear()
    monkeypatch.setattr(author_session, "run_session", session)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    setup = dataclasses.replace(_setup(tmp_path / "private"), held_out_canaries=canaries)
    try:
        return session, author(_plan(tmp_path), setup), None
    except AuthoringError as exc:
        return session, None, exc.context


def _tier_without_list(root: Path, name: str = "actuator") -> Path:
    tier = root / name
    _write_task(tier / f"{name}.t00", 0)
    (tier / "SHA256SUMS").write_text("")
    return tier


# ------------------------------------------------- a tier with no list is never "none"


@pytest.mark.parametrize("seen", [False, None])
def test_a_tier_holding_tasks_without_its_list_refuses_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seen: bool | None
) -> None:
    _tier_without_list(_root(tmp_path))
    session, result, refused = _author(tmp_path, monkeypatch, seen=seen)
    assert refused is not None and refused.get("refused_because") == "canary_list_missing", (
        f"a tier with no canary list was read as naming none: {refused or result}"
    )
    assert session.calls == [], "the session ran"


@pytest.mark.parametrize("depth", ["actuator", "older/round-1/actuator"])
def test_a_tier_without_its_list_is_found_at_any_depth(tmp_path: Path, depth: str) -> None:
    root = _root(tmp_path)
    _tier_without_list(root, depth)
    assert _reason(root) == "canary_list_missing"


def test_a_list_beside_a_tier_is_not_that_tier_s_list(tmp_path: Path) -> None:
    # A list beside a tier lies outside the root a run protects; it does not stand for one.
    root = _root(tmp_path)
    _tier_without_list(root)
    (root / "actuator.canaries.json").write_text(json.dumps([CANARY]))
    assert _reason(root) == "canary_list_missing"


def test_a_list_inside_one_of_a_tier_s_tasks_is_not_the_tier_s_list(tmp_path: Path) -> None:
    # The tier's list lies directly in the tier; one further down names one task's canary.
    root = _root(tmp_path)
    tier = _tier_without_list(root)
    (tier / "actuator.t00" / "canaries.json").write_text(json.dumps([CANARY]))
    assert _reason(root) == "canary_list_missing"


def test_a_task_file_named_in_another_case_still_makes_a_tier(tmp_path: Path) -> None:
    # A disk that ignores case opens it as the task it is.
    root = _root(tmp_path)
    tier = _tier_without_list(root)
    task = tier / "actuator.t00" / "task.json"
    task.rename(task.with_name("Task.JSON"))
    assert _reason(root) == "canary_list_missing"


def test_a_tier_whose_list_was_removed_after_the_split_refuses_the_next_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = _held_tier(tmp_path, monkeypatch)
    lists = _harness_lists(plan.root)
    assert lists, "the split left no canary list"
    for listed in lists:
        listed.unlink()
    assert _reason(plan.root) == "canary_list_missing", (
        "a cut tier with its list removed was read as naming no canary"
    )


def test_a_list_that_goes_while_the_session_runs_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    tier = _tier_without_list(root)
    (tier / "canaries.json").write_text(json.dumps([CANARY]))

    def write(worktree: Path) -> None:
        _tasks(2)(worktree)
        (tier / "canaries.json").unlink()

    _, result, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,), write=write)
    assert refused is not None and refused.get("refused_because") == "canary_list_missing", (
        f"a list that went while the session ran was not missed: {refused or result}"
    )
    assert _listed(pool_dir(root.parent, "control")) == []


@pytest.mark.parametrize(
    "layout",
    [
        {"actuator": None},
        {"firmware/item.json": "{}"},
        {"actuator/SHA256SUMS": ""},
        {"actuator/notes/readme.txt": "x"},
    ],
    ids=["an empty directory", "a directory of files", "a digest alone", "files further down"],
)
def test_a_directory_that_holds_no_task_is_no_tier_and_refuses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: dict[str, str | None]
) -> None:
    root = _root(tmp_path)
    for name, text in layout.items():
        if text is None:
            (root / name).mkdir(parents=True)
        else:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
    _, result, refused = _author(tmp_path, monkeypatch, seen=None)
    assert refused is None, f"a directory holding no task refused the session: {refused}"
    assert result is not None and result["pooled"] == 2


# ------------------------------------- the split's list, where the walk reads it


def test_the_split_leaves_each_list_inside_its_tier_where_the_walk_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    root = plan.root
    tiers = [root / version / "held_out", root / version / "validation"]
    carried = sorted(
        str(load_task(p).task.canary) for tier in tiers for p in tier.iterdir() if p.is_dir()
    )
    assert _harness_lists(root) == sorted(tier / "canaries.json" for tier in tiers), (
        f"the split's lists are not one inside each tier: {_harness_lists(root)}"
    )
    assert sorted(root_canaries(root)) == carried
    # The pool is gone with the split, and no canary was ever given to a task in it.
    assert not pool_dir(plan.store, "control").exists()


# ---------------------------------------------- the blind check looks for them too


def _check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canaries: tuple[str, ...] | None = None,
    seen: bool | str | None = False,
    after: Any = None,  # noqa: ANN401
) -> tuple[FakeSession, dict[str, Any] | None, dict[str, str] | None]:
    """The blind check on a cut tier; the session, the result, or the refusal's context."""
    plan, version = _held_tier(tmp_path, monkeypatch)
    root = plan.root

    def answer(worktree: Path) -> None:
        keys = list(json.loads((worktree / "tasks.json").read_text()))
        (worktree / "answers.json").write_text(
            json.dumps({k: dict.fromkeys(QUESTIONS, True) for k in keys})
        )
        if after is not None:
            after(root)

    session = _Ending(answer, "ended", seen)
    monkeypatch.setattr(author_session, "run_session", session)
    given = root_canaries(root) if canaries is None else canaries
    setup = dataclasses.replace(_setup(tmp_path / "private"), held_out_canaries=given)
    try:
        out = blind_check(
            plan.store,
            plan.role,
            version,
            setup,
            tmp_path / "scratch" / "check",
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    except AuthoringError as exc:
        return session, None, exc.context
    return session, out, None


def test_a_blind_check_that_would_not_look_for_the_root_s_canaries_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, out, refused = _check(tmp_path, monkeypatch, canaries=())
    assert refused is not None and refused.get("refused_because") == "canaries_missing", (
        f"a check that looked for none of the root's canaries ran: {refused or out}"
    )
    assert session.calls == [], "the check's session ran"


@pytest.mark.parametrize("seen", [True, None, ABSENT], ids=["seen", "cannot say", "unrecorded"])
def test_a_blind_check_whose_stream_showed_a_canary_gives_no_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seen: bool | str | None
) -> None:
    _, out, refused = _check(tmp_path, monkeypatch, seen=seen)
    assert refused is not None and refused.get("refused_because") == "held_out_seen", (
        f"a check whose record says {seen!r} gave an answer: {refused or out}"
    )
    assert not (tmp_path / "scratch" / "check").exists()
    held = _plan(tmp_path).root
    assert list((held / "check").glob("*/stdout.jsonl")), "the check's stream was lost"


def test_a_blind_check_under_whose_root_the_canaries_grew_gives_no_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def another_split(root: Path) -> None:
        _tier_without_list(root, "actuator")
        (root / "actuator" / "canaries.json").write_text(json.dumps([OTHER]))

    _, out, refused = _check(tmp_path, monkeypatch, after=another_split)
    assert refused is not None and refused.get("refused_because") == "canaries_missing", (
        f"a check that was not looking for a canary that came gave an answer: {refused or out}"
    )


def test_a_blind_check_looking_for_every_canary_with_a_clean_record_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control: the refusals above are of what the record says, not of every check.
    session, out, refused = _check(tmp_path, monkeypatch)
    assert refused is None and out is not None and out["answered"] and out["all_yes"] == 8
    assert len(session.calls) == 1


def test_the_blind_check_command_passes_every_canary_under_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.per_role import cli

    root = _root(tmp_path)
    tier = _tier_without_list(root, "control")
    (tier / "canaries.json").write_text(json.dumps([CANARY]))
    other = _tier_without_list(root, "thermal")
    (other / "canaries.json").write_text(json.dumps([OTHER]))
    given: list[Any] = []

    def installed(_args: argparse.Namespace, run: Any) -> int:  # noqa: ANN401
        run(_setup(tmp_path / "private"))
        return 0

    def recording(*args: Any, **_kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        given.append(args[3])
        return {}

    monkeypatch.setattr(cli, "_with_install", installed)
    monkeypatch.setattr(author_session, "blind_check", recording)
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    args = parser.parse_args(
        ["per-role", "blind-check", "--role", "control", "--cap", "1"]
        + ["--store", str(root.parent), "--version", "v", "--work", str(tmp_path / "w")]
    )
    args.func(args)
    assert len(given) == 1
    assert sorted(given[0].held_out_canaries) == sorted([CANARY, OTHER]), (
        "the blind-check command did not pass the root's canaries to the session"
    )
