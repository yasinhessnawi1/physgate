"""The raw arm: one Claude Code session on the task's brief, and nothing of the harness.

The arm the harness is measured against (ARCH-143). It is invoked exactly as a role
session is (the same binary, model, effort, output-token limit, reasoning display, tools,
interpreter and OS layer, the same isolated environment), with two differences only: its
prompt is the task's brief, byte for byte, and its hooks are the ``baseline`` profile,
which keeps the held-out tier and the frozen experiments from it and nothing else of the
harness. It may use git in its own work area.

**Its budget** is the harness arm's: the run's total tokens on the same task and trial,
every class counted (input, cache writes, cache reads, output). A watcher reads the
session's stream as it is written, counts each message's final usage once as the run's own
accounting does, and stops the session when the count passes the cap. Usage is known per
message, so the session can pass the cap by at most the message in flight; the count it
reached is recorded, never trimmed. Its turn and wall-clock bounds are a role session's,
times the harness's repair budget, so neither bound binds before the token cap would.

What the session left is kept as sealed evidence: its stream, its answer, its end and a
record of every pin the comparison with the harness arm is held to.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.answer import MAX_ANSWER_BYTES
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.task import Task
from physgate.hooks.settings import PROFILE_TOOLS
from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.credentials import (
    Credential,
    remove_secrets,
    write_key_helper,
    write_login,
)
from physgate.orchestrator.decompose import read_stream
from physgate.orchestrator.dispatch import (
    check_after_stop,
    harness_protection,
    read_captured,
    redact,
    review_material_seen,
    runtime_paths,
    session_end_command,
    spawn_held,
    write_record,
)
from physgate.orchestrator.invocation import isolated_env, role_argv
from physgate.orchestrator.processes import stop_tree
from physgate.orchestrator.role_python import RolePython, session_bin
from physgate.orchestrator.run_config import Effort, Network, RunBounds, ThinkingDisplay
from physgate.oslayer.probe import Absent, Present
from physgate.reviewers.ending import SessionEnd, await_session

#: How often the watcher reads the stream.
WATCH_S = 0.5
#: The token ceiling the hook installer requires. The raw agent loads nothing always, so it
#: never binds; the token cap is the watcher's.
NO_ALWAYS_LOADED_CEILING = 1_000_000


class RawArmError(PerRoleError):
    """The raw arm could not be set up or run as asked."""


@dataclass(frozen=True)
class RawSetup:
    """Every pin of the raw arm, each the same as the harness arm's role sessions'."""

    binary: str
    claude_version: str
    model: str
    effort: Effort
    max_output_tokens: int
    thinking_display: ThinkingDisplay
    #: A role session's bounds; the raw arm's are these times the repair budget.
    bounds: RunBounds
    credential: Credential
    base_url: str | None
    install_bin: Path
    role_python: RolePython | None
    held_out: tuple[str, ...]
    held_out_canaries: tuple[str, ...]
    network: Network
    os_layer: Present | Absent


def stream_total(stream: Path) -> int:
    """Every token the stream's messages were charged for so far, each message once."""
    try:
        text = stream.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    _, usages, _ = read_stream(text)
    return sum(m.usage.total() for m in usages)


class BudgetWatch:
    """A thread that stops the session once its stream's token count passes the cap."""

    def __init__(self, stream: Path, cap: int, process: subprocess.Popen[bytes], started: str):
        """Watch ``stream``; stop ``process`` (started at ``started``) past ``cap`` tokens."""
        self.stream, self.cap = stream, cap
        self._process, self._started = process, started
        self.exhausted_at: int | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Begin watching."""
        self._thread.start()

    def stop(self) -> None:
        """Stop watching, once the session has ended."""
        self._done.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._done.wait(WATCH_S):
            if self._process.poll() is not None:
                return
            total = stream_total(self.stream)
            if total > self.cap:
                self.exhausted_at = total
                stop_tree(self._process.pid, self._started)
                return


def raw_bounds(bounds: RunBounds) -> tuple[int, float]:
    """The raw session's turn and wall-clock bounds: a role session's, times the repair budget."""
    return bounds.session_max_turns * REPAIR_BUDGET, bounds.session_wall_clock_s * REPAIR_BUDGET


def _install(setup: RawSetup, worktree: Path, sdir: Path, temp: Path | None) -> dict[str, Any]:
    state = sdir / "state"
    state.mkdir(mode=0o700, parents=True)
    (sdir / "config").mkdir(mode=0o700, exist_ok=True)
    helper: list[str] = []
    if setup.credential.mode == "api_key":
        helper = ["--api-key-helper", str(write_key_helper(state, setup.credential.secret))]
    argv = [
        str(setup.install_bin),
        "hooks",
        "install",
        "--profile",
        "baseline",
        "--worktree",
        str(worktree),
        "--state-dir",
        str(state),
        "--target",
        str(sdir / "session"),
        "--claude-config-dir",
        str(sdir / "config"),
        "--user-home",
        str(sdir / "home"),
        "--ceiling",
        str(NO_ALWAYS_LOADED_CEILING),
        *helper,
        # The harness checkout is protected from the raw agent and its shell reads denied:
        # what it would find there (the knowledge, the rubrics) is the harness's help.
        *harness_protection(),
        *(arg for root in setup.held_out for arg in ("--held-out", root)),
        *(["--os-layer-temp", str(temp)] if temp is not None else []),
        *(
            ["--os-layer-network", setup.network]
            if temp is not None and setup.network != "open"
            else []
        ),
        *(
            ["--os-layer-readable", str(sdir / "bin")]
            if temp is not None and setup.role_python is not None
            else []
        ),
    ]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        msg = "the hook installer refused the raw session"
        raise RawArmError(msg, stderr=done.stderr[-600:])
    if setup.credential.mode == "subscription":
        write_login(sdir / "config", setup.credential.secret)
    installed: dict[str, Any] = json.loads(done.stdout)
    return installed


def _take_answer(worktree: Path, task: Task, out: Path) -> str:
    """The raw session's answer, copied for the scorer: the file the brief names, as it is."""
    answer = worktree / task.answer.path
    if not answer.exists() and not answer.is_symlink():
        return "no_answer"
    if answer.is_symlink() or not answer.is_file():
        return "not_a_file"
    if answer.stat().st_size > MAX_ANSWER_BYTES:
        return "too_large"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(answer, out, follow_symlinks=False)
    return "found"


def run_session(prompt: str, setup: RawSetup, work: Path, *, cap: int) -> dict[str, Any]:
    """One session on ``prompt``, as the raw arm runs one, in the new directory ``work``.

    The session works in ``work/worktree``; what it leaves there is the caller's to take.
    Returns the session's record: how it ended, what it spent, and whether a held-out
    canary showed in its stream.

    Raises:
        RawArmError: ``work`` exists, the session could not be set up, or its credential
            could not be removed.
    """
    if work.exists():
        msg = f"{work} exists; each session gets a directory of its own"
        raise RawArmError(msg, work=str(work))
    worktree, sdir = work / "worktree", work / "session"
    # Private from the start: the session's credential is written beneath ``sdir``.
    work.mkdir(mode=0o700, parents=True)
    worktree.mkdir(mode=0o700)
    sdir.mkdir(mode=0o700)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True, capture_output=True)
    session_id = str(uuid.uuid4())
    temp: Path | None = None
    if isinstance(setup.os_layer, Present):
        temp = Path(f"/tmp/pg-{uuid.uuid4().hex[:12]}")
        temp.mkdir(mode=0o700)
    try:
        return _run(prompt, setup, work, worktree, sdir, session_id, temp, cap)
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def run_raw(task: Task, setup: RawSetup, work: Path, *, cap: int) -> dict[str, Any]:
    """Run the raw arm once on ``task`` in the new directory ``work``; its record.

    ``cap`` is the harness arm's token total on the same task and trial.

    Raises:
        RawArmError: ``work`` exists, the session could not be set up, or its credential
            could not be removed.
    """
    record = run_session(task.brief, setup, work, cap=cap)
    record.update(
        task=task.id,
        answer=_take_answer(work / "worktree", task, work / "answer" / task.answer.path),
        pins=pins(task, setup),
    )
    write_record(work.parent, work.name, record, "raw.json")
    return record


def _run(
    prompt: str,
    setup: RawSetup,
    work: Path,
    worktree: Path,
    sdir: Path,
    session_id: str,
    temp: Path | None,
    cap: int,
) -> dict[str, Any]:
    stdout, stderr = sdir / "stdout.jsonl", sdir / "stderr.txt"
    # One boundary from the first write of the credential to its removal: whatever ends
    # the session (an error, a refusal, the clock, the cap, a kill), the cleanup runs.
    try:
        ended, watch, seconds, after = _session(
            prompt, setup, worktree, sdir, session_id, temp, cap
        )
    finally:
        _clean(work, sdir, setup.credential.secret, (stdout, stderr))
    captured = read_captured(stdout)
    end = (
        "budget_exhausted"
        if watch.exhausted_at is not None
        else ("wall_clock" if ended.timed_out else "ended")
    )
    return {
        "session_id": session_id,
        "end": end,
        "exit_code": ended.exit_code,
        "left_running": list(ended.left_running),
        "wall_clock_s": seconds,
        "tokens": sum(m.usage.total() for m in captured.usage),
        "cap": cap,
        "answered_by": sorted(captured.answered),
        "held_out_seen": review_material_seen(stdout, frozenset(setup.held_out_canaries))
        is not None,
        "sentinel_after_stop": after.get("refused"),
    }


def _session(
    prompt: str,
    setup: RawSetup,
    worktree: Path,
    sdir: Path,
    session_id: str,
    temp: Path | None,
    cap: int,
) -> tuple[SessionEnd, BudgetWatch, float, dict[str, Any]]:
    """Install, spawn, watch and end the raw session; the credential's removal is the caller's."""
    # As a role session's: what the runtime makes is made first, so it is in the record.
    (sdir / "home").mkdir(mode=0o700, exist_ok=True)
    runtime_paths(worktree, sdir / "home")
    installed = _install(setup, worktree, sdir, temp)
    env = isolated_env(
        home=sdir / "home",
        config_dir=sdir / "config",
        binary=setup.binary,
        claude_version=setup.claude_version,
        max_retries=setup.bounds.binary_max_retries,
        max_output_tokens=setup.max_output_tokens,
        base_url=setup.base_url,
        api_key=None,
    )
    env.update(installed["spawn_env"])
    if setup.role_python is not None:
        env["PATH"] = f"{session_bin(sdir, setup.role_python)}:{env['PATH']}"
    max_turns, wall_clock = raw_bounds(setup.bounds)
    argv = role_argv(
        setup.binary,
        prompt=prompt,
        spawn_args=tuple(installed["spawn_args"]),
        model=setup.model,
        session_id=session_id,
        max_turns=max_turns,
        effort=setup.effort,
        thinking_display=setup.thinking_display,
    )
    check = session_end_command(Path(installed["settings"]))
    stdout, stderr = sdir / "stdout.jsonl", sdir / "stderr.txt"

    def while_held(pid: int, started: str) -> None:
        record = {"pid": pid, "started": started, "session_id": session_id, "kind": "raw"}
        write_record(sdir.parent, sdir.name, record, "process.json")

    began = time.monotonic()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process, started = spawn_held(
            argv,
            cwd=worktree,
            env=env,
            out=out,
            err=err,
            session_id=session_id,
            on_spawn=None,
            while_held=while_held,
        )
        watch = BudgetWatch(stdout, cap, process, started)
        watch.start()
        try:
            ended = await_session(process, started, wall_clock)
        finally:
            watch.stop()
    seconds = time.monotonic() - began
    after = check_after_stop(check, session_id, worktree, env, sdir / "state")
    return ended, watch, seconds, after


def _clean(work: Path, sdir: Path, secret: str, streams: tuple[Path, ...]) -> None:
    """Remove the credential and scrub it from the session's streams, or record why not.

    The role session's own helpers, which reach every file through descriptors without
    following a link. A cleanup that fails is recorded beside the session and refuses the
    result: the credential may still be on disk.

    Raises:
        RawArmError: any part of the cleanup failed.
    """
    errors: list[str] = []
    try:
        remove_secrets(sdir / "state", sdir / "config")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded and refuses below
        errors.append(repr(exc))
    for stream in streams:
        try:
            redact(stream, secret)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded and refuses below
            errors.append(repr(exc))
    if errors:
        record = {"error": "; ".join(errors).replace(secret, "[redacted]")}
        write_record(work.parent, work.name, record, "cleanup.json")
        msg = "the raw session's credential could not be removed: " + record["error"]
        raise RawArmError(msg, work=str(work))


def pins(task: Task, setup: RawSetup) -> dict[str, Any]:
    """Everything the raw arm is held equal to the harness arm on (criterion: fair arms)."""
    return {
        "model": setup.model,
        "claude_version": setup.claude_version,
        "effort": setup.effort,
        "max_output_tokens": setup.max_output_tokens,
        "thinking_display": setup.thinking_display,
        "tools": sorted(PROFILE_TOOLS["baseline"]),
        "role_python": None if setup.role_python is None else setup.role_python.model_dump(),
        "network": setup.network,
        "os_layer": setup.os_layer.model_dump(),
        "brief_sha256": hashlib.sha256(task.brief.encode()).hexdigest(),
        "answer": task.answer.model_dump(),
    }
