"""A run ended mid-session leaves no session's credential file in its run directory.

A session's credential is a file in its own directory, inside the run directory, while it runs
(``credentials``); the session's end removes it. A run process ended by a stop signal used to
end at once: its session, leading a process group of its own, ran on, and the file stayed in
the run directory, which is evidence that gets copied.

So, under :func:`on_stop_signals`, a stop signal (SIGTERM, an interrupt, a hang-up) does what a
kill does, every record of the run left as it stood for the resume, and before that: every
credential file this process put on disk, or a session of its may hold, is removed; every
session it spawned and has not reaped is stopped with its group (SIGTERM, :data:`GRACE_S`,
SIGKILL, with every process seen in its tree before the stop), and waited for, within
:data:`REAP_S`, until it and its group are gone; and the files are removed once more, since a
session may write its own while it runs. The process then ends by that signal, after one line
saying how many sessions are gone and how many still live; a session still alive after the wait
is named on it, and the process ends with :data:`EXIT_SESSIONS_ALIVE` instead, since its files
may be written again. A signal its launcher set to be ignored stays ignored.

A run killed outright leaves the files; the next command on the run removes the file of every
session nothing runs as any more before anything else (:func:`remove_left_credentials`), its
reviewers' too, and leaves a running one's alone: the leftovers' stop ends it and removes its
file, as before. It does so only while no other command drives the run (:func:`driving`).

Where a credential may lie after a kill is found by one function (:func:`credential_places`),
every kind of place a writer names (``credentials.CredentialPlace``) by the place functions the
writers write through: a role session's directory, a review session's (a module's review and the
plan's), each call directory of a decomposition (round one's, its retry's, each later round's and
its retry's) and a raw trial's place. Every clean-up after a kill clears what it finds: the next
command on a run or a decomposition's directory, the restart of a round, the raw round's resume.
A decomposition's call is named on no command line by a session id: it is found running by the
settings file it is started with, and a call its killed ``decompose`` left running is stopped
first, since nothing will ever read what it answers.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol

from physgate.orchestrator.credentials import (
    CREDENTIAL_PLACES,
    KEY_FILE,
    KEY_HELPER,
    LOGIN_FILE,
    CredentialPlace,
    hold_login,
    remove_held_secrets,
    remove_secrets,
)
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.processes import (
    Proc,
    processes_naming,
    running_session_ids,
    signal_if_same,
    started_at,
    stop_tree,
    tree,
)

#: The signals that end a run: a supervisor's SIGTERM, an interrupt, a terminal's hang-up.
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
#: How long the run's sessions have to end on SIGTERM before SIGKILL.
GRACE_S = 5.0
_WAIT_S = 0.05
#: How long the killed sessions, and what was left in their groups, are waited for at most.
REAP_S = 2.0
#: The exit status of a stop that left a session alive after :data:`REAP_S`: a clean stop ends
#: by its signal, so a supervisor can tell the two apart.
EXIT_SESSIONS_ALIVE = 76
#: What a stop line says of the credential files when every session is gone.
REMOVED = "removed"
#: What it says when a session still lives, which may write its login file again.
#: What it says when a file could not be removed, with its count in ``removal_failures``.
NOT_ALL_REMOVED = (
    "some credential files could not be removed; the next command on this run tries again"
)
MAY_BE_WRITTEN_AGAIN = (
    "a session still alive may write its login file again; the next command on this run "
    "removes the files of every session no process runs as"
)

_Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None


class _Child(Protocol):
    """What the stop reads of a spawned session: a ``subprocess.Popen``'s pid and returncode."""

    pid: int
    returncode: int | None


#: Every session this process spawned, until it is reaped.
_live: list[_Child] = []


def track(process: _Child, login_dir: Path | None) -> None:
    """Hold a just-spawned session for a stop signal: its process, and its login file.

    ``login_dir`` is the session's configuration directory, where the binary keeps its login
    file; the files the harness writes are held as it writes them (``credentials``).
    """
    if login_dir is not None:
        hold_login(login_dir)
    _live[:] = [p for p in _live if p.returncode is None]
    _live.append(process)


def _running(pid: int) -> bool:
    """Whether a session this process has not reaped still runs; ended, it waits as a zombie.

    Unreaped, its pid stays the id of its process group. A table that cannot be read says it
    runs: nothing is concluded from no answer.
    """
    try:
        return started_at(pid) is not None
    except OSError:
        return True


def _reaped(pid: int) -> bool:
    """Reap ``pid`` if it has ended; whether it is reaped now (by this call or before it)."""
    try:
        done, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return done == pid


def _group_left(pgid: int) -> bool:
    """Whether any process is still in the group ``pgid`` (a signal 0 only asks)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


@dataclass(frozen=True)
class Ended:
    """How a stop's end of the sessions went: how many it stopped, and each survivor's pid."""

    tried: int
    survivors: tuple[int, ...]


def end_live_sessions(grace_s: float = GRACE_S) -> Ended:
    """Stop every session this process spawned and has not reaped; say which are still alive.

    Each one's tree is collected while it runs, then its group gets SIGTERM. Until the grace
    ends, or every session has ended, none is reaped: unreaped, a session's pid stays its
    group's id, so its group can be signalled by that id whatever is left in it, a process the
    session started as it stopped included. Then whatever is left of each tree gets SIGKILL, and
    each whole group too; each session is reaped and its group waited for until it is empty, all
    within :data:`REAP_S`, so nothing removed after this returns is written again by a process
    that was still dying. A session not reaped by then, or whose group is not yet empty, is a
    survivor, named by its pid. Reaped with ``os.waitpid``, never ``Popen.wait``: the signal may
    have landed inside the run's own wait on the same process, which holds that process's lock.
    """
    live = [p for p in _live if p.returncode is None]
    trees: list[list[Proc]] = []
    for process in live:
        try:
            trees.append(tree(process.pid))
        except OSError:
            trees.append([])
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGTERM)
    ended: set[int] = set()
    deadline = time.monotonic() + grace_s
    while len(ended) < len(live) and time.monotonic() < deadline:
        ended.update(p.pid for p in live if p.pid not in ended and not _running(p.pid))
        time.sleep(_WAIT_S)
    for process, collected in zip(live, trees, strict=True):
        for proc in collected[1:]:
            with contextlib.suppress(OSError):
                signal_if_same(proc, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
    gone = time.monotonic() + REAP_S
    survivors: list[int] = []
    for process in live:
        reaped = _reaped(process.pid)
        while not reaped and time.monotonic() < gone:
            time.sleep(_WAIT_S)
            reaped = _reaped(process.pid)
        left = _group_left(process.pid)
        while left and time.monotonic() < gone:
            time.sleep(_WAIT_S)
            left = _group_left(process.pid)
        if not reaped or left:
            survivors.append(process.pid)
    _live.clear()
    return Ended(tried=len(live), survivors=tuple(survivors))


def _on_stop(signum: int, _frame: FrameType | None) -> None:
    # Nothing here returns to the run. A second signal runs this again, inside, to the same end.
    remove_held_secrets()
    ended = end_live_sessions()
    failed = remove_held_secrets()
    alive = len(ended.survivors)
    said: dict[str, object] = {
        "stopped_by": signal.Signals(signum).name,
        "sessions_gone": ended.tried - alive,
        "sessions_alive": alive,
        "credentials": MAY_BE_WRITTEN_AGAIN if alive else NOT_ALL_REMOVED if failed else REMOVED,
    }
    if failed:
        said["removal_failures"] = failed
    if alive:
        said["survivors"] = list(ended.survivors)
    # Unbuffered: the signal may have landed inside a write of the run's own to stderr.
    with contextlib.suppress(OSError):
        os.write(2, (json.dumps(said, sort_keys=True) + "\n").encode())
    if alive:
        os._exit(EXIT_SESSIONS_ALIVE)
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    os._exit(128 + signum)  # only if the signal was not delivered: the run ends either way


@contextmanager
def on_stop_signals() -> Iterator[None]:
    """Inside, a stop signal ends this process's sessions and removes their credentials first.

    Installed from the main thread only, where Python runs a signal's handler; a signal the
    launcher set to be ignored is left so. What each signal had is put back on the way out.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    found: dict[signal.Signals, _Handler] = {}
    for signum in STOP_SIGNALS:
        handler = signal.getsignal(signum)
        if handler == signal.SIG_IGN:
            continue
        found[signum] = handler
        signal.signal(signum, _on_stop)
    try:
        yield
    finally:
        for each, before in found.items():
            signal.signal(each, before)


_said_unlocked = False


def _say_unlocked() -> None:
    """Say once, on stderr, that this run goes on without the run directory's lock."""
    global _said_unlocked
    if _said_unlocked:
        return
    _said_unlocked = True
    with contextlib.suppress(OSError):
        os.write(
            2,
            b"physgate: this filesystem refuses file locks, so the run goes on without one; "
            b"another command on this run may then remove a login file it has just written\n",
        )


@contextmanager
def driving(run_dir: Path) -> Iterator[None]:
    """Inside, this process holds the run directory's lock, shared, as every driving command does.

    No other command's sweep (:func:`remove_left_credentials`) removes a file while it is held,
    so a session's login file written before its spawn, which no process names yet, is never
    taken for a gone session's. The descriptor is this process's own: a session it spawns does
    not inherit it. A run directory that cannot be opened, or a filesystem that refuses the
    lock, leaves the run unlocked (the refusal said once on stderr); a sweep that cannot take
    its exclusive lock removes nothing.
    """
    try:
        fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        yield
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
        except OSError:
            _say_unlocked()
        yield
    finally:
        os.close(fd)


@dataclass(frozen=True)
class CredentialSite:
    """One place a session's credential may lie in after a kill, and how its session is named.

    ``state`` and ``config`` are the two directories a session's credential files go in
    (:func:`~physgate.orchestrator.credentials.remove_secrets`). ``session_id`` is the id its
    process names on its command line; a decomposition's call names its ``settings`` file instead,
    and a raw place whose process record cannot be read names neither, and is cleared only by its
    own round (which knows its session has ended).
    """

    place: CredentialPlace
    state: Path
    config: Path
    session_id: str | None = None
    settings: Path | None = None

    @classmethod
    def of(
        cls, place: CredentialPlace, sdir: Path, session_id: str | None = None
    ) -> CredentialSite:
        """The site whose session's own directory is ``sdir``."""
        return cls(place, sdir / "state", sdir / "config", session_id)


def _role_sessions(root: Path, _review_root: Path | None) -> list[CredentialSite]:
    try:
        # A link at a session's name is refused by the removal itself, never followed.
        found = sorted(p for p in (root / "sessions").iterdir() if p.is_dir())
    except OSError:
        return []
    return [CredentialSite.of("role_session", p, p.name) for p in found]


def _review_places(root: Path, review_root: Path | None) -> list[CredentialSite]:
    # Here, not at the top: decomposition_review imports dispatch, which imports this module.
    from physgate.orchestrator.decomposition_review import ReviewRecordError, review_record

    found = [
        CredentialSite.of("review_session", sdir, sid)
        for sid, sdir in (_review_sessions(root, review_root) if review_root is not None else [])
    ]
    # The plan's review, named by the record its decomposition keeps of it: before the opening no
    # run record names the run its session's owner file names.
    try:
        record = review_record(root)
    except ReviewRecordError:
        record = None
    if record is not None:
        found.append(CredentialSite.of("review_session", record.session_dir, record.session_id))
    return found


def _plan_calls(root: Path, _review_root: Path | None) -> list[CredentialSite]:
    """Each call directory of the decomposition in ``root``, as its rounds name them."""
    from physgate.orchestrator.design_rounds import retry_dir, round_dir

    top = round_dir(root, 1)
    if top.is_symlink() or not top.is_dir():
        return []
    rounds = [1]
    for entry in sorted(os.listdir(top)):
        name, _, number = entry.partition("-")
        if name == "round" and number.isdigit() and int(number) > 1:
            rounds.append(int(number))
    calls = [where for k in rounds for where in (round_dir(root, k), retry_dir(root, k))]
    return [
        CredentialSite("plan_call", w / "state", w / "config", settings=w / "settings.json")
        for w in calls
    ]


def _raw_place(root: Path, _review_root: Path | None) -> list[CredentialSite]:
    """A raw trial's place, ``root`` being the trial's directory."""
    from physgate.evaluation.tiers.store import PLACE

    sdir = root / PLACE / "session"
    if not sdir.is_dir():
        return []
    try:
        record = json.loads((sdir / "process.json").read_text())
        session_id = record["session_id"] if isinstance(record["session_id"], str) else None
    except (OSError, ValueError, KeyError, TypeError):
        session_id = None
    return [CredentialSite.of("raw_session", sdir, session_id)]


#: How each kind of place is found beneath a root: by the same place functions its writer writes
#: through. A row holds this to every kind a writer names.
_FINDERS: dict[CredentialPlace, Callable[[Path, Path | None], list[CredentialSite]]] = {
    "role_session": _role_sessions,
    "review_session": _review_places,
    "plan_call": _plan_calls,
    "raw_session": _raw_place,
}


def credential_places(root: Path, review_root: Path | None = None) -> tuple[CredentialSite, ...]:
    """Every place a session's credential may lie in after a kill, of every kind, beneath ``root``.

    ``root`` is a run's directory (a decomposition's included) or a raw trial's; given the run's
    ``review_root``, this run's review sessions beneath it are found too. Nothing is read but
    names and the orchestrator's own records of where a session ran.
    """
    found: dict[tuple[Path, Path], CredentialSite] = {}
    for place in CREDENTIAL_PLACES:
        for site in _FINDERS[place](root, review_root):
            # A plan's review is named both by its record and, after the opening, by its owner.
            found.setdefault((site.state, site.config), site)
    return tuple(found.values())


def _review_sessions(run_dir: Path, review_root: Path) -> list[tuple[str, Path]]:
    """This run's reviewer sessions beneath ``review_root``, with their ids, by owner file."""
    # Here, not at the top: dispatch imports this module.
    from physgate.orchestrator.dispatch import OWNER_NAME
    from physgate.reviewers.places import SESSION_DIRNAME

    try:
        run_id = json.loads((run_dir / "run.json").read_text())["run_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    found: list[tuple[str, Path]] = []
    for owner in sorted(review_root.glob(f"*/{SESSION_DIRNAME}/{OWNER_NAME}")):
        try:
            if json.loads(owner.read_text()).get("run_id") == run_id:
                found.append((owner.parent.parent.name, owner.parent))
        except (OSError, ValueError, AttributeError):
            continue
    return found


def remove_left_credentials(run_dir: Path, review_root: Path | None = None) -> tuple[str, ...]:
    """Remove the credential files of every session of the run no process runs as now.

    For the first step of a command on a run that may have been killed: a session nothing
    names by its id on a command line is gone, and needs its credential no more. A running one
    keeps its files. The run's own sessions are swept, and, given the review root, this run's
    reviewer sessions beneath it. Only while no other process drives the run (:func:`driving`):
    a run being driven may have written a session's login file before spawning it. Without the
    lock, or a process listing, nothing is removed here, and a directory that cannot be reached
    without a link is left; the leftovers' stop, after its own stop, removes or refuses as
    before. Returns the ids of the sessions it cleared.
    """
    try:
        lock = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return ()
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return ()
        return _sweep(run_dir, review_root)
    finally:
        os.close(lock)


def _sweep(run_dir: Path, review_root: Path | None) -> tuple[str, ...]:
    sites = credential_places(run_dir, review_root)
    try:
        running = running_session_ids()
    except OSError:
        return ()
    removed: list[str] = []
    for site in sites:
        if site.settings is not None:
            if not _no_planner_runs(site.settings):
                continue
            held = any(
                os.path.lexists(d / n)
                for d, n in (
                    (site.config, LOGIN_FILE),
                    (site.state, KEY_FILE),
                    (site.state, KEY_HELPER),
                )
            )
            try:
                remove_secrets(site.state, site.config)
            except (OSError, InvocationError):
                continue
            if held:
                removed.append(os.path.relpath(site.config.parent, run_dir))
            continue
        if site.session_id is None or site.session_id in running:
            continue
        try:
            remove_secrets(site.state, site.config)
        except (OSError, InvocationError):
            continue
        removed.append(site.session_id)
    return tuple(removed)


def _no_planner_runs(settings: Path) -> bool:
    """Whether no decomposition's call started with ``settings`` runs now; one that does is stopped.

    Only while this process holds the run's lock exclusively: no ``decompose`` drives the run, so
    a call still running was left by one killed outright, and its answer is read by nothing. A
    process table that cannot be read, or a call still alive after its stop, is no answer.
    """
    try:
        for pid in processes_naming(str(settings)):
            stop_tree(pid, started_at(pid))
        return not processes_naming(str(settings))
    except OSError:
        return False
