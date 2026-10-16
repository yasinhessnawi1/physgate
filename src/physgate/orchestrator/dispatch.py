"""The dispatcher: one attempt in a fresh Claude Code session, under the hook layer.

For every attempt: check the binary is still the version the run recorded;
open the subtask's worktree; give the session a directory of its own, outside
the worktree, holding its scratch home and configuration directory, the hook
state and the captured stream; generate its settings with the hook layer's
installer, run from the read-only installation; spawn it exactly as those
settings say; wait within the run's wall clock; stop everything it left running and
run the sentinel's last check once more, before any git call on the attempt; then read
what it left.

What the orchestrator reads afterwards is its own record and the hook layer's,
never the session's say-so: the stream it captured itself (never the
transcript in the session's writable configuration directory), the hook
layer's reading records for whether the required reading was completed, and
the hook log for a node-file halt and for journal appends. The credential
reaches the session through a file, never its environment: an API key through a
helper script the settings name, a subscription token as the binary's login file
in the session's own configuration directory. Either is removed when the session
ends and redacted from the captured stream before anything reads it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import stat
import subprocess
import sysconfig
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
from physgate.hooks.sentinel import _frozen_experiment_paths
from physgate.hooks.settings import CONFIG_NAME, SETTINGS_NAME
from physgate.hooks.snapshot import Signature, file_digest, signature
from physgate.hooks.state import LOG_NAME
from physgate.knowledge import loader
from physgate.knowledge.promote import KNOWLEDGE_ROOT, PROMOTIONS_NAME, canaries
from physgate.orchestrator.accounting import require_matching_totals
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.credentials import (
    REDACTED_TEXT,
    Credential,
    remove_secrets,
    write_key_helper,
    write_login,
)
from physgate.orchestrator.decompose import binary_version, read_stream
from physgate.orchestrator.exceptions import AccountingError, InvocationError
from physgate.orchestrator.git import common_dir, named_from
from physgate.orchestrator.install import InstallFacts, build_record_path, install_facts
from physgate.orchestrator.invocation import isolated_env, role_argv
from physgate.orchestrator.managed import drift, policy_limits_digest
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionKind, SessionReport, SessionRequest
from physgate.orchestrator.processes import (
    Proc,
    ProcessTableError,
    is_session,
    started_at,
    stop_tree,
)
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import DECISIONS_NAME
from physgate.orchestrator.role_python import PROBE, require_same, session_bin
from physgate.orchestrator.run_config import RunConfig, harness_root
from physgate.orchestrator.trajectory import Seal, forged_tail, seal, through_first_result
from physgate.reviewers.ending import SWEEPS, SessionEnd, await_session, group, stop_all
from physgate.reviewers.packet import issued_spec_sha256
from physgate.reviewers.places import SESSION_DIRNAME

REDACTED = REDACTED_TEXT.encode()

#: The record a review's session directory gets first, before anything that holds a
#: credential: which run it belongs to, so that run's resume finds it.
OWNER_NAME = "owner.json"


#: The run's own records, in the run directory. The session's working directory is
#: one level below it, so none of these contains the worktree.
RUN_RECORDS = ("events.jsonl", "ledger.jsonl", "run.json", "queue.jsonl", "decomposition")


def run_protected_roots(run: RunGit) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """What a role session's tools may not write, beyond what the hook layer protects itself.

    Returns the roots the sentinel puts back if they change, and the roots it only
    refuses writes to, because the runtime writes them while the session runs.

    - Put back: the run's records (the event log, the task ledger, the run
      configuration, the approval queue, the decomposition call's files), the
      orchestrator's integration worktree, the target repository's whole common git
      directory, and the ``.git`` pointer file of every worktree it has. The
      orchestrator writes none of them while a session runs: dispatch is serial, and
      its own git commands start no maintenance that outlives them.
    - Refused only: every session's directory, which holds each session's
      captured stream (the trajectory the reviewer and the token account read)
      and its process record, written by the runtime and the spawner during the
      session; and the approval queue's decisions file, which a person appends to
      with ``physgate queue resolve`` whenever they decide, sessions running or not.

    The common git directory is read through the check every write runs
    (:func:`common_dir`), so a repository whose git directory does not verify gives no
    protected set and no session is installed.
    """
    common = common_dir(run.repo)
    # Where git keeps the run branch's loose ref, for any repository layout. A ref
    # moved in packed-refs is seen by the loop's check of the branch instead.
    ref = common / "refs" / "heads" / run.run_branch
    reverted = (*(run.run_dir / name for name in RUN_RECORDS), run.integration, ref)
    reverted = (*reverted, *git_config_roots(common), *git_dir_roots(run.repo, common))
    return reverted, (run.run_dir / "sessions", run.run_dir / DECISIONS_NAME)


def session_protected_roots(
    run: RunGit, store_root: Path, worktree: Path, install_root: Path
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Everything a role session in ``worktree`` is given as protected roots by the dispatcher.

    The run's roots (:func:`run_protected_roots`), and three more of the session's own:

    - the installation's build record, which lives beside the installation, outside the
      root the hook layer protects: a session that rewrote it would make the next run
      refuse, or, with the manifest, pass;
    - this session's worktree's ``.git`` pointer file, which names the admin directory the
      orchestrator's commit runs against (the orchestrator also verifies it before every
      git call);
    - the graph store's own git directory. The store's directory is a protected root the
      hook layer watches only for its journal and node files, but the orchestrator commits
      the store in its own repository after an attempt is applied, and that commit reads the
      repository's config and ``info/attributes``, where a filter would run. The orchestrator
      writes it only between sessions (dispatch is serial, and the store is committed after
      the session has ended), so the whole directory is put back.

    Returns the roots put back, and the roots only refused.
    """
    reverted, refused = run_protected_roots(run)
    reverted = (
        *reverted,
        build_record_path(install_root),
        worktree / ".git",
        Path(store_root) / ".git",
    )
    return reverted, refused


#: The files and directories in a repository's common git directory through which a write
#: makes a later git command run a program: its configuration (a diff, merge or filter driver,
#: or the file-system monitor), the attributes and exclude files under ``info/``, the
#: repository hooks, and a submodule's own git directory under ``modules/`` (its config and
#: hooks). Each lies inside the common git directory, which is protected whole
#: (:func:`git_dir_roots`); they stay named on their own as well.
GIT_CONFIG_NAMES = ("config", "config.worktree", "info", "hooks", "modules")


def git_config_roots(common_git_dir: Path) -> tuple[Path, ...]:
    """The common git directory's exec-config surface, as protected roots."""
    return tuple(common_git_dir / name for name in GIT_CONFIG_NAMES)


def git_dir_roots(repo: Path, common_git_dir: Path) -> tuple[Path, ...]:
    """The whole common git directory, and the ``.git`` pointer file of each of its worktrees.

    A role session runs no git at all: the orchestrator stages, commits and merges its work.
    So nothing in the git directory is the session's to write, and every file in it changes
    what a later git command of the orchestrator's does or reads:

    - ``objects/``: git trusts an object file's bytes to be what its name says and does not
      check them again, so a byte changed there changes a commit, a tree or a file the
      orchestrator reads; ``objects/info/`` holds the alternates and the commit graph;
    - ``refs/``, ``packed-refs``, ``HEAD`` and ``shallow``: where every branch points, and which
      commits git treats as having no parents;
    - ``index`` and ``worktrees/``: each linked worktree's admin directory, whose ``commondir``
      names the directory git takes the configuration from and whose ``gitdir``, ``HEAD`` and
      ``index`` are that worktree's state;
    - everything else git keeps there, named here or not.

    All of it is put back if it changes, which holds existing object files, packs and their
    indexes, the multi-pack index and the commit graph byte for byte to what they were when
    the session started; anything new is moved aside. Each worktree's ``.git`` pointer file,
    which names its admin directory, is put back too; the pointers are found from the admin
    directories' own ``gitdir`` files, read from the filesystem as git reads them (one that
    git could read another way refuses the set). A repository that is itself a
    linked worktree has a pointer of its own.
    """
    roots = [common_git_dir]
    pointer = repo / ".git"
    if pointer.is_file():
        roots.append(pointer)
    admins = common_git_dir / "worktrees"
    for gitdir in sorted(admins.glob("*/gitdir")) if admins.is_dir() else ():
        # Read as git reads it; one git would read another way refuses the whole set, so no
        # session is installed on a protected set built from a guess.
        pointer = named_from(gitdir.parent, "gitdir")
        if pointer.name == ".git":
            roots.append(pointer)
    return tuple(roots)


@dataclass(frozen=True)
class Captured:
    """A session's captured stream, as read once: sealed, checked, parsed from the same bytes."""

    seal: Seal
    tampered: str | None
    # The binary's result object: an untyped boundary.
    result: dict[str, Any] | None
    usage: tuple[MessageUsage, ...]
    answered: frozenset[str]


def read_captured(stream: Path) -> Captured:
    """Read a session's stream once: seal it, find a forged tail, parse what the runtime wrote.

    One read path for every reader, the session that ended under its orchestrator
    and the leftover a resume finds. A stream with a tail after the runtime's
    result is parsed only up to that result; the tail is reported, never read.
    """
    data = stream.read_bytes() if stream.exists() else b""
    text = data.decode(errors="replace")
    tampered = forged_tail(text)
    if tampered is not None:
        text = through_first_result(text)
    result, usage, answered = read_stream(text)
    return Captured(
        seal=seal(data), tampered=tampered, result=result, usage=usage, answered=answered
    )


def review_material_seen(stream: Path, live: frozenset[str]) -> str | None:
    """The first canary of reviewer material in a session's stream, if any is there.

    Detection, not prevention: the hook layer refuses every read of the reviewer
    tree it can judge, and a read whose path the session builds while its command
    runs is judged by nothing. Such a read that reaches a rubric shows the rubric's
    canary in the session's own stream, as a tool's output. A read that never shows
    the canary verbatim (a part of the file, or the file transformed) is not found.
    """
    if not live or not stream.exists():
        return None
    data = stream.read_bytes()
    return next((c for c in sorted(live) if c.encode() in data), None)


def role_prompt(request: SessionRequest) -> str:
    """What a role session is told: a template, with the repair instruction if any."""
    text = (
        f"You implement subtask {request.subtask_id} in the {request.assigned_role} role.\n\n"
        f"Your specification is {request.spec_path}; read it in full first. Change files only "
        f"under {request.module_dir}/. To propose a node of the design graph, write it whole as "
        "JSON to .physgate/proposals/<node id>.json; never write the graph store itself. Stop "
        "when the specification is met.\n"
    )
    if request.repair_instruction:
        text += f"\n{request.repair_instruction}\n"
    return text


@dataclass(frozen=True)
class _Input:
    """The one field the reading check reads from a hook's input: the session id."""

    session_id: str
    cwd: str = "/"
    hook_event_name: str = "Stop"
    tool_name: str | None = None
    tool_input: dict[str, object] | None = None
    tool_response: object = None
    agent_id: str | None = None
    error: str | None = None


def read_in_full(config_path: Path, session_id: str) -> bool:
    """The hook layer's own answer: is every required file read in full, as it is now?"""
    config = SessionConfig.model_validate_json(config_path.read_bytes())
    return not outstanding(config, _Input(session_id=session_id))


@dataclass(frozen=True)
class EndCheck:
    """The settings' SessionEnd command, which runs the sentinel's last check, and its timeout."""

    argv: tuple[str, ...]
    timeout_s: float


def session_end_command(settings: Path) -> EndCheck:
    """The SessionEnd hook command the installer wrote into a session's settings.

    Read before the session is spawned, so it is the installer's command and nothing a
    session's process wrote since.
    """
    try:
        groups = json.loads(settings.read_bytes())["hooks"]["SessionEnd"]
        (group,) = groups
        (hook,) = group["hooks"]
        return EndCheck(tuple(shlex.split(hook["command"])), float(hook["timeout"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = "the session's settings name no single SessionEnd check"
        raise InvocationError(msg, settings=str(settings), error=repr(exc)) from exc


#: What a sentinel check records when it could not do its work: the code the hooks run from
#: changed, a protected path could not be put back, or the hook reached no decision.
_FAILED_CHECKS = ("halt", "unrestorable", "error")


def sentinel_refusal(exit_code: int | None, records: list[dict[str, Any]]) -> str | None:
    """Why the attempt must go no further after the sentinel's check ran again, or ``None``.

    ``records`` are the hook log's lines that check wrote. A change it put back is a refusal
    of the check's own (exit 2) that needs nothing more; a node file or a journal append it
    saw is read from the hook log as one seen during the session is (:meth:`_hook_log`), and
    a sentinel already halted during the session refuses as it did then. A check that could
    not compare or put back, or that left no record of a refusal, is not a check.
    """
    decisions = [str(r.get("decision")) for r in records]
    failed = [d for d in decisions if d in _FAILED_CHECKS]
    if failed:
        return f"the check recorded {failed[0]!r}"
    if exit_code == 0:
        return None
    if exit_code == 2 and decisions:
        return None
    return f"the check exited {exit_code} and recorded nothing"


def check_after_stop(
    check: EndCheck, session_id: str, cwd: Path, env: dict[str, str], state: Path
) -> dict[str, Any]:
    """Run the sentinel's SessionEnd check once more, after the session's processes are gone.

    The session's own last check runs at its SessionEnd hook; a process it left could write a
    put-back root after that and before it was stopped. This check, the same command on the
    same record, puts any such write back. Returns what it did, for the session's end record,
    with ``refused`` naming why the attempt must go no further, if it must.

    What this still misses is what the stop misses (``reviewers.ending``): a process that left
    the session's process group and outlived its parent between two polls is never stopped, and
    a write it makes after this check is not put back. A role session's shell can start one;
    the hook layer refuses the backgrounding it can see.
    """
    log = state / LOG_NAME
    offset = log.stat().st_size if log.exists() else 0
    event = {"session_id": session_id, "cwd": str(cwd), "hook_event_name": "SessionEnd"}
    try:
        done = subprocess.run(
            check.argv,
            input=json.dumps(event | {"reason": "other"}),
            capture_output=True,
            text=True,
            timeout=check.timeout_s,
            cwd=cwd,
            env=env,
            check=False,
        )
        exit_code: int | None = done.returncode
    except (OSError, subprocess.TimeoutExpired):
        exit_code = None
    written = log.read_bytes()[offset:] if log.exists() else b""
    try:
        records = [json.loads(line) for line in written.splitlines() if line.strip()]
    except ValueError:
        records, exit_code = [{"decision": "error"}], None
    return {
        "refused": sentinel_refusal(exit_code, records),
        "exit": exit_code,
        "decisions": [r.get("decision") for r in records],
        "put_back": sorted(
            {p for r in records if r.get("decision") == "put back" for p in r.get("paths", [])}
        ),
    }


#: How ``ps`` prints a start time under the C locale.
_LSTART = "%a %b %d %H:%M:%S %Y"


def _seconds(lstart: str | None) -> float | None:
    if lstart is None:
        return None
    try:
        return time.mktime(time.strptime(lstart, _LSTART))
    except ValueError:
        return None


def process_rows() -> list[tuple[int, int, str, str]] | None:
    """Every process as ``ps`` lists it, (pid, pgid, state, start), or ``None`` if unread.

    A table that does not list this very process was not read, whatever ``ps`` returned.
    """
    try:
        done = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat=,lstart="],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=30.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], " ".join(parts[3].split())))
    if done.returncode != 0 or os.getpid() not in {row[0] for row in rows}:
        return None
    return rows


def still_running(
    session_pid: int, started: str | None, stopped: Iterable[int], stop_done: float
) -> str | None:
    """Why the session's stop is not confirmed, or ``None`` once its tree and group are empty.

    Read from the process table afresh, never from what the stop concluded: any process still in
    the session's group started since the session, or still running at a pid the stop stopped
    and started between the session and the end of the stop. A pid reused in that window counts
    too, as does a start time that cannot be read: the attempt is refused rather than a
    survivor missed.
    """
    rows = process_rows()
    if rows is None:
        return "the process table could not be read"
    since, watched = _seconds(started), set(stopped)

    def left(pid: int, pgid: int, lstart: str) -> bool:
        at = _seconds(lstart)
        after = since is None or at is None or at >= since
        # A group member started after the stop is still the session's: a group's id is not
        # reused while it has a member. A stopped pid running again may be another process.
        return after and (pgid == session_pid or (pid in watched and (at or 0) <= stop_done))

    found = sorted(
        pid
        for pid, pgid, state, lstart in rows
        if pid != session_pid and not state.startswith("Z") and left(pid, pgid, lstart)
    )
    return f"still running after the stop: {found}" if found else None


def sweep_group(pid: int, started: str | None) -> tuple[int, ...]:
    """Stop every process left in the process group ``pid`` led, the shared stop's sweep.

    For a session found at a resume, whose own tree a walk can no longer reach. Only members
    started since the session are stopped.
    """
    since = _seconds(started)

    def members() -> list[Proc]:
        return [
            p
            for p in group(pid)
            if p.pid != pid and (since is None or (_seconds(p.started) or since) >= since)
        ]

    stopped = set(stop_all(members()))
    for _ in range(SWEEPS):
        found = stop_all(members())
        if not found:
            break
        stopped |= set(found)
    return tuple(sorted(stopped))


def end_check_at_resume(sdir: Path, session_id: str, install_bin: Path) -> EndCheck | None:
    """The sentinel's SessionEnd check for a session found at a resume, or ``None`` if it has none.

    The settings file is the session's user's to write by then, so nothing executable is taken
    from it: the installation's own interpreter runs the hook module, and only the digest of the
    configuration it names is read (a rewritten configuration fails that digest). A session whose
    sentinel never recorded anything has nothing to compare.
    """
    baseline = sdir / "state" / "sessions" / session_id / "sentinel" / "baseline.json"
    if not baseline.exists():
        return None
    config = sdir / "session" / CONFIG_NAME
    try:
        argv = session_end_command(sdir / "session" / SETTINGS_NAME).argv
        digest = argv[argv.index("--config-sha256") + 1]
        named = argv[argv.index("--config") + 1]
    except (InvocationError, ValueError, IndexError):
        digest, named = "", ""
    if named != str(config) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        # The check runs all the same, and fails its digest: the attempt is refused.
        digest = "0" * 64
    python = install_bin.parent / "python"
    module = ["-I", "-m", "physgate.hooks", "SessionEnd", "--hooks", "sentinel"]
    argv = (str(python), *module, "--config", str(config), "--config-sha256", digest)
    return EndCheck(argv, 30.0)


def write_record(parent: Path, name: str, record: dict[str, Any], file: str) -> None:
    """Write ``parent/name/file`` as a new file, never through a link a session could plant.

    The session's directory is opened without following a link, and the file is created
    exclusively without following one: whatever stood at that name (a link the session's
    process planted, pointing anywhere) is unlinked, never written through.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY
    top = os.open(parent, flags)
    try:
        here = os.open(name, flags | os.O_NOFOLLOW, dir_fd=top)
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(file, dir_fd=here)
            create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            fd = os.open(file, create, 0o600, dir_fd=here)
            with os.fdopen(fd, "w") as out:
                out.write(json.dumps(record))
        finally:
            os.close(here)
    finally:
        os.close(top)


@dataclass(frozen=True)
class RootsRecord:
    """The orchestrator's own record of every put-back root, taken before the session starts.

    Held in the orchestrator's memory, never on disk, so nothing the session's user can write
    (the sentinel's own record among it) can make a changed root pass for an unchanged one.
    """

    roots: tuple[str, ...]
    exclude: tuple[str, ...]
    #: Path to its signature, its content digest if a file, its target if a link.
    entries: dict[str, tuple[Signature, str | None, str | None]]


def record_roots(config_path: Path) -> RootsRecord:
    """Record every root the session's sentinel puts back, as its configuration names them.

    Raises:
        OSError: a path under a root could not be read; no session may start on such a record.
    """
    config = SessionConfig.model_validate_json(config_path.read_bytes())
    reverted = [r for r in config.protected_roots if r.watch == "revert"]
    frozen = _frozen_experiment_paths(config)
    roots = tuple(sorted({r.path for r in reverted} | set(frozen)))
    exclude = tuple(sorted({e for r in reverted for e in r.exceptions}))
    entries = {
        path: (
            sig,
            file_digest(path) if sig[0] == "file" else None,
            os.readlink(path) if sig[0] == "link" else None,
        )
        for path, sig in strict_signatures(roots, exclude).items()
    }
    return RootsRecord(roots, exclude, entries)


def strict_signatures(roots: tuple[str, ...], exclude: tuple[str, ...]) -> dict[str, Signature]:
    """The signature of every path under ``roots`` but ``exclude``, every directory listed.

    Unlike the sentinel's walk, a directory that cannot be listed, or an entry that cannot be
    read, raises: what could not be read is never taken for what is not there. A root that does
    not exist is recorded as absent, and compared as such.

    Raises:
        OSError: a path under a root could not be read.
    """

    def excluded(path: str) -> bool:
        return any(path == e or path.startswith(e.rstrip("/") + "/") for e in exclude)

    found: dict[str, Signature] = {}
    pending = sorted(roots, reverse=True)
    while pending:
        path = pending.pop()
        if excluded(path):
            continue
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        found[path] = signature(st)
        if stat.S_ISDIR(st.st_mode):
            with os.scandir(path) as listing:
                pending.extend(sorted((e.path for e in listing), reverse=True))
    return found


def changed_since(record: RootsRecord) -> list[str]:
    """Every put-back root path that is not now what the record holds, read afresh.

    A file put back holds its bytes and mode again (on a new inode); a directory's own times
    move when the sentinel moves something out of it, so a directory is held to its mode and
    its entries, not its times.
    """
    now = strict_signatures(record.roots, record.exclude)
    changed = set(now) ^ set(record.entries)
    for path, sig in now.items():
        if path not in record.entries or sig == record.entries[path][0]:
            continue
        was, digest, link = record.entries[path]
        kind = sig[0]
        if (
            sig[:2] != was[:2]
            or kind == "other"
            or (kind == "file" and file_digest(path) != digest)
            or (kind == "link" and os.readlink(path) != link)
        ):
            changed.add(path)
    return sorted(changed)


def process_group_of(pid: int) -> int | None:
    """The process group ``ps`` reports for ``pid``, or ``None`` if it is not running."""
    out = subprocess.run(
        ["ps", "-o", "pgid=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    ).stdout.strip()
    return int(out) if out.isdigit() else None


def harness_protection() -> list[str]:
    """The installer's arguments that put the harness checkout out of a session's reach.

    The checkout this orchestrator runs from (its gate source, its curated library
    and bounds tables, its frozen experiments), and the startup files of the
    interpreter this process runs on, wherever its environment lives: a ``.pth``
    planted there runs at the orchestrator's next start.
    """
    harness = harness_root()
    if harness is None:
        return []
    args = ["--harness", str(harness)]
    paths = sysconfig.get_paths()
    for site_packages in sorted({paths["purelib"], paths["platlib"]}):
        args += ["--harness-site-packages", site_packages]
    return args


class Installed(BaseModel):
    """What the hook layer's installer prints: its files and how to spawn the session."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    settings: str
    config: str
    spawn_args: tuple[str, ...]
    spawn_env: dict[str, str]


def redact(path: Path, secret: str | None) -> None:
    """Replace every occurrence of ``secret`` in the file at ``path``."""
    if not secret or not path.exists():
        return
    data = path.read_bytes()
    if secret.encode() in data:
        path.write_bytes(data.replace(secret.encode(), REDACTED))


#: How long an interpreter has to answer the probe.
PROBE_TIMEOUT_S = 60


def probe_interpreter(path: Path) -> dict[str, object] | None:
    """What the interpreter at ``path`` says of itself (``role_python.PROBE``), or ``None``.

    Run from an empty environment and the filesystem root, so nothing of the harness's
    own environment reaches what it reports.
    """
    try:
        done = subprocess.run(
            [str(path), "-I", "-c", PROBE],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
            cwd="/",
        )
        found = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return found if isinstance(found, dict) else None


class ClaudeDispatcher:
    """The loop's dispatcher over the Claude Code binary."""

    def __init__(
        self,
        *,
        config: RunConfig,
        run: RunGit,
        store_root: Path,
        install_bin: Path,
        binary: str,
        base_url: str | None,
        credential: Credential,
        review_root: Path,
    ) -> None:
        """Dispatch attempts of ``run`` with the hooks from ``install_bin``'s installation.

        ``review_root`` is where reviews are prepared, every packet with its copy of a
        rubric; no role session may read or write anything beneath it.
        """
        self._config = config
        self._run = run
        self._store_root = store_root
        self._install_bin = install_bin
        self._binary = binary
        self._base_url = base_url
        self._credential = credential
        self._review_root = Path(review_root)
        self._facts: InstallFacts | None = None
        harness = harness_root()
        #: Every canary the harness's rubric promotions recorded, read once.
        self._canaries = (
            canaries(harness / KNOWLEDGE_ROOT / PROMOTIONS_NAME) if harness else frozenset()
        )

    def environment(self) -> InstallFacts:
        """The installation's and the session directories' facts, taken once."""
        if self._facts is None:
            self._facts = install_facts(
                self._install_bin.parent.parent, self._run.run_dir / "sessions"
            )
        return self._facts

    def _install(self, request: SessionRequest, worktree: Path, sdir: Path) -> Installed:
        state = sdir / "state"
        state.mkdir(parents=True)
        helper: list[str] = []
        if self._credential.mode == "api_key":
            key_helper = write_key_helper(state, self._credential.secret)
            helper = ["--api-key-helper", str(key_helper)]
        reverted, refused = session_protected_roots(
            self._run, self._store_root, worktree, self._install_bin.parent.parent
        )
        protect = [arg for root in reverted for arg in ("--protect", str(root))]
        protect += [arg for root in refused for arg in ("--protect-refuse-only", str(root))]
        # A session in the target's worktree has nothing of its own in the harness
        # checkout, and the live gate reads from it.
        protect += harness_protection()
        # Where reviews are prepared, each packet with its copy of a rubric: withheld
        # from the role session like the library's reviewer tree.
        protect += ["--review-material", str(self._review_root)]
        # The always-loaded set (cross's standards, the role's own standards and
        # skill) is a subset of required reading, which adds the module spec.
        # loader.py names both relative to the worktree being dispatched to, never
        # the orchestrator's own checkout — that is where this session's Read
        # tool actually operates.
        reading_paths = loader.required_reading(request.assigned_role, Path(request.spec_path))
        always_loaded_paths = loader.always_loaded(request.assigned_role)
        reading_args = [
            arg for path in reading_paths for arg in ("--reading", str(worktree / path))
        ]
        always_loaded_args = [
            arg for path in always_loaded_paths for arg in ("--always-loaded", str(worktree / path))
        ]
        argv = [
            str(self._install_bin),
            "hooks",
            "install",
            "--profile",
            "role",
            "--role",
            request.assigned_role,
            "--worktree",
            str(worktree),
            "--own-branch",
            self._run.subtask_branch(request.subtask_id),
            "--store-root",
            str(self._store_root),
            "--state-dir",
            str(state),
            "--target",
            str(sdir / "session"),
            "--claude-config-dir",
            str(sdir / "config"),
            "--user-home",
            str(sdir / "home"),
            "--ceiling",
            str(self._config.token_ceiling),
            *reading_args,
            *always_loaded_args,
            *helper,
            *protect,
        ]
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            msg = "the hook layer's installer refused the session"
            raise InvocationError(msg, stderr=done.stderr[-600:])
        if self._credential.mode == "subscription":
            write_login(sdir / "config", self._credential.secret)
        return Installed.model_validate_json(done.stdout)

    def run(self, request: SessionRequest) -> SessionReport:
        """Run one attempt in a fresh session and report what it left."""
        reported = binary_version(self._binary)
        if reported != self._config.claude_version:
            msg = "the binary is not the version this run recorded"
            raise InvocationError(msg, reported=reported, recorded=self._config.claude_version)
        worktree = self._run.open_subtask(request.subtask_id)
        # The specification as issued, digested before the session can touch anything.
        issued = (
            issued_spec_sha256(self._run.repo, request.spec_commit, request.spec_path)
            if request.spec_commit is not None
            else None
        )
        session_id = str(uuid.uuid4())
        sdir = self._run.run_dir / "sessions" / session_id
        system_before = self.environment().system_managed
        installed = self._install(request, worktree, sdir)
        # Read before the session starts, while nothing of it can have touched the file.
        end_check = session_end_command(Path(installed.settings))
        (sdir / "home").mkdir(exist_ok=True)
        env = isolated_env(
            home=sdir / "home",
            config_dir=sdir / "config",
            binary=self._binary,
            max_retries=request.bounds.binary_max_retries,
            max_output_tokens=self._config.max_output_tokens,
            base_url=self._base_url,
            api_key=None,
        )
        env.update(installed.spawn_env)
        recorded_python = self._config.role_python
        if recorded_python is not None:
            # The run's named interpreter, measured again, first on the session's PATH as
            # ``python3``: a directory holding nothing else, so nothing beside it comes too.
            require_same(
                recorded_python,
                probe=probe_interpreter,
                harness=harness_root(),
                install=self._install_bin.parent.parent,
            )
            env["PATH"] = f"{session_bin(sdir, recorded_python)}:{env['PATH']}"
        argv = role_argv(
            self._binary,
            prompt=role_prompt(request),
            spawn_args=installed.spawn_args,
            model=request.model,
            session_id=session_id,
            max_turns=request.bounds.session_max_turns,
            effort=self._config.effort,
            thinking_display=self._config.thinking_display,
        )
        stdout = sdir / "stdout.jsonl"
        # The orchestrator's own record of the put-back roots, taken before the session can
        # write anything: the check after the stop is held to it, not to the sentinel's alone.
        try:
            roots = record_roots(Path(installed.config))
        except OSError as exc:
            msg = "a put-back root could not be read, so no session starts on it"
            raise InvocationError(msg, error=repr(exc)) from exc
        with stdout.open("wb") as out, (sdir / "stderr.txt").open("wb") as err:
            process = subprocess.Popen(
                argv,
                cwd=worktree,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            try:
                spawned = started_at(process.pid)
            except ProcessTableError:
                # Nothing of its own can be told apart yet: the session alone is stopped.
                process.kill()
                process.wait()
                raise
            record = {
                "pid": process.pid,
                "started": spawned,
                "spawned_at": time.time(),
                "session_id": session_id,
                # Exactly what was spawned, so it can be held against what the hook
                # layer's installer printed. It carries no key: the key is in a helper.
                "argv": argv,
                "installer_spawn_args": list(installed.spawn_args),
            }
            (sdir / "process.json").write_text(json.dumps(record))
            # However the session ends, nothing it started is left running before any git
            # call of the orchestrator's on this attempt; then the sentinel's last check runs
            # once more, for what was written between SessionEnd and the stop.
            ended: SessionEnd | None = None
            try:
                ended = await_session(
                    process,
                    record["started"],  # type: ignore[arg-type]
                    request.bounds.session_wall_clock_s,
                )
            except OSError as exc:
                unconfirmed: str | None = f"the stop could not be completed: {exc!r}"
                # The session itself is this process's own child, unreaped, so its pid is still
                # its own: it alone is stopped here; what it started waits for the resume.
                with contextlib.suppress(OSError):
                    process.kill()
                    process.wait()
            stop_done = time.time()
        if ended is not None:
            # The table is read again: nothing the stop concluded is taken as its proof.
            unconfirmed = still_running(
                process.pid,
                record["started"],  # type: ignore[arg-type]
                ended.left_running,
                stop_done,
            )
        # The credential is on disk only while its session runs.
        remove_secrets(sdir / "state", sdir / "config")
        redact(stdout, self._credential.secret)
        # On every path, the stop confirmed or not.
        after_stop = check_after_stop(end_check, session_id, worktree, env, sdir / "state")
        # Read afresh after the check, against the record taken before the spawn: a check
        # skipped, or satisfied by a sentinel record the session's process rewrote, shows here.
        try:
            moved, unread = changed_since(roots), None
        except OSError as exc:
            moved, unread = [], f"a put-back root could not be read: {exc!r}"
        if (
            ended is None
            or unconfirmed is not None
            or after_stop["refused"] is not None
            or moved
            or unread is not None
        ):
            settled = {
                "left_running": list(ended.left_running) if ended is not None else [],
                "stop_unconfirmed": unconfirmed,
                "sentinel_after_stop": after_stop,
                "protected_changed": moved,
                "protected_unread": unread,
            }
            # Beside the end record, not in it: a resume still finds the session unended,
            # stops and checks it again, and reads what it spent.
            write_record(sdir.parent, sdir.name, settled, "after_stop.json")
            msg = (
                "the session's stop is not confirmed, or the sentinel's check after it "
                "failed; no git call follows on this attempt"
            )
            raise InvocationError(
                msg,
                session_id=session_id,
                stop=unconfirmed or "",
                check=str(after_stop["refused"] or ""),
                changed=", ".join(moved),
                unread=unread or "",
            )
        exit_code: int | None = ended.exit_code
        timed_out = ended.timed_out
        captured = read_captured(stdout)
        seen = review_material_seen(stdout, self._canaries)
        sealed, tampered = captured.seal, captured.tampered
        result, usage, answered = captured.result, captured.usage, captured.answered
        require_matching_totals(result, usage)
        end = classify_session_end(result, exit_code=exit_code, stopped_at_wall_clock=timed_out)
        if end.outcome == "completed":
            echoed = sorted(answered)
            if echoed != [request.model]:
                msg = "the session was answered by a model other than the pinned one"
                raise InvocationError(msg, asked=request.model, answered=",".join(echoed))
        halted, appends = self._hook_log(sdir / "state", session_id)
        commit = (
            commit_attempt(
                worktree, request.subtask_id, request.attempt, session_id, repo=self._run.repo
            )
            if end.outcome == "completed"
            else None
        )
        write_record(
            sdir.parent,
            sdir.name,
            {
                "exit": exit_code,
                "timed_out": timed_out,
                "left_running": list(ended.left_running),
                "sentinel_after_stop": after_stop,
            },
            "ended.json",
        )
        return SessionReport(
            session_id=session_id,
            end=end,
            attempt_commit=commit,
            # Any session whose stream was captured and sealed names it: an infrastructure
            # retry's earlier sessions are part of the attempt its reviewer reads.
            trajectory=str(stdout) if end.outcome == "completed" or sealed is not None else None,
            worktree=str(worktree) if end.outcome == "completed" else None,
            reading_verified=self._read_in_full(Path(installed.config), session_id),
            node_files_halted=halted,
            hook_journal_appends=appends,
            usage=usage,
            managed_drift=drift(sdir / "config", system_before),
            policy_limits_sha256=policy_limits_digest(sdir / "config"),
            trajectory_seal=sealed,
            trajectory_tampered=tampered,
            review_material_seen=seen,
            issued_spec_sha256=issued,
        )

    def stop_leftovers(self) -> list[Leftover]:
        """Stop every session a previous orchestrator left running, before anything else.

        A session is found from the pid and start time recorded when it was
        spawned; a pid now held by another process is not signalled. Every
        session left without an end is returned, stopped or not, with what its
        captured stream shows it spent: its orchestrator died before recording
        that, and nothing else will. Every session's credential files are then
        removed and its stream redacted, before the stream is read.
        """
        found: list[tuple[Path, str, int, int, bool, SessionKind]] = []
        session_dirs = self._session_dirs()
        for sdir in session_dirs:
            record_path, ended = sdir / "process.json", sdir / "ended.json"
            if ended.exists() or not record_path.exists():
                continue
            record = json.loads(record_path.read_text())
            pid, started = int(record["pid"]), record.get("started")
            kind: SessionKind = "reviewer" if record.get("kind") == "reviewer" else "session"
            session_id = str(record["session_id"])
            if is_session(pid, started, session_id):
                # The group the harness created for it: the proven session leads it.
                leads = process_group_of(pid) == pid
                killed, stopped = stop_tree(pid, started), True
                written: dict[str, Any] = {"stopped_at_resume": True, "killed": killed}
            else:
                killed, stopped, leads = 0, False, False
                written = {"not_running_at_resume": True}
            if kind == "session":
                # Before any git call on the attempt, as at a session's end under its
                # orchestrator; a refusal leaves the session unended for the next resume.
                written |= self._settle_at_resume(sdir, session_id, pid, started, leads)
            write_record(sdir.parent, sdir.name, written, "ended.json")
            found.append((sdir, session_id, pid, killed, stopped, kind))
        # Nothing of this run is running now, so no session still needs its credential.
        # A killed orchestrator never removed it; its stream was never redacted either.
        for sdir in session_dirs:
            remove_secrets(sdir / "state", sdir / "config")
            redact(sdir / "stdout.jsonl", self._credential.secret)
        leftovers = []
        for sdir, session_id, pid, killed, stopped, kind in found:
            # The same read as a session that ended under its orchestrator: sealed as
            # read, a tail after the runtime's result not taken, and a stream with a
            # result held to the runtime's own totals.
            captured = read_captured(sdir / "stdout.jsonl")
            tampered = captured.tampered
            if tampered is None:
                try:
                    require_matching_totals(captured.result, captured.usage)
                except AccountingError as exc:
                    tampered = f"{exc}: {exc.context}"
            leftovers.append(
                Leftover(
                    session_id=session_id,
                    pid=pid,
                    killed=killed,
                    stopped=stopped,
                    usage=captured.usage,
                    complete=captured.result is not None,
                    seal=captured.seal,
                    tampered=tampered,
                    kind=kind,
                )
            )
        return leftovers

    def _settle_at_resume(
        self, sdir: Path, session_id: str, pid: int, started: str | None, leads: bool
    ) -> dict[str, Any]:
        """Stop what a role session found at a resume left in its group; check once more.

        Only a group proven the session's is signalled: the session was found running by its
        pid, start time and command line (:func:`is_session`), and led its own group, which the
        harness created for it. Otherwise the group the record names (a file the session's user
        can write) is only read: any member started since the session refuses the resume, and
        nothing is signalled. Then the stop is confirmed from the process table and the
        sentinel's check runs again, whatever the confirmation found.

        What this cannot do is what the orchestrator's own record does for a session that ends
        under it: that record died with the orchestrator, so the check here is as good as the
        sentinel's state, which the session's user can write.

        Raises:
            InvocationError: the stop is not confirmed or the check failed; the resume goes no
                further, and the session stays unended for the next.
        """
        swept: tuple[int, ...] = ()
        if leads:
            try:
                swept = sweep_group(pid, started)
            except OSError as exc:
                unconfirmed: str | None = f"the sweep could not signal: {exc!r}"
            else:
                unconfirmed = still_running(pid, started, swept, time.time())
            if started_at(pid) == started:
                unconfirmed = "the session is still running after its stop"
        elif started_at(pid) is None:
            # Read, never signalled: nothing proves this group is the session's.
            unconfirmed = still_running(pid, started, (), time.time())
        else:
            # Another process holds the pid, so no group of that id has a member of the
            # session's left; or the session led no group of its own.
            unconfirmed = None if not is_session(pid, started, session_id) else "no own group"
        check = end_check_at_resume(sdir, session_id, self._install_bin)
        after_stop = (
            check_after_stop(check, session_id, sdir, {"PATH": "/usr/bin:/bin"}, sdir / "state")
            if check is not None
            else {"refused": None, "no_record": True}
        )
        settled = {
            "left_running": list(swept),
            "stop_unconfirmed": unconfirmed,
            "sentinel_after_stop": after_stop,
        }
        if unconfirmed is not None or after_stop["refused"] is not None:
            write_record(sdir.parent, sdir.name, settled, "after_stop.json")
            msg = (
                "a session found at the resume is not confirmed stopped, or the sentinel's "
                "check after its stop failed; the resume goes no further"
            )
            raise InvocationError(
                msg,
                session_id=session_id,
                stop=unconfirmed or "",
                check=str(after_stop["refused"] or ""),
            )
        return settled

    def _session_dirs(self) -> list[Path]:
        """Every session directory of this run: its role sessions', then its reviews'.

        A review's session lives beneath the review root, which no role session may
        reach, and is this run's if its owner record names this run.
        """
        dirs = sorted(p for p in (self._run.run_dir / "sessions").glob("*") if p.is_dir())
        for owner in sorted(self._review_root.glob(f"*/{SESSION_DIRNAME}/{OWNER_NAME}")):
            try:
                run_id = json.loads(owner.read_text()).get("run_id")
            except (OSError, ValueError, AttributeError):
                continue
            if run_id == self._run.run_id:
                dirs.append(owner.parent)
        return dirs

    @staticmethod
    def _read_in_full(config_path: Path, session_id: str) -> bool:
        return read_in_full(config_path, session_id)

    @staticmethod
    def _hook_log(state: Path, session_id: str) -> tuple[bool, tuple[str, ...]]:
        """Whether the sentinel halted on node files, and every journal append it recorded."""
        log = state / "hooks.log.jsonl"
        if not log.exists():
            return False, ()
        halted, appends = False, []
        for line in log.read_text().splitlines():
            record = json.loads(line)
            if record.get("session") != session_id:
                continue
            if record.get("decision") == "node mismatch":
                halted = True
            if record.get("decision") == "journal append":
                appends.append(
                    f"bytes {record.get('bytes')} after {record.get('tool')}: "
                    f"{json.dumps(record.get('tool_input'))[:200]}"
                )
        return halted, tuple(appends)
