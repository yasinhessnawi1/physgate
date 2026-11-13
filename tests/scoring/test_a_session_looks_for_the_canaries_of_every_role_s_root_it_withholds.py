"""A session looks for the canaries of every role's root it withholds, not its own role's alone.

An author and a blind check withhold the whole store: their role's root and every other
role's. What a session is checked for must cover what it withholds: a canary listed under
another role's root that showed in the session's stream would otherwise be no exposure to its
record. So both are refused unless the session looks for every canary of every role's root in
the store, before it starts and again once it is over, and each command gives the session them
all. The other role here is ``firmware``; its list lies where an own root's would.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from test_an_author_looks_for_every_canary_under_its_protected_root import (
    CANARY,
    OTHER,
    _author,
    _root,
)
from test_every_tier_under_a_protected_root_names_its_canaries import _check
from test_the_task_author_s_session_is_staged_held_and_split_blind import _plan, _setup, _tasks

from physgate.evaluation.per_role import author_session

LIST_NAME = "thermal.canaries.json"


def _other_root(own: Path) -> Path:
    """The firmware role's root beside ``own``, the control role's."""
    return own.parent / "firmware"


def _listed_under_the_other_role(own: Path, *canaries: str) -> None:
    other = _other_root(own)
    other.mkdir(parents=True, exist_ok=True)
    (other / LIST_NAME).write_text(json.dumps(list(canaries)))


def test_an_author_not_looking_for_another_role_s_canary_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    _listed_under_the_other_role(root, OTHER)
    session, result, refused = _author(tmp_path, monkeypatch, canaries=())
    assert refused is not None and refused.get("refused_because") == "canaries_missing", result
    assert session.calls == [], "the session ran without looking for another role's canary"
    session, result, refused = _author(tmp_path, monkeypatch, canaries=(OTHER,))
    assert refused is None and result is not None and result["pooled"] == 2


def test_a_list_that_comes_under_another_role_s_root_while_an_author_runs_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)

    def write(worktree: Path) -> None:
        _tasks(2)(worktree)
        _listed_under_the_other_role(root, OTHER)

    session, result, refused = _author(tmp_path, monkeypatch, canaries=(), write=write)
    assert refused is not None and refused.get("refused_because") == "canaries_missing", result
    assert len(session.calls) == 1


def test_a_blind_check_not_looking_for_another_role_s_canary_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The list is there before the check; its own root's canaries are all it is given. The
    # own root is not made here: the check's fixture cuts its tier there.
    _listed_under_the_other_role(_plan(tmp_path).root, OTHER)
    session, out, refused = _check(tmp_path, monkeypatch)
    assert refused is not None and refused.get("refused_because") == "canaries_missing", out
    assert session.calls == [], "the check ran without looking for another role's canary"


def test_a_list_that_comes_under_another_role_s_root_while_a_blind_check_runs_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def after(own: Path) -> None:
        _listed_under_the_other_role(own, OTHER)

    _, out, refused = _check(tmp_path, monkeypatch, after=after)
    assert refused is not None and refused.get("refused_because") == "canaries_missing", out


def _given_by(command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The setups the command gave its session, the session itself replaced."""
    from physgate.evaluation.per_role import cli

    root = _root(tmp_path)
    (root / LIST_NAME).write_text(json.dumps([CANARY]))
    _listed_under_the_other_role(root, OTHER)
    given: list[Any] = []

    def installed(_args: argparse.Namespace, run: Any) -> int:  # noqa: ANN401
        run(_setup(tmp_path / "private"))
        return 0

    def recording(*args: Any, **_kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        given.append(args[1] if command == "author" else args[3])
        return {}

    monkeypatch.setattr(cli, "_with_install", installed)
    monkeypatch.setattr(
        author_session, "author" if command == "author" else "blind_check", recording
    )
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    places = ["--store", str(root.parent), "--work", str(tmp_path / "w")]
    if command == "author":
        places += ["--role-python", "/p"]
        words = ["per-role", "author", "--role", "control", "--cap", "1", "--seed", "1"]
    else:
        words = ["per-role", "blind-check", "--role", "control", "--version", "v", "--cap", "1"]
    args = parser.parse_args([*words, *places])
    args.func(args)
    return given


@pytest.mark.parametrize("command", ["author", "blind-check"])
def test_each_command_gives_its_session_every_role_s_canaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    given = _given_by(command, tmp_path, monkeypatch)
    assert len(given) == 1
    assert sorted(given[0].held_out_canaries) == sorted([CANARY, OTHER]), (
        f"the {command} command did not give the session another role's canary"
    )
