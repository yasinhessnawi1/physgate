"""What the harness reads of a session's place after the session, it reads as it reads the answer.

The session may leave anything at a name the harness reads afterwards: its generated
configuration (the tool list the comparison holds against the harness run's), its stream, its
answer. Each is opened once, no link followed at any component, without waiting on a named
pipe, as a regular file with no other link to it, under a size bound. What is not such a file
is refused, and the round never hangs on it.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)
from task_fixtures import own_task

from physgate.evaluation.baseline.runner import run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS
from physgate.orchestrator import dispatch
from physgate.orchestrator.exceptions import InvocationError

#: Long enough for any refusal on this machine; a read waiting on a pipe never ends by itself.
WITHIN_S = 20.0
FORGED = ["Forged"]


def _score(_task: Any, answer: Path) -> dict[str, Any]:  # noqa: ANN401
    assert answer.is_file()
    return dict(SCORED)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _release(fifo: Path) -> None:
    """Let a reader waiting on ``fifo`` go on: a writer opens it and closes it at once."""
    with contextlib.suppress(OSError):
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))


def _within(call: Callable[[], Any], fifo: Path | None) -> Any:  # noqa: ANN401
    """What ``call`` returned or raised; the row fails on its assertion past the bound."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = call()
        except Exception as exc:  # noqa: BLE001 - the row asserts on what it was
            box["value"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(WITHIN_S)
    hung = thread.is_alive()
    while thread.is_alive() and fifo is not None:
        _release(fifo)
        thread.join(1.0)
    assert not hung, "the harness waited on a named pipe the session left"
    return box["value"]


def _round(store: StandInStore, tmp_path: Path, arm: StandInArm) -> Any:  # noqa: ANN401
    task = store.tasks["visible"][0]
    return run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=run_set((harness_run(tmp_path / "runs", task, store), 0)),
        out=tmp_path / "round",
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
    )


def _forged(where: Path) -> Path:
    """A configuration of the installer's shape whose tool list is not the one installed."""
    where.mkdir(parents=True, exist_ok=True)
    body = {"profile": "baseline", "role": None, "tools_allowed": FORGED}
    (where / CONFIG_NAME).write_text(json.dumps(body))
    return where / CONFIG_NAME


def _left_at_config(kind: str, tmp_path: Path) -> Callable[[Path, Path], None]:
    def leave(place: Path, _harness: Path) -> None:
        directory = place / "session" / "session"
        config = directory / CONFIG_NAME
        if kind == "directory link":
            _forged(tmp_path / "elsewhere")
            for each in directory.iterdir():
                each.unlink()
            directory.rmdir()
            directory.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
            return
        config.unlink()
        if kind == "named pipe":
            os.mkfifo(config)
        elif kind == "link":
            config.symlink_to(_forged(tmp_path / "elsewhere"))
        elif kind == "hard link":
            os.link(_forged(tmp_path / "elsewhere"), config)
        elif kind == "directory":
            config.mkdir()
        else:
            body = {"profile": "baseline", "role": None}
            body["tools_allowed"] = list(PROFILE_TOOLS["baseline"])  # type: ignore[assignment]
            # The installer's shape, padded past any configuration the installer writes.
            config.write_text(json.dumps(body) + " " * (2 << 20))

    return leave


@pytest.mark.parametrize(
    "kind", ["named pipe", "link", "directory link", "hard link", "directory", "oversized"]
)
def test_the_session_s_configuration_is_read_as_a_bounded_regular_file_or_refused(
    tmp_path: Path, store: StandInStore, kind: str
) -> None:
    """The comparison's read of the raw session's tool list refuses all but the file itself.

    A pipe does not hold the round; a link, at the name or on the way, is not read through, so
    a forged tool list never reaches the comparison.
    """
    arm = StandInArm(left=_left_at_config(kind, tmp_path))
    config = tmp_path / "round" / "work" / "0000-1" / "place" / "session" / "session" / CONFIG_NAME
    outcome = _within(
        lambda: _round(store, tmp_path, arm), config if kind == "named pipe" else None
    )
    assert isinstance(outcome, Exception), "a configuration that is not the file itself was taken"
    told = f"{outcome} {getattr(outcome, 'context', {})}"
    assert "configuration" in told, told
    assert "Forged" not in told, "the forged tool list was read through a link"


@pytest.mark.parametrize("kind", ["named pipe", "hard link"])
def test_the_session_s_stream_is_read_as_a_regular_file_or_refused_after_the_session(
    tmp_path: Path, store: StandInStore, kind: str
) -> None:
    """A pipe or a second link at the stream's name refuses the trial; nothing waits on it."""
    outside = tmp_path / "outside.jsonl"
    outside.write_text("")

    def leave(place: Path, _harness: Path) -> None:
        stream = place / "session" / "stdout.jsonl"
        outside.write_bytes(stream.read_bytes())
        stream.unlink()
        if kind == "named pipe":
            os.mkfifo(stream)
        else:
            os.link(outside, stream)

    arm = StandInArm(left=leave)
    stream = tmp_path / "round" / "work" / "0000-1" / "place" / "session" / "stdout.jsonl"
    outcome = _within(
        lambda: _round(store, tmp_path, arm), stream if kind == "named pipe" else None
    )
    assert isinstance(outcome, InvocationError), outcome


def _session_file(tmp_path: Path) -> Path:
    """A file where a session's own files lie: ``<run>/sessions/<id>/<name>``."""
    sdir = tmp_path / "run" / "sessions" / "s-1"
    sdir.mkdir(parents=True)
    return sdir / "stdout.jsonl"


@pytest.mark.parametrize("kind", ["named pipe", "hard link", "directory", "oversized"])
def test_a_session_s_own_file_is_read_as_a_bounded_regular_file_or_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A session's file is read: never a pipe, a second link, a directory, a giant."""
    path = _session_file(tmp_path)
    if kind == "named pipe":
        os.mkfifo(path)
    elif kind == "hard link":
        (tmp_path / "outside").write_text("outside")
        os.link(tmp_path / "outside", path)
    elif kind == "directory":
        path.mkdir()
    else:
        monkeypatch.setattr(dispatch, "MAX_SESSION_FILE_BYTES", 64, raising=False)
        path.write_bytes(b"x" * 65)
    outcome = _within(lambda: dispatch.read_session_file(path), path)
    assert isinstance(outcome, InvocationError), outcome


def test_a_session_s_own_file_at_the_bound_is_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _session_file(tmp_path)
    monkeypatch.setattr(dispatch, "MAX_SESSION_FILE_BYTES", 64, raising=False)
    path.write_bytes(b"x" * 64)
    assert dispatch.read_session_file(path) == b"x" * 64


def test_an_answer_with_another_link_to_its_file_is_not_taken(tmp_path: Path) -> None:
    """A hard link from the worktree to a file elsewhere is not the session's answer."""
    task = parse_task(json.dumps(own_task()).encode())
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    worktree = tmp_path / "place" / "worktree"
    worktree.mkdir(parents=True)
    os.link(outside, worktree / task.answer.path)
    out = tmp_path / "harness" / "answer" / task.answer.path
    assert raw._take_answer(worktree, task, out) == "not_a_file"
    assert not out.exists()


def test_a_named_pipe_left_at_the_stream_does_not_hold_the_credential_s_removal(
    tmp_path: Path,
) -> None:
    """The scrub of the credential from a session's stream refuses a pipe; it never waits on one."""
    path = _session_file(tmp_path)
    os.mkfifo(path)
    outcome = _within(lambda: dispatch.redact(path, "a-secret"), path)
    assert isinstance(outcome, InvocationError), outcome


def test_a_hard_link_left_at_the_stream_is_not_written_through_by_the_scrub(
    tmp_path: Path,
) -> None:
    """The scrub never rewrites a file that has another name outside the session's directory."""
    path = _session_file(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("before a-secret after")
    os.link(outside, path)
    outcome = _within(lambda: dispatch.redact(path, "a-secret"), None)
    assert isinstance(outcome, InvocationError), outcome
    assert outside.read_text() == "before a-secret after"
