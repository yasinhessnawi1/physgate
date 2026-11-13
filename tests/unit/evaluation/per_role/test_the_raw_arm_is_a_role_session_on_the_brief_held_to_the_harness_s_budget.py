from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from startup_stand_in import stand_in_spawn_env
from task_fixtures import own_task

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.compare import RAW_PINS
from physgate.evaluation.per_role.arms.raw import BudgetWatch, RawSetup, raw_bounds, stream_total
from physgate.evaluation.tiers.task import parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import Absent, Present
from physgate.oslayer.session_temp import session_temps_root

BOUNDS = RunBounds(
    binary_max_retries=0,
    session_wall_clock_s=1800.0,
    session_max_turns=150,
    infra_retry_delays_s=(),
)


def _message(n: int, start: dict[str, int], final_output: int) -> list[dict[str, Any]]:
    mid = f"msg_{n}"
    return [
        {
            "type": "stream_event",
            "event": {"type": "message_start", "message": {"id": mid, "usage": start}},
        },
        {"type": "assistant", "message": {"id": mid, "model": "m", "usage": start}},
        {"type": "assistant", "message": {"id": mid, "model": "m", "usage": start}},
        {
            "type": "stream_event",
            "event": {"type": "message_delta", "usage": {"output_tokens": final_output}},
        },
    ]


def _write(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def test_every_class_of_every_message_is_counted_once_at_its_final_usage(tmp_path: Path) -> None:
    start = {
        "input_tokens": 3,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 1000,
        "output_tokens": 1,
    }
    stream = tmp_path / "stdout.jsonl"
    _write(stream, _message(1, start, 50) + _message(2, start, 70))
    assert stream_total(stream) == 2 * (3 + 100 + 1000) + 50 + 70
    assert stream_total(tmp_path / "absent.jsonl") == 0


def test_the_raw_session_s_bounds_are_a_role_session_s_times_the_repair_budget() -> None:
    assert raw_bounds(BOUNDS) == (450, 5400.0)


def test_the_watch_stops_a_session_once_its_stream_passes_the_cap(tmp_path: Path) -> None:
    from physgate.orchestrator.processes import started_at

    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    started = started_at(process.pid)
    assert started is not None
    watch = BudgetWatch(stream, cap=500, process=process, started=started)
    watch.start()
    time.sleep(1.0)
    assert process.poll() is None  # under the cap, it runs
    _write(stream, _message(1, {"input_tokens": 400, "output_tokens": 1}, 200))
    process.wait(timeout=10)
    watch.stop()
    assert watch.exhausted_at == 600


def test_the_watch_stops_a_session_for_the_reason_its_checkpoint_gives(tmp_path: Path) -> None:
    from physgate.orchestrator.processes import started_at

    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")
    asked: list[int] = []

    def check(total: int) -> str | None:
        asked.append(total)
        return "no_task_held" if total > 100 else None

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    started = started_at(process.pid)
    assert started is not None
    watch = BudgetWatch(stream, cap=10**6, process=process, started=started, check=check)
    watch.start()
    time.sleep(1.0)
    assert process.poll() is None and asked and asked[-1] == 0
    _write(stream, _message(1, {"input_tokens": 100, "output_tokens": 1}, 50))
    process.wait(timeout=10)
    watch.stop()
    assert watch.stopped_for == ("no_task_held", 150) and watch.exhausted_at is None


def _setup(tmp_path: Path, **changes: Any) -> RawSetup:
    fields: dict[str, Any] = {
        "binary": "claude",
        "claude_version": "2.1.301",
        "model": "claude-opus-5-5",
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
        "bounds": BOUNDS,
        "credential": Credential(mode="api_key", secret="not-a-key"),
        "base_url": None,
        "install_bin": tmp_path / "install" / "bin" / "physgate",
        "role_python": None,
        "held_out": ("/elsewhere/heldout",),
        "held_out_canaries": (),
        "network": "none",
        "os_layer": Absent(reason="test", no_os_protection=False),
    }
    fields.update(changes)
    return RawSetup(**fields)


#: A session's own temporary directory as the raw arm names one: beneath the parent of them all.
#: Named only; the installer is not run on it here, so nothing is made there.
OWN_TEMP = Path(session_temps_root()) / "0123456789"


def _install_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup: RawSetup,
    temp: Path | None,
    own_temp: Path | None = None,
) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": stand_in_spawn_env()}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    raw._install(
        setup,
        tmp_path / "worktree",
        tmp_path / f"s{len(list(tmp_path.glob('s*')))}",
        temp,
        own_temp=own_temp,
    )
    return seen[0]


def test_the_raw_session_is_installed_as_the_raw_agent_with_the_tier_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = _install_argv(tmp_path, monkeypatch, _setup(tmp_path), OWN_TEMP, OWN_TEMP)
    assert argv[argv.index("--profile") + 1] == "baseline"
    assert argv[argv.index("--held-out") + 1] == "/elsewhere/heldout"
    assert argv[argv.index("--os-layer-network") + 1] == "none"
    # Where the layer runs, its temporary directory is the session's own, and no other.
    assert argv[argv.index("--os-layer-temp") + 1] == str(OWN_TEMP) and "--temp" not in argv
    absent = _install_argv(tmp_path, monkeypatch, _setup(tmp_path), None, OWN_TEMP)
    assert "--os-layer-network" not in absent and "--os-layer-temp" not in absent
    # The raw arm withholds nothing beyond the harness's own pins.
    assert "--review-material" not in argv


def test_a_session_given_further_places_to_withhold_has_each_withheld_from_its_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    setup = dataclasses.replace(_setup(tmp_path), withheld_reads=("/home/u", "/tmp/kb"))
    argv = _install_argv(tmp_path, monkeypatch, setup, OWN_TEMP, OWN_TEMP)
    given = [argv[i + 1] for i, a in enumerate(argv) if a == "--review-material"]
    assert given == ["/home/u", "/tmp/kb"]
    assert argv[argv.index("--held-out") + 1] == "/elsewhere/heldout"


@pytest.mark.parametrize(
    ("make", "status"),
    [
        (lambda w: None, "no_answer"),
        (lambda w: (w / "answer.json").write_bytes(b"x" * (64 * 1024 + 1)), "too_large"),
        (
            lambda w: (
                (w / "elsewhere.json").write_text("{}"),
                (w / "answer.json").symlink_to(w / "elsewhere.json"),
            ),
            "not_a_file",
        ),
        (lambda w: (w / "answer.json").mkdir(), "not_a_file"),
        (lambda w: (w / "answer.json").write_text("{}"), "found"),
    ],
    ids=["none", "too large", "a link", "a directory", "a file"],
)
def test_the_answer_taken_is_the_named_file_as_it_is(
    tmp_path: Path, make: Any, status: str
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    make(worktree)
    task = parse_task(json.dumps(own_task()).encode())
    out = tmp_path / "out" / "answer.json"
    assert raw._take_answer(worktree, task, out) == status
    assert out.exists() == (status == "found")


def test_a_work_directory_that_exists_is_refused(tmp_path: Path) -> None:
    task = parse_task(json.dumps(own_task()).encode())
    with pytest.raises(raw.RawArmError, match="exists"):
        raw.run_raw(task, _setup(tmp_path), tmp_path, cap=1)


def test_the_pins_name_every_condition_the_arms_are_held_equal_on(tmp_path: Path) -> None:
    task = parse_task(json.dumps(own_task()).encode())
    pins = raw.pins(
        task, _setup(tmp_path, os_layer=Present(mechanism="seatbelt", claude_version="2.1.301"))
    )
    # Exactly the pins the comparison knows: one the comparison would not read, or one it
    # reads that the raw arm never writes, is a difference no fair pair could clear.
    assert set(pins) == RAW_PINS
    assert pins["advisor"] is None and pins["endpoint"] == "default"


def test_the_raw_arm_records_the_canaries_it_looked_for_as_their_digest(tmp_path: Path) -> None:
    """The comparison holds them to the harness run's; the digest names no canary."""
    task = parse_task(json.dumps(own_task()).encode())
    canaries = ("f" * 32, "0" * 32)
    pins = raw.pins(task, _setup(tmp_path, held_out_canaries=canaries))
    digest = hashlib.sha256("\n".join(sorted(canaries)).encode()).hexdigest()
    assert pins.get("held_out_canaries_sha256") == digest


def test_the_raw_arm_records_its_bounds_as_it_ran_them(tmp_path: Path) -> None:
    """The binary's retries and delays as given, the turns and wall clock as multiplied."""
    task = parse_task(json.dumps(own_task()).encode())
    bounds = BOUNDS.model_copy(update={"binary_max_retries": 2, "infra_retry_delays_s": (60.0,)})
    pins = raw.pins(task, _setup(tmp_path, bounds=bounds))
    assert pins.get("bounds") == {
        "binary_max_retries": 2,
        "infra_retry_delays_s": [60.0],
        "session_max_turns": 450,
        "session_wall_clock_s": 5400.0,
    }


def test_the_raw_session_is_held_to_its_own_session_directory_and_its_own_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two places the installer withholds from a raw agent are named exactly.

    A narrower one (a directory inside the session's, another temp) installs as well, and
    leaves the session's stream, login and settings, or the temporary files of every other
    session, open to its tools.
    """
    for temp in (OWN_TEMP, None):
        argv = _install_argv(tmp_path, monkeypatch, _setup(tmp_path), temp, OWN_TEMP)
        sdir = Path(argv[argv.index("--state-dir") + 1]).parent
        assert argv[argv.index("--sessions-root") + 1] == str(sdir)
        assert argv[argv.index("--target") + 1] == str(sdir / "session")
        if temp is None:
            assert argv[argv.index("--temp") + 1] == str(OWN_TEMP)


def test_a_new_bound_is_recorded_as_the_session_ran_it(tmp_path: Path) -> None:
    """The bounds are recorded field by field from the bounds' own model, none written by hand."""

    class _MoreBounds(RunBounds):
        session_max_tools: int = 9

    task = parse_task(json.dumps(own_task()).encode())
    bounds = _MoreBounds(**BOUNDS.model_dump())
    recorded = raw.pins(task, _setup(tmp_path, bounds=bounds)).get("bounds")
    assert recorded == {
        "binary_max_retries": 0,
        "infra_retry_delays_s": [],
        "session_max_turns": 450,
        "session_wall_clock_s": 5400.0,
        "session_max_tools": 9,
    }


def test_without_the_os_layer_the_installed_session_withholds_its_own_and_every_other_s_files(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The raw arm's own argv, with no OS layer, through the real installer.

    The session's directory, the parent of every session's temporary directory and the
    temporary directory every session of the user shares are each refused to its reads; the
    only way back in is its own temporary directory, beneath the parent.
    """
    import argparse
    import os

    from physgate.hooks.cli import add_parser
    from physgate.hooks.config import SessionConfig

    worktree, sdir = outside_tmp / "worktree", outside_tmp / "session"
    worktree.mkdir()
    sdir.mkdir()
    argv = _install_argv(outside_tmp, monkeypatch, _setup(outside_tmp), None, OWN_TEMP)
    # The argv names the directories the capture made up; the real run names this test's.
    named = Path(argv[argv.index("--state-dir") + 1]).parent
    argv = [a.replace(str(named), str(sdir)) for a in argv]
    argv = [a.replace(str(outside_tmp / "worktree"), str(worktree)) for a in argv]
    monkeypatch.undo()
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(argv[1:])
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    config = SessionConfig.model_validate_json(Path(printed["config"]).read_text())
    roots = {Path(os.path.realpath(r.path)): r for r in config.protected_roots}

    def root(path: Path | str) -> Any:  # noqa: ANN401 - the installed root, by its place
        found = roots.get(Path(os.path.realpath(path)))
        assert found is not None, f"{path} is not withheld from the session"
        return found

    session = root(sdir)
    assert session.reads == "denied" and session.read_exceptions == ()
    family = root(session_temps_root())
    assert family.reads == "denied"
    assert [os.path.realpath(p) for p in family.read_exceptions] == [os.path.realpath(OWN_TEMP)]
    shared = root(f"/tmp/claude-{os.getuid()}")
    assert shared.reads == "denied" and shared.read_exceptions == ()
