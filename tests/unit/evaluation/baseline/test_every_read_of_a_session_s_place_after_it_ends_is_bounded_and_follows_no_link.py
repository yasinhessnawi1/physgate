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
from dataclasses import replace
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

from physgate.evaluation.baseline.runner import BaselineError, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.compare import ComparisonError, differences
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.tiers.task import Role, parse_task
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS
from physgate.orchestrator import dispatch
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.run_config import RunConfig

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


def _within(call: Callable[[], Any], fifo: Callable[[], Path] | None) -> Any:  # noqa: ANN401
    """What ``call`` returned or raised; the row fails on its assertion past the bound.

    ``fifo`` gives the pipe a hung read waits on, once the session has left it.
    """
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
        _release(fifo())
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

    def config() -> Path:
        return arm.calls[-1][2] / "session" / "session" / CONFIG_NAME

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

    def stream() -> Path:
        return arm.calls[-1][2] / "session" / "stdout.jsonl"

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


@pytest.mark.parametrize("kind", ["link", "named pipe"])
def test_the_token_watch_reads_the_stream_as_a_session_s_own_file(
    tmp_path: Path, kind: str
) -> None:
    """The watch refuses a link or a pipe at the stream, so the watch stops the session."""
    path = _session_file(tmp_path)
    if kind == "link":
        (tmp_path / "outside").write_text("")
        path.symlink_to(tmp_path / "outside")
    else:
        os.mkfifo(path)
    outcome = _within(lambda: raw.stream_total(path), path)
    assert isinstance(outcome, InvocationError), outcome


def test_the_scrub_refuses_a_stream_past_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _session_file(tmp_path)
    monkeypatch.setattr(dispatch, "MAX_SESSION_FILE_BYTES", 64)
    path.write_bytes(b"a-secret" + b"x" * 64)
    with pytest.raises(InvocationError, match="too large"):
        dispatch.redact(path, "a-secret")
    assert path.read_bytes().startswith(b"a-secret"), "a file past the bound was rewritten"


def test_the_raw_arm_s_record_in_its_place_is_not_read_through_a_link(
    tmp_path: Path, store: StandInStore
) -> None:
    """Where the arm's record lies in the session's place, a link at its name is refused."""
    task = store.tasks["visible"][0]
    run = harness_run(tmp_path / "runs", task, store)
    place = tmp_path / "trial" / "place"
    place.mkdir(parents=True)
    record = tmp_path / "elsewhere.json"
    record.write_text(json.dumps({"pins": {}, "task": task.id}))
    (place / "raw.json").symlink_to(record)
    with pytest.raises(ComparisonError, match="record could not be read"):
        differences(run, place, role="control", task=task)


def test_a_raw_session_whose_binary_cannot_be_measured_is_refused_before_it_starts(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()

    def given_none(config: RunConfig, role: Role) -> RawSetup:
        return replace(setup_for(config, role), binary=str(tmp_path / "no-such-binary"))

    with pytest.raises(BaselineError) as raised:
        run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=run_set((run, 0)),
            out=tmp_path / "round",
            setup_for=given_none,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
        )
    assert raised.value.context.get("refused_because") == "binary"
    assert arm.calls == []


def test_an_answer_held_to_an_identity_list_that_is_not_whole_is_not_taken(
    tmp_path: Path,
) -> None:
    task = parse_task(json.dumps(own_task()).encode())
    worktree = tmp_path / "place" / "worktree"
    worktree.mkdir(parents=True)
    (worktree / task.answer.path).write_text("{}")
    out = tmp_path / "harness" / "answer" / task.answer.path
    assert raw._take_answer(worktree, task, out, []) == "not_a_file"
    assert not out.exists()


def test_a_visible_session_is_withheld_the_harness_s_directory_beside_its_place(
    tmp_path: Path, store: StandInStore
) -> None:
    """The harness's directory beside a visible trial's place is withheld from its session.

    The trial lies in the store's work root, which the run's roots hold; the session is given
    its own place out of them and nothing else, so the harness's directory beside it, as it is
    while the session runs, is among what it withholds.
    """
    task = store.tasks["visible"][0]
    withheld: list[tuple[Path, tuple[str, ...]]] = []
    arm = StandInArm()

    def seen(task_: Any, setup: RawSetup, work: Path, *, cap: int, harness: Path) -> Any:  # noqa: ANN401
        carved = setup.held_out_carved
        held = raw.held_out_but(setup.held_out, Path(carved)) if carved else setup.held_out
        withheld.append((harness, (*held, *vars(setup).get("held_out_also", ()))))
        assert setup.held_out == store.held_out, "the run's own roots are given as recorded"
        return arm(task_, setup, work, cap=cap, harness=harness)

    run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=run_set((harness_run(tmp_path / "runs", task, store), 0)),
        out=tmp_path / "round",
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=seen,
        sleep=lambda _s: None,
    )
    ((harness, held),) = withheld
    assert os.path.realpath(harness) in {os.path.realpath(p) for p in held}
    assert os.path.realpath(tmp_path / "round") in held, "the round's directory is not withheld"
