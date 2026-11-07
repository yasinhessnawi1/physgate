"""An author's session looks for every canary its protected root names, or it does not run.

The tiers already cut under the protected root leave their canary lists beside them. The
authoring command passes every canary they name to the session's watch, and the runner
refuses a session that would not look for one of them. A list that cannot be read, does not
parse, names no canary, or is a link or not a regular file with one name refuses the
session: it is never read as naming none. Only a root that holds no list at all lets a
session whose record cannot say what it saw (it had no canary to look for) be pooled.
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
from physgate.evaluation.per_role.author_session import author, pool_dir
from physgate.evaluation.per_role.authoring import AuthoringError

CANARY = "5f0c3a9e1b7d4c2a8e6f0b1d3c5a7e9f"
#: Another role's canary list, where a split leaves it: beside that role's tier.
LIST_NAME = "actuator.canaries.json"


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


def _bad_list(root: Path, outside: Path, case: str) -> None:
    target = root / LIST_NAME
    if case == "a link":
        (outside / "elsewhere.json").write_text(json.dumps([CANARY]))
        target.symlink_to(outside / "elsewhere.json")
    elif case == "a directory":
        target.mkdir()
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
        ("a directory", "canary_list_unreadable"),
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


def test_a_record_that_cannot_say_what_it_saw_is_refused_where_the_root_names_canaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (_root(tmp_path) / LIST_NAME).write_text(json.dumps([CANARY]))
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
    other = "0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a"
    (root / LIST_NAME).write_text(json.dumps([CANARY]))
    (root / "control-two.canaries.json").write_text(json.dumps([other, CANARY]))
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
    assert sorted(given[0].held_out_canaries) == sorted([CANARY, other]), (
        "the author command did not pass the root's canaries to the session"
    )
