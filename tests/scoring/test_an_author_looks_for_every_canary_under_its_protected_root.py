"""An author's session looks for every canary its protected root names, or it does not run.

The tiers already cut under the protected root leave their canary lists there, beside a tier
or inside one. The authoring command passes every canary they name, at any depth, to the
session's watch, and the runner refuses a session that would not look for one of them. A list
that cannot be read, does not parse, names no canary, or is a link or not a regular file with
one name refuses the session, and so does a directory that cannot be listed: neither is ever
read as naming none. Only a root that holds no list at all lets a session whose record cannot
say what it saw (it had no canary to look for) be pooled.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import _plan, _setup, _tasks
from test_what_an_author_s_watch_could_not_hold_is_never_pooled import _Ending, _listed

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import author, pool_dir, root_canaries
from physgate.evaluation.per_role.authoring import AuthoringError

CANARY = "5f0c3a9e1b7d4c2a8e6f0b1d3c5a7e9f"
OTHER = "0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a"
#: Another role's canary list, where a split leaves it: beside that role's tier.
LIST_NAME = "actuator.canaries.json"
#: Lists further down: inside a tier, and beside a tier a level below the root.
NESTED = ["actuator/canaries.json", "older/round-1/actuator.canaries.json"]


def _root(tmp_path: Path) -> Path:
    root = _plan(tmp_path).held_out_root
    root.mkdir(parents=True)
    return root


def _author(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    canaries: tuple[str, ...] = (),
    seen: bool | None = False,
) -> tuple[_Ending, dict[str, Any] | None, dict[str, str] | None]:
    """Run the author on a scripted session; the session, the result, or the refusal's context."""
    session = _Ending(_tasks(2), "ended", seen)
    session.calls.clear()
    monkeypatch.setattr(author_session, "run_session", session)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    setup = dataclasses.replace(_setup(tmp_path / "private"), held_out_canaries=canaries)
    try:
        return session, author(_plan(tmp_path), setup), None
    except AuthoringError as exc:
        return session, None, exc.context


def _listed_at(root: Path, name: str, *canaries: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(list(canaries)))


def _reason(root: Path) -> str:
    """Why the root's lists were refused, or what else became of them."""
    try:
        return f"taken: {root_canaries(root)}"
    except AuthoringError as exc:
        return exc.context.get("refused_because", "no reason")
    except (OSError, RecursionError) as exc:
        return repr(exc)


def _bad_list(root: Path, outside: Path, case: str) -> None:
    target = root / LIST_NAME
    if case == "a link":
        (outside / "elsewhere.json").write_text(json.dumps([CANARY]))
        target.symlink_to(outside / "elsewhere.json")
    elif case == "a link to a directory":
        target.symlink_to(outside)
    elif case == "a directory":
        target.mkdir()
    elif case == "a pipe":
        os.mkfifo(target)
    elif case == "too large":
        target.write_text(json.dumps([CANARY] * 30_000))
    elif case == "a second name":
        target.write_text(json.dumps([CANARY]))
        os.link(target, outside / "second.json")
    elif case == "unreadable":
        target.write_text(json.dumps([CANARY]))
        target.chmod(0)
    else:
        target.write_text(case)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("a link", "canary_list_unreadable"),
        ("a link to a directory", "canary_list_unreadable"),
        ("a directory", "canary_list_unreadable"),
        ("a pipe", "canary_list_unreadable"),
        ("too large", "canary_list_unreadable"),
        ("a second name", "canary_list_unreadable"),
        ("unreadable", "canary_list_unreadable"),
        ("not json", "canary_list_unparsed"),
        ('{"canaries": []}', "canary_list_unparsed"),
        ("[1]", "canary_list_unparsed"),
        ('[""]', "canary_list_unparsed"),
        ("[]", "canary_list_empty"),
    ],
)
def test_a_canary_list_that_cannot_be_taken_whole_refuses_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, reason: str
) -> None:
    if case == "unreadable" and os.geteuid() == 0:
        pytest.skip("the superuser reads a file whatever its mode")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = _root(tmp_path)
    _bad_list(root, outside, case)
    try:
        session, result, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,))
    finally:
        if case == "unreadable":
            (root / LIST_NAME).chmod(0o600)
    assert refused is not None and refused.get("refused_because") == reason, (
        f"a canary list that is {case} was not refused as {reason}: {refused or result}"
    )
    assert session.calls == [], "the session ran"


def test_a_list_that_goes_on_past_the_parser_s_depth_is_refused_as_unparsed(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    (root / LIST_NAME).write_text("[" * 200_000)
    assert _reason(root) == "canary_list_unparsed"


def test_a_read_of_a_list_that_fails_refuses_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    _listed_at(root, LIST_NAME, CANARY)

    def failing(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise OSError("the disk gave up")

    monkeypatch.setattr(author_session.os, "fdopen", failing)
    assert _reason(root) == "canary_list_unreadable"


@pytest.mark.parametrize("name", NESTED)
def test_a_list_anywhere_under_the_root_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _listed_at(_root(tmp_path), name, CANARY)
    session, result, refused = _author(tmp_path, monkeypatch, canaries=())
    assert refused is not None and refused.get("refused_because") == "canaries_missing", (
        f"a list at {name} under the root was not seen: {refused or result}"
    )
    assert session.calls == [], "the session ran without looking for the root's canaries"


@pytest.mark.parametrize("name", NESTED)
def test_a_list_anywhere_under_the_root_that_cannot_be_taken_whole_refuses_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    root = _root(tmp_path)
    (root / name).parent.mkdir(parents=True)
    (root / name).write_text("not json")
    session, result, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,))
    assert refused is not None and refused.get("refused_because") == "canary_list_unparsed", (
        f"a list that does not parse at {name} was not refused: {refused or result}"
    )
    assert session.calls == [], "the session ran"


def test_a_directory_under_the_root_that_cannot_be_listed_refuses_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("the superuser lists a directory whatever its mode")
    closed = _root(tmp_path) / "actuator"
    closed.mkdir()
    closed.chmod(0)
    try:
        session, result, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,))
    finally:
        closed.chmod(0o700)
    assert refused is not None and refused.get("refused_because") == "canary_list_unreadable", (
        f"a directory a list may lie in, which cannot be listed, was passed: {refused or result}"
    )
    assert session.calls == [], "the session ran"


def test_a_session_that_would_not_look_for_a_canary_under_its_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (_root(tmp_path) / LIST_NAME).write_text(json.dumps([CANARY]))
    session, _, refused = _author(tmp_path, monkeypatch, canaries=())
    assert refused is not None and refused.get("refused_because") == "canaries_missing"
    assert session.calls == [], "the session ran without looking for the root's canaries"
    # Given every canary, the same session runs and its tasks are pooled.
    session, result, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,))
    assert refused is None and result is not None and result["pooled"] == 2


def test_a_session_that_would_look_for_only_some_of_the_root_s_canaries_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _listed_at(_root(tmp_path), LIST_NAME, CANARY, OTHER)
    session, _, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,))
    assert refused is not None and refused.get("refused_because") == "canaries_missing"
    assert refused.get("missing") == "1"
    assert session.calls == [], "the session ran without looking for one of the root's canaries"


@pytest.mark.parametrize("name", [LIST_NAME, *NESTED])
def test_a_record_that_cannot_say_what_it_saw_is_refused_where_the_root_names_canaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _listed_at(_root(tmp_path), name, CANARY)
    _, _, refused = _author(tmp_path, monkeypatch, canaries=(CANARY,), seen=None)
    assert refused is not None and refused.get("refused_because") == "held_out_seen"
    assert _listed(pool_dir(_plan(tmp_path).held_out_root, "control")) == []


def test_a_record_that_cannot_say_is_pooled_only_where_the_root_names_no_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path)
    _, result, refused = _author(tmp_path, monkeypatch, seen=None)
    assert refused is None, f"a root with no canary to look for refused the session: {refused}"
    assert result is not None and result["pooled"] == 2


def test_the_author_command_passes_every_canary_under_the_root_to_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.per_role import cli

    root = _root(tmp_path)
    nested = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    _listed_at(root, LIST_NAME, CANARY)
    _listed_at(root, "control-two.canaries.json", OTHER)
    _listed_at(root, "thermal/canaries.json", nested)
    given: list[Any] = []

    def installed(_args: argparse.Namespace, run: Any) -> int:  # noqa: ANN401
        run(_setup(tmp_path / "private"))
        return 0

    def recording(_plan: Any, setup: Any) -> dict[str, Any]:  # noqa: ANN401
        given.append(setup)
        return {}

    monkeypatch.setattr(cli, "_with_install", installed)
    monkeypatch.setattr(author_session, "author", recording)
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    places = ["--held-out-root", str(root), "--work", str(tmp_path / "w")]
    places += ["--visible", str(tmp_path / "v"), "--role-python", "/p"]
    args = parser.parse_args(
        ["per-role", "author", "--role", "control", "--cap", "1", "--seed", "1", *places]
    )
    args.func(args)
    assert len(given) == 1
    assert sorted(given[0].held_out_canaries) == sorted([CANARY, OTHER, nested]), (
        "the author command did not pass the root's canaries to the session"
    )
