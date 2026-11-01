"""A run's reviews are looked for under the review root it recorded, whatever a command names.

A review's session directory lives beneath the review root, and a later command finds it only
beneath the root it is given. The first command that names a root for a run records it, resolved
and absolute: ``decompose`` when it reviews the plan, else the first ``run`` or ``resume``. A later
``run`` or ``resume`` that names another is refused before it stops or spawns anything, and says
both. A run recorded before the record existed goes on as it did, and records the root it is given.
``~`` in a root is expanded wherever the root is read, so ``decompose``, ``run`` and the reviewer
name one place.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGate, FakeReviewer, KilledError, Rig, plan
from test_a_review_session_a_killed_decompose_left_is_stopped_by_the_next_command import (
    CANARY,
    EXPOSED_FILE,
    OTHER_START,
    SECRET,
    SESSION,
    SIDE_FILE,
    WITH_CANARY,
    Recording,
)
from test_decompose_reviews_the_plan_before_it_writes_anything import (
    Calls,
    Stopped,
    _args,
    _exit,
    calls,
)
from test_the_physgate_command_starts_and_decides import _run_args, fake_binary

from physgate.cli import main
from physgate.orchestrator import dispatch
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.loop import Loop

__all__ = ["calls"]  # the fixture, used by name

RECORD = "review_root.json"
REVIEW = "rev-1"
STARTED = "Mon Jan  1 00:00:00 2001"
SHOWN = (
    json.dumps(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": f"x <!-- {CANARY} -->"}]},
        }
    )
    + "\n"
)


def outcome(how: Callable[[], Any]) -> Any:  # noqa: ANN401 - a code, or what escaped
    """What ``how`` returned, or the exception that escaped it: a row asserts on either."""
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the row asserts on
        return exc


def _args_with_root(tmp_path: Path, command: str, root: str) -> list[str]:
    args = [command, *_run_args(tmp_path)[1:]]
    args[args.index("--review-root") + 1] = root
    return args


def _registrations() -> Registrations:
    return Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})


@pytest.fixture
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A decomposed run holding the held-out canary, whose sessions are never spawned here."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    def spawned(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        msg = "a session was spawned"
        raise KilledError(msg)

    # A session spawned is the command going on where the row says it stops.
    monkeypatch.setattr(dispatch.ClaudeDispatcher, "run", spawned)
    rig = Rig(tmp_path / "run", config_overrides={"held_out_canaries": (CANARY,)})
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    return rig.run_dir


def _killed_in_its_review(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """The run's ``run`` is killed after its review's end record, the canary in its stream."""

    def run(self: Loop) -> Any:  # noqa: ANN401
        self._spawned(REVIEW, 999_999, STARTED)  # noqa: SLF001 - the loop's own spawn line
        sdir = root / REVIEW / "session"
        sdir.mkdir(parents=True)
        (sdir / "owner.json").write_text(json.dumps({"run_id": self.config.run_id}))
        record = {"pid": 999_999, "started": STARTED, "session_id": REVIEW, "kind": "reviewer"}
        (sdir / "process.json").write_text(json.dumps(record))
        (sdir / "stdout.jsonl").write_text(SHOWN)
        (sdir / "ended.json").write_text(
            json.dumps({"exit": 0, "timed_out": False, "left_running": []})
        )
        raise KilledError

    monkeypatch.setattr(Loop, "run", run)


def _incidents(run_dir: Path) -> list[str]:
    rows = [json.loads(raw) for raw in (run_dir / "events.jsonl").read_bytes().splitlines()]
    return [r["cause"] for r in rows if r["kind"] == "incident"]


# --- a run or resume naming another root ---------------------------------------------------------


@pytest.mark.parametrize("command", ["run", "resume"])
def test_a_command_naming_another_root_is_refused_before_anything_runs(
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    first = (tmp_path / "review-scratch").resolve()
    _killed_in_its_review(monkeypatch, first)
    killed = outcome(lambda: main(_args_with_root(tmp_path, "run", str(first)), _registrations()))
    assert isinstance(killed, KilledError), killed
    stream = first / REVIEW / "session" / "stdout.jsonl"
    events, shown = (run_dir / "events.jsonl").read_bytes(), stream.read_bytes()
    capsys.readouterr()

    other = (tmp_path / "other-scratch").resolve()
    other.mkdir()
    again = outcome(lambda: main(_args_with_root(tmp_path, command, str(other)), _registrations()))
    err = capsys.readouterr().err
    assert again == 2, f"a {command} under another root went on: {again!r}"
    said = json.loads(err.strip().splitlines()[-1])
    assert (said.get("recorded"), said.get("named")) == (str(first), str(other)), said
    assert str(first) in said["error"] and str(other) in said["error"]
    assert (run_dir / "events.jsonl").read_bytes() == events, "the refused command wrote a line"
    assert stream.read_bytes() == shown


def test_the_recorded_root_finds_the_killed_review_and_halts_on_its_exposure(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = (tmp_path / "review-scratch").resolve()
    _killed_in_its_review(monkeypatch, first)
    killed = outcome(lambda: main(_args_with_root(tmp_path, "run", str(first)), _registrations()))
    assert isinstance(killed, KilledError), killed
    other = (tmp_path / "other-scratch").resolve()
    other.mkdir()
    assert outcome(lambda: main(_args_with_root(tmp_path, "resume", str(other)), _registrations()))
    assert _incidents(run_dir) == []
    taken = outcome(lambda: main(_args_with_root(tmp_path, "resume", str(first)), _registrations()))
    assert not isinstance(taken, KilledError), "the resume under the recorded root spawned"
    assert _incidents(run_dir) == ["held_out_read"], "the killed review's exposure was not found"


# --- what is recorded ----------------------------------------------------------------------------


def test_the_first_run_records_its_root_resolved(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _killed_in_its_review(monkeypatch, (tmp_path / "review-scratch").resolve())
    monkeypatch.chdir(tmp_path)
    killed = outcome(
        lambda: main(_args_with_root(tmp_path, "run", "review-scratch"), _registrations())
    )
    assert isinstance(killed, KilledError), killed
    assert (run_dir / RECORD).is_file(), "the first run recorded no review root"
    assert json.loads((run_dir / RECORD).read_text()) == {
        "review_root": str((tmp_path / "review-scratch").resolve())
    }


def test_a_run_recorded_before_the_record_goes_on_and_records_the_root_it_names(
    tmp_path: Path,
    run_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run with no record, as every run before it had: driven as before, and held after."""

    def run(self: Loop) -> Any:  # noqa: ANN401
        raise KilledError

    monkeypatch.setattr(Loop, "run", run)
    assert not (run_dir / RECORD).exists()
    named = (tmp_path / "other-scratch").resolve()
    named.mkdir()
    went_on = outcome(lambda: main(_args_with_root(tmp_path, "run", str(named)), _registrations()))
    assert isinstance(went_on, KilledError), f"a run with no record was not driven: {went_on!r}"
    assert (run_dir / RECORD).is_file(), "the run recorded no review root"
    assert json.loads((run_dir / RECORD).read_text()) == {"review_root": str(named)}
    capsys.readouterr()
    first = (tmp_path / "review-scratch").resolve()
    again = outcome(lambda: main(_args_with_root(tmp_path, "resume", str(first)), _registrations()))
    assert again == 2
    assert json.loads(capsys.readouterr().err.strip().splitlines()[-1])["named"] == str(first)


def test_a_record_that_cannot_be_read_refuses(
    tmp_path: Path, run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (run_dir / RECORD).write_text("{")
    events = (run_dir / "events.jsonl").read_bytes()
    first = (tmp_path / "review-scratch").resolve()
    refused = outcome(
        lambda: main(_args_with_root(tmp_path, "resume", str(first)), _registrations())
    )
    assert refused == 2
    assert "cannot be read" in capsys.readouterr().err
    assert (run_dir / "events.jsonl").read_bytes() == events


# --- decompose records the root its review runs under -------------------------------------------


def test_a_run_after_decompose_naming_another_root_is_refused_and_stops_nothing(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(tmp_path, WITH_CANARY)
    first = (tmp_path / "review-scratch").resolve()
    reviewing = Recording(Stopped(), (SESSION, 4242, OTHER_START), stream=SHOWN, root=first)
    with pytest.raises(Stopped):
        _exit(args, reviewing)
    assert (tmp_path / "run" / SIDE_FILE).exists()
    assert (tmp_path / "run" / RECORD).is_file(), "decompose recorded no review root"
    assert json.loads((tmp_path / "run" / RECORD).read_text()) == {"review_root": str(first)}
    capsys.readouterr()
    other = (tmp_path / "other-scratch").resolve()
    refused = outcome(lambda: main(_args_with_root(tmp_path, "run", str(other))))
    said = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert refused == 2
    assert (said.get("recorded"), said.get("named")) == (str(first), str(other)), said
    assert (tmp_path / "run" / SIDE_FILE).exists(), "the refused run stopped the review first"


class Credentialed(Recording):
    """Killed with the credential in its directory and the canary in its stream.

    Its session is written beneath the root its setup was given, as a plan review's is.
    """

    def review_plan(self, under: Any) -> Any:  # noqa: ANN401
        self.root = Path(self.setups[-1].review_root)
        assert self.hook is not None
        sdir = self.root / self.spawned[0] / "session"
        (sdir / "state").mkdir(parents=True)
        self.hook(*self.spawned)
        (sdir / "state" / "key").write_text(SECRET)
        (sdir / "stdout.jsonl").write_text(
            SHOWN + json.dumps({"type": "user", "echo": SECRET}) + "\n"
        )
        raise Stopped


def test_a_tilde_root_named_to_decompose_and_run_finds_scans_and_redacts_the_killed_review(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = (tmp_path / "home").resolve()
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # zsh passes ``--review-root=~/review-scratch`` on as it is written.
    monkeypatch.chdir(elsewhere)
    args = _args(tmp_path, WITH_CANARY)
    args[args.index("--review-root") + 1] = "~/review-scratch"
    with pytest.raises(Stopped):
        _exit(args, Credentialed(Stopped(), (SESSION, 4242, OTHER_START)))
    sdir = home / "review-scratch" / SESSION / "session"
    assert (sdir / "stdout.jsonl").is_file(), "the review did not run beneath the home directory"

    ran = outcome(lambda: main(_args_with_root(tmp_path, "run", "~/review-scratch")))
    assert ran == 2
    assert (tmp_path / "run" / EXPOSED_FILE).is_file(), "the killed review was not scanned"
    assert not (tmp_path / "run" / SIDE_FILE).exists(), "the killed review's record was kept"
    held = sorted(
        str(p.relative_to(sdir))
        for p in sdir.rglob("*")
        if p.is_file() and SECRET.encode() in p.read_bytes()
    )
    assert held == [], f"the credential is still in the review's directory: {held}"
