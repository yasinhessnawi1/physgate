"""The raw arm: one Claude Code session on the task's brief, and nothing of the harness.

The arm the harness is measured against (ARCH-143). It is invoked exactly as a role
session is (the same binary, model, effort, output-token limit, reasoning display, tools,
interpreter, tool environment, tool servers and OS layer, the same isolated environment), with
two differences only: its
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

**Its tools** are the harness run's: the tool environment the run recorded, held before the
session and scanned again after it as a role session's is, with its programs first on the
session's search path and its roots read and run but written by no tool; and the servers the
run recorded for the raw agent's profile, offered only where the OS layer contains them.

What the session left is kept as sealed evidence: its stream, its answer, its end and a
record of every pin the comparison with the harness arm is held to.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.answer import MAX_ANSWER_BYTES
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.task import Task
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import session_tool_search
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
    runtime_git_paths,
    runtime_paths,
    session_end_command,
    spawn_held,
    write_record,
)
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.orchestrator.invocation import NO_TOOL_SERVERS, isolated_env, role_argv
from physgate.orchestrator.processes import kill_own, stop_tree
from physgate.orchestrator.role_python import RolePython, session_bin
from physgate.orchestrator.run_config import (
    Effort,
    Network,
    RunBounds,
    ThinkingDisplay,
    ToolServers,
    endpoint_of,
    harness_root,
)
from physgate.orchestrator.tool_environment import (
    changed_while_running,
    forbidden_places,
    hold_before_session,
    profile_launches,
    series_environment,
    session_environment,
    wire_session,
)
from physgate.oslayer.containment import (
    ContainmentError,
    ServerLaunch,
    contained_servers,
    wrappers,
)
from physgate.oslayer.probe import Absent, Present
from physgate.oslayer.session_temp import make_session_temp
from physgate.reviewers.ending import SessionEnd, await_session
from physgate.toolenv.record import ToolEnvironment

#: How often the watcher reads the stream.
WATCH_S = 0.5
#: The longest the cap may go without a completed reading of the stream: ten readings. A
#: watch that has not read the stream in this long has stopped counting, whether it is stuck
#: in a reading, behind, or gone, and the session is stopped (``watch_stalled``).
HEARTBEAT_S = 5.0
#: The longest a session may run with no stream to count: a session whose stream has not
#: appeared this long after the watch started is stopped (``no_stream``).
NO_STREAM_S = 10.0
#: The longest one call of the checkpoint may run. It runs on a thread of its own, so a slow
#: call never delays the cap; a call past this has hung, and the session is stopped
#: (``watch_stalled``). The bound is on one call, and one call of an author's checkpoint
#: scores every task that changed since the last, seconds each: a burst of tasks written
#: between two readings, or a scorer slowed by contention for the interpreter, can pass it on
#: a sound session. That stall is false, and it fails closed: the session is stopped and none
#: of its tasks is pooled; nothing runs on uncounted.
CHECKPOINT_S = 120.0
#: The ends at which the watch could not hold the session to its cap: what the session did
#: was not counted as the watch meant it to be, and what it made is not taken.
WATCH_FAILURES = frozenset({"watch_failed", "watch_stalled", "no_stream"})
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
    #: Further places withheld from the session's file tools and its shell, without the
    #: held-out tier's tripwire (which refuses every call where any file has a second
    #: name): what a task author must not read beyond the tier, such as the user's home.
    #: Empty for the raw arm, which is held to the harness arm's pins.
    withheld_reads: tuple[str, ...] = ()
    #: Places no tool of the session writes, by the file tools, the shell or the OS layer,
    #: but for ``writable_within`` beneath them: a blind check's whole tier-set store, but its
    #: own directory there. Empty for the raw arm.
    write_protected: tuple[str, ...] = ()
    writable_within: tuple[str, ...] = ()
    #: The tool environment the harness run recorded: the session reads and runs it, writes
    #: none of it, and finds its programs first on its search path. ``None`` where the run
    #: named none.
    tool_environment: ToolEnvironment | None = None
    #: The tool servers the harness run recorded. The session is offered those of the raw
    #: agent's profile (``baseline``), started from :attr:`tool_environment`, and only where
    #: the OS layer contains them, as a role session is offered the role profile's.
    tool_servers: ToolServers | None = None

    def __post_init__(self) -> None:
        """Refuse servers without the environment they start from, as a run's record does."""
        if self.tool_servers is not None and self.tool_environment is None:
            msg = "tool servers start from a tool environment, and the raw arm is given none"
            raise RawArmError(msg)


def server_launches_for(setup: RawSetup) -> tuple[ServerLaunch, ...]:
    """How the raw agent's tool servers start, from the setup's records and the register.

    The role sessions' come from the same records by the same code, each its own profile's.

    Raises:
        RawArmError: the register or the bound on an answer is not the one recorded, or a
            server cannot be started from the recorded environment.
    """
    try:
        return profile_launches(setup.tool_servers, setup.tool_environment, "baseline")
    except RunConfigError as exc:
        raise RawArmError(str(exc)) from exc


def offered_servers(setup: RawSetup, temp: Path | None) -> tuple[str, ...]:
    """The servers the raw session is offered by name: none without the OS layer (``temp``)."""
    if setup.tool_servers is None or setup.tool_environment is None or temp is None:
        return ()
    return tuple(setup.tool_servers.profiles.get("baseline", ()))


def contained_servers_for(
    setup: RawSetup,
    launches: tuple[ServerLaunch, ...],
    config_file: Path,
    sdir: Path,
    own_temp: Path | None,
    env: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    """The session's tool-server configuration, and the wrappers its servers may name.

    As a role session's: none without the OS layer, which alone contains a server the binary
    starts; each server's rules come from the session's own configuration, as installed.

    Raises:
        RawArmError: a server cannot be contained here, so the session is not started.
    """
    if not launches or not isinstance(setup.os_layer, Present):
        return NO_TOOL_SERVERS, ()
    if own_temp is None:
        msg = "a session offered tool servers needs a temporary directory of its own for them"
        raise RawArmError(msg)
    platform = sys.platform
    bwrap = shutil.which("bwrap", path=env["PATH"]) if platform.startswith("linux") else None
    config = SessionConfig.model_validate_json(config_file.read_bytes())
    try:
        servers = contained_servers(
            config,
            launches,
            platform=platform,
            temp_dir=own_temp,
            profiles_dir=sdir / "servers",
            bwrap=bwrap,
        )
    except ContainmentError as exc:
        msg = "a tool server cannot be contained here, so the session is not started"
        raise RawArmError(msg, error=str(exc)) from exc
    return servers, wrappers(platform, bwrap)


def hold_tools(setup: RawSetup, work: Path) -> str | None:
    """Hold the setup's tool environment to its record; the scan to hold it to after the session.

    Measured in full, as a run's first session's is, before anything of the session exists, in
    none of the places a run's environment may not lie in (the raw arm's own directory among
    them). ``None`` with no environment.

    Raises:
        RawArmError: the environment is not the recorded one, or lies where it may not.
    """
    if setup.tool_environment is None:
        return None
    try:
        return hold_before_session(
            setup.tool_environment,
            None,
            forbidden=forbidden_places(
                harness=harness_root(),
                install=setup.install_bin.parent.parent,
                run_dir=work,
                target=None,
            ),
        )
    except InvocationError as exc:
        raise RawArmError(str(exc)) from exc


def stream_total(stream: Path) -> int:
    """Every token the stream's messages were charged for so far, each message once."""
    try:
        text = stream.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    _, usages, _ = read_stream(text)
    return sum(m.usage.total() for m in usages)


#: A checkpoint the watch asks at each reading, given the tokens spent so far: a reason to
#: stop the session now, or ``None`` to let it run on. The raw arm has none: its only
#: bound is the cap. A task author has one, on how its tasks keep pace with its spending.
Checkpoint = Callable[[int], str | None]


class BudgetWatch:
    """Threads that stop the session once its stream's token count passes the cap, failing closed.

    The cap is only as good as its counting, so every way the counting can stop stops the
    session too, and the first reason is kept in :attr:`end`:

    - ``budget_exhausted``: the count passed the cap; :attr:`exhausted_at` holds it;
    - a reason the ``check`` returned; :attr:`stopped_for` holds it with the count then;
    - ``watch_failed``: a reading of the stream or the checkpoint raised; :attr:`failure`
      says what;
    - ``watch_stalled``: no reading completed within :data:`HEARTBEAT_S`, a checkpoint call
      ran past :data:`CHECKPOINT_S`, or a watch thread is gone while the session runs;
    - ``no_stream``: the stream had not appeared :data:`NO_STREAM_S` after the start.

    The last three are :data:`WATCH_FAILURES`. A session that ends by itself as the guard
    looks keeps its own end.

    Three threads: the reader counts the stream every :data:`WATCH_S`; the checkpoint, when
    there is one, is asked with the latest count, on a thread of its own, so a slow check
    never delays the count the cap is held to; a guard holds both to their heartbeat and
    stops the session for them when they cannot. A stop that fails kills the session's
    process group instead, and :attr:`stop_error` says why the stop failed; the result of
    such a session is refused (:func:`require_stopped`).
    """

    def __init__(
        self,
        stream: Path,
        cap: int,
        process: subprocess.Popen[bytes],
        started: str,
        check: Checkpoint | None = None,
    ):
        """Watch ``stream``; stop ``process`` (started at ``started``) past ``cap`` tokens."""
        self.stream, self.cap = stream, cap
        self._process, self._started = process, started
        self._check = check
        self.exhausted_at: int | None = None
        self.stopped_for: tuple[str, int] | None = None
        self.end: str | None = None
        self.failure: str | None = None
        self.stop_error: str | None = None
        self._total = 0
        self._since = time.monotonic()
        self._last_read = self._since
        #: When the checkpoint's call in progress began; ``None`` between calls.
        self._asking_since: float | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._checker = threading.Thread(target=self._ask, daemon=True)
        self._guard = threading.Thread(target=self._hold, daemon=True)

    def start(self) -> None:
        """Begin watching."""
        self._since = self._last_read = time.monotonic()
        self._reader.start()
        if self._check is not None:
            self._checker.start()
        self._guard.start()

    def stop(self) -> None:
        """Stop watching, once the session has ended.

        A thread stuck in a reading is not waited for beyond a heartbeat: the session it
        watched has ended, and the thread is a daemon.
        """
        self._done.set()
        for thread in (self._reader, self._checker, self._guard):
            if thread.is_alive():
                thread.join(timeout=HEARTBEAT_S)

    # -------------------------------------------------------------------- the threads

    def _read(self) -> None:
        try:
            self._read_loop()
        except Exception as exc:  # noqa: BLE001 - a watch that cannot count stops the session
            self._stop("watch_failed", failure=f"reading the stream: {exc!r}")

    def _read_loop(self) -> None:
        while not self._done.wait(WATCH_S):
            if self._process.poll() is not None:
                return
            if not self.stream.exists():
                # A look that found nothing yet is a completed reading too: the guard holds a
                # stream that never appears to a bound of its own.
                with self._lock:
                    self._last_read = time.monotonic()
                continue
            total = stream_total(self.stream)
            with self._lock:
                self._total, self._last_read = total, time.monotonic()
            if total > self.cap:
                self.exhausted_at = total
                self._stop("budget_exhausted")
                return

    def _ask(self) -> None:
        assert self._check is not None  # started only with a checkpoint
        try:
            while not self._done.wait(WATCH_S):
                if self._process.poll() is not None:
                    return
                with self._lock:
                    total, self._asking_since = self._total, time.monotonic()
                reason = self._check(total)
                with self._lock:
                    self._asking_since = None
                if reason is not None:
                    self.stopped_for = (reason, total)
                    self._stop(reason)
                    return
        except Exception as exc:  # noqa: BLE001 - a checkpoint that raises stops the session
            self._stop("watch_failed", failure=f"the checkpoint: {exc!r}")

    def _hold(self) -> None:
        try:
            self._hold_loop()
        except Exception as exc:  # noqa: BLE001 - a guard that cannot look stops the session
            self._stop("watch_failed", failure=f"the guard: {exc!r}")

    def _hold_loop(self) -> None:
        while not self._done.wait(WATCH_S):
            if self._process.poll() is not None or self.end is not None:
                return
            now = time.monotonic()
            with self._lock:
                last_read, asking_since = self._last_read, self._asking_since
            if asking_since is not None and now - asking_since > CHECKPOINT_S:
                self._stall("watch_stalled")
                return
            if not self.stream.exists():
                if now - self._since > NO_STREAM_S:
                    self._stall("no_stream")
                    return
                continue
            gone = not self._reader.is_alive() or (
                self._check is not None and not self._checker.is_alive()
            )
            if gone or now - last_read > HEARTBEAT_S:
                self._stall("watch_stalled")
                return

    def _stall(self, end: str) -> None:
        """Stop the session for ``end``, unless it has ended since the guard looked at it.

        The reader and the checkpoint return once the session has ended, and the guard looks
        at the session before it looks at them: a thread gone, or a bound passed, because the
        session ended in between is no failure of the watch, and the session's own end stands.
        """
        if self._process.poll() is None:
            self._stop(end)

    # ---------------------------------------------------------------------- the stop

    def _stop(self, end: str, *, failure: str | None = None) -> None:
        """Stop the session for ``end``, once: the first reason is the one recorded."""
        with self._lock:
            if self.end is not None:
                return
            self.end, self.failure = end, failure
        try:
            stop_tree(self._process.pid, self._started)
        except Exception as exc:  # noqa: BLE001 - recorded; the group is killed instead
            self.stop_error = repr(exc)
            # The dispatcher's kill of a session it spawned leading a group of its own and
            # has not reaped: the group by its id, with no process table. What left the
            # group is not reached, and the result is refused (require_stopped).
            kill_own(self._process)


def held_out_seen(stream: Path, canaries: tuple[str, ...]) -> bool | None:
    """Whether a held-out canary showed in ``stream``; ``None`` with no canary to look for.

    With nothing to look for, nothing in the stream can show a canary, and "not seen" is a
    claim the record cannot make: it is unknown, for the reader of the record to refuse
    where canaries exist.
    """
    if not canaries:
        return None
    return review_material_seen(stream, frozenset(canaries)) is not None


def require_stopped(watch: BudgetWatch) -> None:
    """Refuse the result of a session the watch could not stop as it meant to.

    Raises:
        RawArmError: the watch's stop of the session failed; its group was killed instead,
            and whatever ran in it after the cap is not accounted for.
    """
    if watch.stop_error is not None:
        msg = (
            f"the session could not be stopped when its watch said ({watch.end}): "
            f"{watch.stop_error}"
        )
        raise RawArmError(msg, end=watch.end or "", stop_error=watch.stop_error)


def raw_bounds(bounds: RunBounds) -> tuple[int, float]:
    """The raw session's turn and wall-clock bounds: a role session's, times the repair budget."""
    return bounds.session_max_turns * REPAIR_BUDGET, bounds.session_wall_clock_s * REPAIR_BUDGET


def _install(
    setup: RawSetup,
    worktree: Path,
    sdir: Path,
    temp: Path | None,
    *,
    own_temp: Path | None = None,
) -> dict[str, Any]:
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
        # The session's own directory, which holds its login, stream, settings and records: no
        # tool of the raw agent reads it, as no role session's reads the run's. A raw session
        # has no run around it, so its own directory is the whole of what there is to name,
        # and the installer refuses a raw-agent session that names none.
        "--sessions-root",
        str(sdir),
        # The harness checkout is protected from the raw agent and its shell reads denied:
        # what it would find there (the knowledge, the rubrics) is the harness's help.
        *harness_protection(),
        *(arg for root in setup.held_out for arg in ("--held-out", root)),
        *(arg for root in setup.withheld_reads for arg in ("--review-material", root)),
        *(arg for root in setup.write_protected for arg in ("--protect", root)),
        *(arg for place in setup.writable_within for arg in ("--protect-except", place)),
        # The harness run's tool environment: read and run by the session's commands, written
        # by none, as a role session's.
        *(
            arg
            for root in (setup.tool_environment.roots if setup.tool_environment else ())
            for arg in ("--tool-environment-root", root)
        ),
        *(["--os-layer-temp", str(temp)] if temp is not None else []),
        # The raw agent's tool servers: their admitted tools join its closed list. None
        # without the OS layer, which alone contains them.
        *(arg for name in offered_servers(setup, temp) for arg in ("--tool-server", name)),
        # Without the layer the session still keeps its temporary files in a directory of its
        # own, never in the one every session of the user shares.
        *(["--temp", str(own_temp)] if temp is None and own_temp is not None else []),
        # The session is spawned held (the dispatcher's spawn), which exports its pid as the
        # survivor reaper's canary; the installer refuses a reaped session that does not say so.
        "--spawns-with-canary",
        *(
            ["--os-layer-network", setup.network]
            if temp is not None and setup.network != "open"
            else []
        ),
        # The named interpreter, and the programs of the tool environment, are linked in the
        # session's own directory, which the OS layer keeps from shell commands; it is opened.
        *(
            ["--os-layer-readable", str(sdir / "bin")]
            if temp is not None
            and (setup.role_python is not None or setup.tool_environment is not None)
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


def run_session(
    prompt: str,
    setup: RawSetup,
    work: Path,
    *,
    cap: int,
    files: Mapping[str, bytes] | None = None,
    check: Checkpoint | None = None,
) -> dict[str, Any]:
    """One session on ``prompt``, as the raw arm runs one, in the new directory ``work``.

    The session works in ``work/worktree``; what it leaves there is the caller's to take.
    ``files`` are written into the worktree, by plain name, before the session starts: a
    session given material to read finds it there, never in its prompt, which any process
    of the same user can list. ``check`` is asked at each reading of the stream, with the
    tokens spent so far, and the session is stopped for any reason it returns; that
    reason is then the record's ``end``.
    Returns the session's record: how it ended, what it spent, and whether a held-out
    canary showed in its stream.

    Raises:
        RawArmError: ``work`` exists, the session could not be set up, its credential could
            not be removed, or its tool environment is not the recorded one before it or
            changed while it ran.
    """
    if work.exists():
        msg = f"{work} exists; each session gets a directory of its own"
        raise RawArmError(msg, work=str(work))
    # Before anything of the session exists: a refusal here leaves nothing behind.
    launches = server_launches_for(setup)
    at_start = hold_tools(setup, work)
    worktree, sdir = work / "worktree", work / "session"
    # Private from the start: the session's credential is written beneath ``sdir``.
    work.mkdir(mode=0o700, parents=True)
    worktree.mkdir(mode=0o700)
    sdir.mkdir(mode=0o700)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True, capture_output=True)
    for name, data in (files or {}).items():
        if "/" in name or name.startswith("."):
            msg = f"{name!r} is not a plain file name for the worktree"
            raise RawArmError(msg, name=name)
        (worktree / name).write_bytes(data)
    session_id = str(uuid.uuid4())
    # As a role session's: a temporary directory of its own, beneath the one parent no other
    # session reads or writes; where the OS layer runs, it is the layer's too.
    try:
        own_temp = make_session_temp()
    except OSError as exc:
        msg = "no temporary directory of the session's own could be made, so none is started"
        raise RawArmError(msg, error=str(exc)) from exc
    temp = own_temp if isinstance(setup.os_layer, Present) else None
    try:
        record = _run(
            prompt,
            setup,
            work,
            worktree,
            sdir,
            session_id,
            temp,
            cap,
            check,
            own_temp=own_temp,
            launches=launches,
        )
    finally:
        shutil.rmtree(own_temp, ignore_errors=True)
    if setup.tool_environment is not None and at_start is not None:
        # Scanned once more: a change now was made while the session ran, by a write no layer
        # refused, and what the session made was not made on the recorded environment.
        changed = changed_while_running(setup.tool_environment, at_start)
        if changed is not None:
            raise RawArmError(changed, work=str(work))
    return record


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
    check: Checkpoint | None = None,
    *,
    own_temp: Path | None = None,
    launches: tuple[ServerLaunch, ...] = (),
) -> dict[str, Any]:
    stdout, stderr = sdir / "stdout.jsonl", sdir / "stderr.txt"
    # One boundary from the first write of the credential to its removal: whatever ends
    # the session (an error, a refusal, the clock, the cap, a kill), the cleanup runs.
    try:
        ended, watch, seconds, after = _session(
            prompt,
            setup,
            worktree,
            sdir,
            session_id,
            temp,
            cap,
            check,
            own_temp=own_temp,
            launches=launches,
        )
    finally:
        _clean(work, sdir, setup.credential.secret, (stdout, stderr))
    captured = read_captured(stdout)
    end = watch.end or ("wall_clock" if ended.timed_out else "ended")
    return {
        "session_id": session_id,
        "end": end,
        "exit_code": ended.exit_code,
        "left_running": list(ended.left_running),
        "wall_clock_s": seconds,
        "tokens": sum(m.usage.total() for m in captured.usage),
        "cap": cap,
        "answered_by": sorted(captured.answered),
        "held_out_seen": held_out_seen(stdout, setup.held_out_canaries),
        "watch_failure": watch.failure,
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
    checkpoint: Checkpoint | None = None,
    *,
    own_temp: Path | None = None,
    launches: tuple[ServerLaunch, ...] = (),
) -> tuple[SessionEnd, BudgetWatch, float, dict[str, Any]]:
    """Install, spawn, watch and end the raw session; the credential's removal is the caller's."""
    # As a role session's: what the runtime makes is made first, so it is in the record.
    (sdir / "home").mkdir(mode=0o700, exist_ok=True)
    runtime_paths(worktree, sdir / "home")
    # And what this pin's runtime makes in the work area's own git directory, per platform.
    runtime_git_paths(worktree / ".git", setup.claude_version)
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
    recorded_tools = setup.tool_environment
    wired: dict[str, str] = {}
    if recorded_tools is not None:
        # Before the installation, so the OS layer's rules name the directory of the session's
        # programs as it will stand, as a role session's are.
        tools_temp = own_temp if own_temp is not None else temp
        if tools_temp is None:
            msg = "a session on a tool environment needs a temporary directory of its own"
            raise RawArmError(msg)
        try:
            wired = wire_session(
                recorded_tools, bin_dir=sdir / "bin", temp=tools_temp, taken=tuple(env)
            )
        except InvocationError as exc:
            raise RawArmError(str(exc)) from exc
    installed = _install(setup, worktree, sdir, temp, own_temp=own_temp)
    env.update(installed["spawn_env"])
    if recorded_tools is not None:
        try:
            # The environment's interpreter is the session's ``python3``, its programs first.
            env = session_environment(env, wired, sdir / "bin")
            # Its scripts' records name the environment's code by the run's roots and digest.
            env = series_environment(env, recorded_tools)
        except InvocationError as exc:
            raise RawArmError(str(exc)) from exc
    elif setup.role_python is not None:
        env["PATH"] = f"{session_bin(sdir, setup.role_python)}:{env['PATH']}"
    tool_servers, contained_by = contained_servers_for(
        setup,
        launches,
        Path(installed["config"]),
        sdir,
        own_temp if own_temp is not None else temp,
        env,
    )
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
        tool_servers=tool_servers,
        wrappers=contained_by,
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
        watch = BudgetWatch(stdout, cap, process, started, checkpoint)
        watch.start()
        try:
            ended = await_session(process, started, wall_clock)
        finally:
            watch.stop()
    seconds = time.monotonic() - began
    require_stopped(watch)
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


def canaries_sha256(canaries: Iterable[str]) -> str:
    """The digest a record holds for a list of held-out canaries: it names none of them."""
    return hashlib.sha256("\n".join(sorted(canaries)).encode()).hexdigest()


def pins(task: Task, setup: RawSetup) -> dict[str, Any]:
    """Everything the raw arm is held equal to the harness arm on, as it ran.

    The tool list is not here: the comparison reads it from the session's generated
    configuration, the list the session was actually given.
    """
    max_turns, wall_clock = raw_bounds(setup.bounds)
    return {
        # No raw session is given an advisor; a field to give one records it here.
        "advisor": None,
        "auth": setup.credential.mode,
        # As the session ran them: the binary's retries as given, the turns and the wall
        # clock a role session's times the repair budget.
        "bounds": {
            "binary_max_retries": setup.bounds.binary_max_retries,
            "infra_retry_delays_s": list(setup.bounds.infra_retry_delays_s),
            "session_max_turns": max_turns,
            "session_wall_clock_s": wall_clock,
        },
        "endpoint": endpoint_of(setup.base_url),
        "held_out": sorted(setup.held_out),
        # The canaries its stream was scanned for, which the harness run's must equal.
        "held_out_canaries_sha256": canaries_sha256(setup.held_out_canaries),
        "model": setup.model,
        "claude_version": setup.claude_version,
        "effort": setup.effort,
        "max_output_tokens": setup.max_output_tokens,
        "thinking_display": setup.thinking_display,
        "role_python": None if setup.role_python is None else setup.role_python.model_dump(),
        "network": setup.network,
        "os_layer": setup.os_layer.model_dump(),
        # The tools it computed and built with, and the servers it was offered from them, as
        # the harness run recorded both; whether its settings denied the binary's search tool,
        # read from the deny lists it was installed from, as a run records it.
        "tool_environment": (
            None
            if setup.tool_environment is None
            else setup.tool_environment.model_dump(mode="json")
        ),
        "tool_servers": (
            None if setup.tool_servers is None else setup.tool_servers.model_dump(mode="json")
        ),
        "tool_search": session_tool_search(),
        "brief_sha256": hashlib.sha256(task.brief.encode()).hexdigest(),
        "answer": task.answer.model_dump(),
    }
