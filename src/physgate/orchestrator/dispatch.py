"""The dispatcher: one attempt in a fresh Claude Code session, under the hook layer.

For every attempt: check the binary is still the version the run recorded;
open the subtask's worktree; give the session a directory of its own, outside
the worktree, holding its scratch home and configuration directory, the hook
state and the captured stream; generate its settings with the hook layer's
installer, run from the read-only installation; spawn it exactly as those
settings say; wait within the run's wall clock; then read what it left.

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

import json
import subprocess
import sysconfig
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
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
from physgate.orchestrator.git import common_dir
from physgate.orchestrator.install import InstallFacts, build_record_path, install_facts
from physgate.orchestrator.invocation import isolated_env, role_argv
from physgate.orchestrator.managed import drift, policy_limits_digest
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionKind, SessionReport, SessionRequest
from physgate.orchestrator.processes import is_session, started_at, stop_tree
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.queue import DECISIONS_NAME
from physgate.orchestrator.role_python import PROBE, require_same, session_bin
from physgate.orchestrator.run_config import RunConfig, harness_root
from physgate.orchestrator.trajectory import Seal, forged_tail, seal, through_first_result
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
      orchestrator's integration worktree, and the run branch's ref in the target
      repository. The orchestrator writes none of them while a session runs.
    - Refused only: every session's directory, which holds each session's
      captured stream (the trajectory the reviewer and the token account read)
      and its process record, written by the runtime and the spawner during the
      session; and the approval queue's decisions file, which a person appends to
      with ``physgate queue resolve`` whenever they decide, sessions running or not.
    """
    # Where git keeps the run branch's loose ref, for any repository layout. A ref
    # moved in packed-refs is seen by the loop's check of the branch instead.
    common = common_dir(run.repo)
    ref = common / "refs" / "heads" / run.run_branch
    reverted = (*(run.run_dir / name for name in RUN_RECORDS), run.integration, ref)
    reverted = (*reverted, *git_config_roots(common))
    return reverted, (run.run_dir / "sessions", run.run_dir / DECISIONS_NAME)


#: The files and directories in a repository's common git directory through which a write
#: makes a later git command run a program: its configuration (a diff, merge or filter driver,
#: or the file-system monitor), the attributes and exclude files under ``info/``, the
#: repository hooks, and a submodule's own git directory under ``modules/`` (its config and
#: hooks). A role session has no legitimate need to write any of them, so they are protected
#: roots: the path layer refuses a file tool's write, and the sentinel puts back a shell write.
#: The per-worktree ``config.worktree`` is covered too, because git reads it only when
#: ``extensions.worktreeConfig`` is set in this same ``config``, which is now protected, and a
#: role cannot set it (``git config`` writes are refused at the shell layer).
GIT_CONFIG_NAMES = ("config", "config.worktree", "info", "hooks", "modules")


def git_config_roots(common_git_dir: Path) -> tuple[Path, ...]:
    """The common git directory's exec-config surface, as protected roots."""
    return tuple(common_git_dir / name for name in GIT_CONFIG_NAMES)


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
        reverted, refused = run_protected_roots(self._run)
        # The installation's build record lives beside it, outside the installation
        # root the hook layer protects; a session that rewrote it would make the
        # next run refuse, or, with the manifest, pass. It is put back.
        reverted = (*reverted, build_record_path(self._install_bin.parent.parent))
        # This session's worktree is a linked worktree, so its ``.git`` is a pointer file to
        # the admin directory the orchestrator's commits run against. A session that repointed
        # it would make the commit take another directory's config as git's own, so the pointer
        # is put back. (The orchestrator also verifies it before every git call.)
        reverted = (*reverted, worktree / ".git")
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
            record = {
                "pid": process.pid,
                "started": started_at(process.pid),
                "spawned_at": time.time(),
                "session_id": session_id,
                # Exactly what was spawned, so it can be held against what the hook
                # layer's installer printed. It carries no key: the key is in a helper.
                "argv": argv,
                "installer_spawn_args": list(installed.spawn_args),
            }
            (sdir / "process.json").write_text(json.dumps(record))
            try:
                exit_code: int | None = process.wait(timeout=request.bounds.session_wall_clock_s)
                timed_out = False
            except subprocess.TimeoutExpired:
                stop_tree(process.pid, record["started"])  # type: ignore[arg-type]
                exit_code, timed_out = process.wait(), True
        # The credential is on disk only while its session runs.
        remove_secrets(sdir / "state", sdir / "config")
        redact(stdout, self._credential.secret)
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
            commit_attempt(worktree, request.subtask_id, request.attempt, session_id)
            if end.outcome == "completed"
            else None
        )
        (sdir / "ended.json").write_text(json.dumps({"exit": exit_code, "timed_out": timed_out}))
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
            if is_session(pid, started, str(record["session_id"])):
                killed = stop_tree(pid, started)
                ended.write_text(json.dumps({"stopped_at_resume": True, "killed": killed}))
                found.append((sdir, str(record["session_id"]), pid, killed, True, kind))
            else:
                ended.write_text(json.dumps({"not_running_at_resume": True}))
                found.append((sdir, str(record["session_id"]), pid, 0, False, kind))
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
