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
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
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
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.git import common_dir
from physgate.orchestrator.install import InstallFacts, install_facts
from physgate.orchestrator.invocation import isolated_env, role_argv
from physgate.orchestrator.managed import drift
from physgate.orchestrator.merge import RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest
from physgate.orchestrator.processes import started_at, stop_tree
from physgate.orchestrator.queue import DECISIONS_NAME
from physgate.orchestrator.run_config import RunConfig
from physgate.orchestrator.trajectory import forged_tail, seal, through_first_result

REDACTED = REDACTED_TEXT.encode()


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
    ref = common_dir(run.repo) / "refs" / "heads" / run.run_branch
    reverted = (*(run.run_dir / name for name in RUN_RECORDS), run.integration, ref)
    return reverted, (run.run_dir / "sessions", run.run_dir / DECISIONS_NAME)


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


class _Installed(BaseModel):
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
    ) -> None:
        """Dispatch attempts of ``run`` with the hooks from ``install_bin``'s installation."""
        self._config = config
        self._run = run
        self._store_root = store_root
        self._install_bin = install_bin
        self._binary = binary
        self._base_url = base_url
        self._credential = credential
        self._facts: InstallFacts | None = None

    def environment(self) -> InstallFacts:
        """The installation's and the session directories' facts, taken once."""
        if self._facts is None:
            self._facts = install_facts(
                self._install_bin.parent.parent, self._run.run_dir / "sessions"
            )
        return self._facts

    def _install(self, request: SessionRequest, worktree: Path, sdir: Path) -> _Installed:
        state = sdir / "state"
        state.mkdir(parents=True)
        helper: list[str] = []
        if self._credential.mode == "api_key":
            key_helper = write_key_helper(state, self._credential.secret)
            helper = ["--api-key-helper", str(key_helper)]
        reverted, refused = run_protected_roots(self._run)
        protect = [arg for root in reverted for arg in ("--protect", str(root))]
        protect += [arg for root in refused for arg in ("--protect-refuse-only", str(root))]
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
            "--reading",
            str(worktree / request.spec_path),
            *helper,
            *protect,
        ]
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            msg = "the hook layer's installer refused the session"
            raise InvocationError(msg, stderr=done.stderr[-600:])
        if self._credential.mode == "subscription":
            write_login(sdir / "config", self._credential.secret)
        return _Installed.model_validate_json(done.stdout)

    def run(self, request: SessionRequest) -> SessionReport:
        """Run one attempt in a fresh session and report what it left."""
        reported = binary_version(self._binary)
        if reported != self._config.claude_version:
            msg = "the binary is not the version this run recorded"
            raise InvocationError(msg, reported=reported, recorded=self._config.claude_version)
        worktree = self._run.open_subtask(request.subtask_id)
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
            base_url=self._base_url,
            api_key=None,
        )
        env.update(installed.spawn_env)
        argv = role_argv(
            self._binary,
            prompt=role_prompt(request),
            spawn_args=installed.spawn_args,
            model=request.model,
            session_id=session_id,
            max_turns=request.bounds.session_max_turns,
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
        # Sealed before anything reads it, and read from the same bytes.
        data = stdout.read_bytes()
        sealed = seal(data)
        text = data.decode(errors="replace")
        tampered = forged_tail(text)
        if tampered is not None:
            # What the runtime wrote ends at its first result; the rest is not read.
            text = through_first_result(text)
        result, usage, answered = read_stream(text)
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
            trajectory=str(stdout) if end.outcome == "completed" else None,
            worktree=str(worktree) if end.outcome == "completed" else None,
            reading_verified=self._read_in_full(Path(installed.config), session_id),
            node_files_halted=halted,
            hook_journal_appends=appends,
            usage=usage,
            managed_drift=drift(sdir / "config", system_before),
            trajectory_seal=sealed,
            trajectory_tampered=tampered,
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
        found: list[tuple[Path, str, int, int, bool]] = []
        for record_path in sorted((self._run.run_dir / "sessions").glob("*/process.json")):
            ended = record_path.parent / "ended.json"
            if ended.exists():
                continue
            record = json.loads(record_path.read_text())
            pid, started = int(record["pid"]), record.get("started")
            if started is not None and started_at(pid) == started:
                killed = stop_tree(pid, started)
                ended.write_text(json.dumps({"stopped_at_resume": True, "killed": killed}))
                found.append((record_path.parent, str(record["session_id"]), pid, killed, True))
            else:
                ended.write_text(json.dumps({"not_running_at_resume": True}))
                found.append((record_path.parent, str(record["session_id"]), pid, 0, False))
        # Nothing of this run is running now, so no session still needs its credential.
        # A killed orchestrator never removed it; its stream was never redacted either.
        for sdir in sorted(p for p in (self._run.run_dir / "sessions").glob("*") if p.is_dir()):
            remove_secrets(sdir / "state", sdir / "config")
            redact(sdir / "stdout.jsonl", self._credential.secret)
        leftovers = []
        for sdir, session_id, pid, killed, stopped in found:
            stream = sdir / "stdout.jsonl"
            text = stream.read_text(errors="replace") if stream.exists() else ""
            result, usage, _ = read_stream(text)
            leftovers.append(
                Leftover(
                    session_id=session_id,
                    pid=pid,
                    killed=killed,
                    stopped=stopped,
                    usage=usage,
                    complete=result is not None,
                )
            )
        return leftovers

    @staticmethod
    def _read_in_full(config_path: Path, session_id: str) -> bool:
        """The hook layer's own answer: is every required file read in full, as it is now?"""
        config = SessionConfig.model_validate_json(config_path.read_bytes())
        return not outstanding(config, _Input(session_id=session_id))

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
