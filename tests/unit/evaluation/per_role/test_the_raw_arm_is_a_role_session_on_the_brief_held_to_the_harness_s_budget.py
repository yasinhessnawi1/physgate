from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.raw import BudgetWatch, RawSetup, raw_bounds, stream_total
from physgate.evaluation.per_role.task import parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.run_config import RunBounds
from physgate.oslayer.probe import Absent, Present

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


def _install_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: RawSetup, temp: Path | None
) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    raw._install(
        setup, tmp_path / "worktree", tmp_path / f"s{len(list(tmp_path.glob('s*')))}", temp
    )
    return seen[0]


def test_the_raw_session_is_installed_as_the_raw_agent_with_the_tier_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = _install_argv(tmp_path, monkeypatch, _setup(tmp_path), Path("/tmp/pg-0123456789ab"))
    assert argv[argv.index("--profile") + 1] == "baseline"
    assert argv[argv.index("--held-out") + 1] == "/elsewhere/heldout"
    assert argv[argv.index("--os-layer-network") + 1] == "none"
    absent = _install_argv(tmp_path, monkeypatch, _setup(tmp_path), None)
    assert "--os-layer-network" not in absent and "--os-layer-temp" not in absent
    # The raw arm withholds nothing beyond the harness's own pins.
    assert "--review-material" not in argv


def test_a_session_given_further_places_to_withhold_has_each_withheld_from_its_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    setup = dataclasses.replace(_setup(tmp_path), withheld_reads=("/home/u", "/tmp/kb"))
    argv = _install_argv(tmp_path, monkeypatch, setup, Path("/tmp/pg-0123456789ab"))
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
    assert set(pins) == {
        "model",
        "claude_version",
        "effort",
        "max_output_tokens",
        "thinking_display",
        "tools",
        "role_python",
        "network",
        "os_layer",
        "brief_sha256",
        "answer",
    }
