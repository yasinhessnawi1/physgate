"""A harness round over a stand-in tier version, its runs made by the real loop with no model.

The store is the baseline's stand-in (:func:`baseline_fixtures.stand_in_store`): twenty-four
fixture tasks split by the real writer, its check recorded, a run root registered. The target
is a repository with one commit. The driver stands in for the ``physgate`` command: its
``decompose`` does what the command's does with the call's outcome given, not asked of a model
(its first step the command's own, :func:`open_decomposition`: the run directory refused unless
fresh and its own, the parameters recorded with the target; the run started from a plan of one
control module, or recorded as a failed decomposition); its ``drive`` is the real loop with
the real change checker, merger and store keeper, a stand-in session that writes the answer file
in its module's directory, and the command's own refusal of a resume before a usage limit's
reset. A row makes a call fail, end on the machine or be killed, by its number.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

EVALUATION_TESTS = Path(__file__).resolve().parents[1]
for _where in (EVALUATION_TESTS, EVALUATION_TESTS / "baseline", EVALUATION_TESTS / "per_role"):
    if str(_where) not in sys.path:
        sys.path.insert(0, str(_where))

import pytest  # noqa: E402
from baseline_fixtures import (  # noqa: E402
    BUILT,
    EXAMPLES,
    LAYER,
    MODEL,
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    setup_for,
    stand_in_store,
)
from knowledge_fixture import build_fixture_library  # noqa: E402
from observe_rig import FakeSession, Gate, Reviewer, node  # noqa: E402
from task_fixtures import controller  # noqa: E402

import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.evaluation.harness_round import Decompose, Drive, Inputs  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.tiers.canaries import store_canaries  # noqa: E402
from physgate.evaluation.tiers.exposure import add_run_root, run_roots  # noqa: E402
from physgate.evaluation.tiers.heldout import tier_digest  # noqa: E402
from physgate.evaluation.tiers.store import role_root  # noqa: E402
from physgate.evaluation.tiers.task import Role, Task  # noqa: E402
from physgate.knowledge.library import LibraryError  # noqa: E402
from physgate.orchestrator import decompose as core_decompose  # noqa: E402
from physgate.orchestrator import design_rounds  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper  # noqa: E402
from physgate.orchestrator.budget import SessionEnd  # noqa: E402
from physgate.orchestrator.canaries import CanaryCheck  # noqa: E402
from physgate.orchestrator.credentials import Credential, remove_secrets  # noqa: E402
from physgate.orchestrator.decompose import (  # noqa: E402
    Outcome,
    Plan,
    PlannedModule,
    mint_id,
    open_decomposition,
    start_run,
)
from physgate.orchestrator.design_rounds import (  # noqa: E402
    decompose_in_rounds,
    decomposition_streams,
)
from physgate.orchestrator.escalation import bind  # noqa: E402
from physgate.orchestrator.events import SubtaskPlanned, read_events  # noqa: E402
from physgate.orchestrator.exceptions import (  # noqa: E402
    InvocationError,
    LimitNotResetError,
    ModelSeparationError,
    OrchestratorError,
    ReviewUnavailableError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.git import head_of  # noqa: E402
from physgate.orchestrator.loop import Loop  # noqa: E402
from physgate.orchestrator.merge import GitMerger, RunGit  # noqa: E402
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook  # noqa: E402
from physgate.orchestrator.processes import started_at  # noqa: E402
from physgate.orchestrator.protocols import (  # noqa: E402
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    Usage,
)
from physgate.orchestrator.record import ReviewInstall, RunRecord  # noqa: E402
from physgate.orchestrator.review_root_record import record_review_root  # noqa: E402
from physgate.orchestrator.run_config import (  # noqa: E402
    RunConfig,
    account_in_effect,
    load_run_config,
    require_same_account,
)
from physgate.orchestrator.trajectory import seal  # noqa: E402
from physgate.orchestrator.usage_limit import UsageLimit  # noqa: E402
from physgate.orchestrator.waiting import (  # noqa: E402
    EXIT_WAITING_FOR_LIMIT,
    limit_wait,
    printed_step,
)
from physgate.reviewers.exceptions import ReviewError  # noqa: E402
from physgate.reviewers.places import review_root_path  # noqa: E402
from physgate.state.schema import Node  # noqa: E402

__all__ = [
    "PINS",
    "PRICES",
    "SCORED",
    "Killed",
    "Rig",
    "StandInArm",
    "StandInDriver",
    "make_rig",
    "setup_for",
]

#: What the stand-in driver measures as the harness, the client, its version and the rest the
#: command measures for every run (as the rig's parameters record them): a clean checkout at one
#: commit and the suite's stand-in build.
PINS: dict[str, Any] = {
    "harness": {"commit": "c" * 40, "clean": True, "uncommitted_sha256": None},
    "binary": BUILT.model_dump(mode="json"),
    "claude_version": "2.1.301",
    "git_binary": None,
    "role_python": None,
    "tool_environment": None,
    "tool_servers": None,
    "endpoint": "default",
    "tool_search": "denied",
    "python_bytecode": "not_written",
}
#: The plan's reviewer, on another model than the decomposition's.
PLAN_REVIEWER = "claude-sonnet-5"


class Killed(BaseException):  # noqa: N818 - stands for the process being killed, as an interrupt is
    """The round's process killed at the point a row names."""


def target_repo(root: Path) -> Path:
    """A target repository with one commit and a clean worktree."""
    repo = root / "design"
    (repo / "modules").mkdir(parents=True)
    (repo / "README.md").write_text("design\n")
    (repo / "modules" / "keep.txt").write_text("x\n")
    for args in (
        ["init", "-q", "-b", "master"],
        ["add", "-A"],
        ["commit", "-q", "-m", "i"],
    ):
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    return repo


def params(made: StandInStore, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """A measured single-role run's parameters on the store, with what the command measures.

    The stand-in ``decompose`` takes these as the run's configuration, adding what a run is
    given (its id, seed, brief digest and target commit); the real one measures the rest. They
    withhold whole every run root of the store, as the core's rule asks.
    """
    fields: dict[str, Any] = json.loads((EXAMPLES / "params.subscription.json").read_text())
    fields.update(
        claude_version="2.1.301",
        endpoint="default",
        reportable=True,
        harness={"commit": "c" * 40, "clean": True, "uncommitted_sha256": None},
        git_binary=None,
        binary=BUILT.model_dump(),
        account={"name": fields["account"], "token_sha256_prefix": "e" * 12},
        os_layer=LAYER.model_dump(),
        # A stand-in loop records no OS-layer line: allowed, as for every rig of the loop.
        os_layer_absent="allow",
        network="none",
        network_enforced=True,
        tool_servers=None,
        tool_search="denied",
        python_bytecode="not_written",
        # The plan's review is a model call; the stand-in makes none.
        design_review="off",
        models={
            "decomposition": MODEL,
            "roles": {"control": MODEL},
            "reviewers": {"control": "claude-sonnet-5"},
        },
        held_out=list(made.held_out),
        held_out_sha256=[tier_digest(Path(root)) for root in made.held_out],
        held_out_canaries=sorted(set(made.canaries) | set(store_canaries(made.store))),
    )
    fields["bounds"]["infra_retry_delays_s"] = [7.0]
    # Every registered run root of the store, every role's, as the core's rule asks of a
    # measured run of any tier.
    fields["withheld_whole"] = sorted(
        str(r)
        for role in get_args(Role)
        if os.path.lexists(role_root(made.store, role))
        for r in run_roots(made.store, role)
    )
    if changes.get("design_review", "off") != "off":
        reviewers = {**fields["models"]["reviewers"], "design": PLAN_REVIEWER}
        fields["models"] = {**fields["models"], "reviewers": reviewers}
    fields.update(changes)
    return fields


@dataclass
class AnswerSession(FakeSession):
    """The loop's stand-in session, writing the task's answer file in its module's directory."""

    answer_name: str = "answer.json"
    #: The calls that write no answer (a call that ends on the machine writes none either).
    silent: set[int] = field(default_factory=set)
    #: The calls the process is killed in, before the session runs.
    killed: set[int] = field(default_factory=set)
    #: The calls that end on the account's usage limit, its reset not read (or read, as given).
    limited: set[int] = field(default_factory=set)
    limit_resets_at: str | None = None
    #: The calls whose credential is refused.
    refused_credential: set[int] = field(default_factory=set)
    #: Counted across every drive of the row, so a call's number names it in any process.
    counter: list[int] = field(default_factory=lambda: [0])

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        self.counter[0] += 1
        call = self.counter[0]
        if call in self.killed:
            raise Killed
        self.calls = call - 1  # the stand-in numbers its own calls from here
        worktree = self.layout.open_subtask(request.subtask_id)
        if call in self.refused_credential:
            return SessionReport(
                session_id=f"cred-{call}",
                end=SessionEnd(outcome="infrastructure", cause="credential_refused"),
                attempt_commit=None,
                trajectory=None,
                trajectory_seal=None,
                worktree=str(worktree),
                reading_verified=False,
                node_files_halted=False,
                usage=(),
            )
        if call in self.limited:
            stream = self.layout.run_dir / "sessions" / f"limit-{call}" / "stdout.jsonl"
            stream.parent.mkdir(parents=True, exist_ok=True)
            stream.write_text(json.dumps({"type": "result", "session_id": f"limit-{call}"}) + "\n")
            return SessionReport(
                session_id=f"limit-{call}",
                end=SessionEnd(outcome="infrastructure", cause="usage_limit"),
                attempt_commit=None,
                trajectory=str(stream),
                trajectory_seal=seal(stream.read_bytes()),
                worktree=str(worktree),
                reading_verified=False,
                node_files_halted=False,
                usage=(),
                usage_limit=(
                    UsageLimit(resets="later")
                    if self.limit_resets_at is None
                    else UsageLimit(resets="1:20pm (Europe/Oslo)", resets_at=self.limit_resets_at)
                ),
            )
        if call not in self.silent and call not in self.infra:
            module = worktree / request.module_dir
            module.mkdir(parents=True, exist_ok=True)
            (module / self.answer_name).write_text(json.dumps(controller()))
        return super().run(request, on_spawn)


@dataclass
class StandInDriver:
    """Decomposes and drives as the command does; each call numbered from 1 across the row."""

    library: Path
    answer_name: str
    #: Per decomposition: the cause its call ends on instead of a plan.
    fails: dict[int, str] = field(default_factory=dict)
    #: The decompositions the process is killed in, after the parameters are recorded.
    killed_in_decompose: set[int] = field(default_factory=set)
    #: The decompositions the command refuses (exit 2) before it writes anything.
    refused: set[int] = field(default_factory=set)
    #: The drives the process is killed in, before the loop is built.
    killed_in_drive: set[int] = field(default_factory=set)
    #: Session calls (across the row) that end on an API error, that write no answer, or in
    #: which the process is killed.
    infra: set[int] = field(default_factory=set)
    silent: set[int] = field(default_factory=set)
    killed: set[int] = field(default_factory=set)
    limited: set[int] = field(default_factory=set)
    #: The instant a limited session's stream gives its reset at; ``None``: its reset not read.
    limit_resets_at: str | None = None
    refused_credential: set[int] = field(default_factory=set)
    #: The secret the command is started with; ``None``: the account is not held, as every row
    #: but the account's drives. Given, each drive is held to the run's account as the command
    #: holds it, with the person's word on a replaced credential as the command takes it.
    secret: str | None = None
    #: The module directory the plan gives, from the minted id; ``modules/<id>`` by default.
    module_dir: Callable[[str], str] = lambda minted: f"modules/{minted}"
    #: Under a parameters' ``design_review: observe``, the plan's call and its review, scripted:
    #: the decompositions killed once the call wrote its stream; killed during the review, the
    #: review's session left running (and its stream holding ``review_shows`` where given); whose
    #: review errs (``invocation_error`` or ``model_separation``, a void; an invocation error with
    #: ``review_shows`` given after its session wrote it and ended; ``credential_refused``, the
    #: review's session ended by a refused credential, which a mode that holds the plan ends void
    #: on); whose run cannot be started (a void after the round's end line).
    killed_after_call: set[int] = field(default_factory=set)
    killed_in_review: set[int] = field(default_factory=set)
    review_shows: str | None = None
    review_errs: dict[int, str] = field(default_factory=dict)
    start_raises: set[int] = field(default_factory=set)
    #: Under ``observe``, a run begun and never finished: the decompositions killed while their
    #: run's opening is written, before its first line of the named kind (``RunStarted``: the
    #: configuration recorded and no line); killed once the run has started and before the round
    #: journal's last line; and whose library the core's own start cannot put into the target, once
    #: the run's record is opened.
    killed_before_line: dict[int, str] = field(default_factory=dict)
    killed_before_journal_end: set[int] = field(default_factory=set)
    library_refused_at_start: set[int] = field(default_factory=set)
    #: ... and killed once the run's record is opened and its branch made, before its first commit
    #: (so before its configuration is recorded).
    killed_before_configuration: set[int] = field(default_factory=set)
    #: Under ``observe``, the decompositions whose first call's output its schema refused: the call
    #: is made once more, the first journalled with its spend.
    schema_refused_first: set[int] = field(default_factory=set)
    #: The review sessions left running, as (pid, session id): a row stops what is left.
    left_reviews: list[tuple[int, str]] = field(default_factory=list)
    #: What this driver measures as the harness, the client and its version.
    pin_record: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(PINS)))
    decomposed: list[Decompose] = field(default_factory=list)
    drives: list[Drive] = field(default_factory=list)
    sessions: list[int] = field(default_factory=lambda: [0])
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def pins(self, inputs: Inputs | None = None) -> dict[str, Any]:  # noqa: ARG002
        """The harness, the client and the rest, as the command would measure them for a run."""
        measured: dict[str, Any] = json.loads(json.dumps(self.pin_record))
        return measured

    def config_of(self, call: Decompose) -> RunConfig:
        """The run's configuration: the round's parameters with what a run is given."""
        fields = json.loads(call.params.read_bytes())
        fields.update(
            run_id=call.run_id,
            seed=call.seed,
            brief_sha256=hashlib.sha256(call.brief.read_bytes()).hexdigest(),
            target_head=head_of(call.target, "HEAD"),
        )
        return RunConfig.model_validate_json(json.dumps(fields))

    def plan_of(self, config: RunConfig) -> Plan:
        """The plan every decomposition gives: one control module, its directory from its id."""
        return Plan(
            modules=(
                PlannedModule(
                    name="ctl",
                    role="control",
                    module_dir=self.module_dir(mint_id(config.seed, 0, "ctl")),
                    spec="Design the controller. Answer here.",
                ),
            ),
            interface_nodes=(Node.model_validate(node("iface.bus", kind="interface")),),
        )

    def decompose(self, call: Decompose) -> int:
        self.decomposed.append(call)
        n = len(self.decomposed)
        if n in self.refused:
            return 2
        # The command's own first step, called as the command calls it: the directory refused
        # unless fresh and its own, then the parameters recorded with the target.
        open_decomposition(
            call.run_dir,
            params=call.params,
            target=call.target,
            brief=call.brief,
            review_root=review_root_path(call.review_root),
        )
        if n in self.killed_in_decompose:
            raise Killed
        # The review root, recorded before the call as a measured run's decomposition records it
        # (its plan is reviewed), so a later reader looks for its reviews where they are.
        record_review_root(call.run_dir, review_root_path(call.review_root))
        config = self.config_of(call)
        cause = self.fails.get(n)
        plan = self.plan_of(config)
        usage = Usage(
            input_tokens=50,
            output_tokens=20,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        outcome = Outcome(
            session_id=f"plan-{n}",
            ok=cause is None,
            cause=cause,  # type: ignore[arg-type]
            detail="stand-in",
            plan=plan if cause is None else None,
            usage=(MessageUsage(message_id=f"plan-{n}", usage=usage),),
            model=MODEL,
            num_turns=1,
            # A call that ended on the account's usage limit carries the limit, as the core's own
            # reading gives it: here with no reset read, so the round waits the core's stated wait.
            usage_limit=UsageLimit(resets=None) if cause == "usage_limit" else None,
        )
        if config.design_review != "off":
            try:
                self._in_rounds(n, call, config, outcome)
            except (OrchestratorError, ReviewError):
                return 2  # as the command fails a void decomposition
        else:
            start_run(
                outcome,
                config=config,
                run_dir=call.run_dir,
                target_repo=call.target,
                library=self.library,
            ).close()
        # The call's stream, where the log names it: a protected trial's is scanned for its canary.
        for place in decomposition_streams(read_events(call.run_dir / "events.jsonl")):
            stream = call.run_dir / place
            stream.parent.mkdir(parents=True, exist_ok=True)
            if not stream.exists():
                stream.write_text(json.dumps({"type": "result", "session_id": f"plan-{n}"}) + "\n")
        return 0 if cause is None else 1

    def _in_rounds(self, n: int, call: Decompose, config: RunConfig, outcome: Outcome) -> None:
        """The decomposition as the command makes it with its plan reviewed: the core's rounds."""
        root = review_root_path(call.review_root)
        reviewer = PlanReview(self, n, root)
        calls = [0]

        def make_call(
            brief: str,
            *,
            workdir: Path,
            prompt: str | None,
            session_id: str,
            accept_misorder: bool = False,
        ) -> Outcome:
            calls[0] += 1
            workdir.mkdir(parents=True, exist_ok=True)
            stream = workdir / "stdout.jsonl"
            stream.write_text(json.dumps({"type": "result", "session_id": session_id}) + "\n")
            if n in self.killed_after_call:
                raise Killed
            made = outcome.model_copy(
                update={"session_id": session_id, "stream_seal": seal(stream.read_bytes())}
            )
            if n in self.schema_refused_first and calls[0] == 1:
                said = "the output was refused by its schema"
                return made.model_copy(
                    update={"ok": False, "cause": "schema_refused", "detail": said, "plan": None}
                )
            return made

        with contextlib.ExitStack() as stack:
            patch = stack.enter_context(pytest.MonkeyPatch.context())
            if n in self.start_raises:

                def unstartable(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
                    msg = "the run could not be started"
                    raise RunStateError(msg)

                patch.setattr(design_rounds, "start_run", unstartable)
            if n in self.library_refused_at_start:

                def refusing(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
                    msg = "the target holds other bytes where the library goes"
                    raise LibraryError(msg)

                patch.setattr(core_decompose, "put_into", refusing)
            if n in self.killed_before_configuration:

                def killed(*_a: Any, **_k: Any) -> Any:  # noqa: ANN401
                    raise Killed

                patch.setattr(core_decompose, "commit_all", killed)
            if n in self.killed_before_line:
                kind, emit = self.killed_before_line[n], RunRecord.emit

                def killing(record: RunRecord, event: Any) -> None:  # noqa: ANN401
                    if type(event).__name__ == kind:
                        raise Killed
                    emit(record, event)

                patch.setattr(RunRecord, "emit", killing)
            if n in self.killed_before_journal_end:
                end = design_rounds._Loop.end

                def cut(loop: Any, k: int, follows: str, *rest: Any) -> None:  # noqa: ANN401
                    if follows != "void":
                        raise Killed
                    end(loop, k, follows, *rest)

                patch.setattr(design_rounds._Loop, "end", cut)
            made = decompose_in_rounds(
                call.brief.read_bytes().decode(),
                config=config,
                run_dir=call.run_dir,
                target_repo=call.target,
                library=self.library,
                reviewing=(
                    reviewer,
                    ReviewInstall(path="/install", action="checked", seconds=0.0, entries=1),
                ),
                check=CanaryCheck(
                    held_out=frozenset(config.held_out_canaries), review_material=frozenset()
                ),
                make_call=make_call,
                review_root=root,
            )
        made.record.close()

    def drive(self, call: Drive) -> int:
        self.drives.append(call)
        if len(self.drives) in self.killed_in_drive:
            raise Killed
        run_dir = call.run_dir
        if call.resume:
            # As the command refuses it: before anything is built, written or started.
            waiting = limit_wait(run_dir, self.clock(), limit_reset=call.limit_reset)
            if waiting is not None:
                return EXIT_WAITING_FOR_LIMIT
        config = load_run_config(run_dir / "run.json")
        replaced = None
        if self.secret is not None:
            # The command's own account check, before anything is built (``_drive_run``).
            credential = Credential(mode=config.auth, secret=self.secret)
            try:
                replaced = orchestrator_cli._credential_replaced(
                    run_dir, config, credential, word=call.credential_replaced
                )
                if replaced is None:
                    held = account_in_effect(config, read_events(run_dir / "events.jsonl"))
                    require_same_account(config, credential, in_effect=held)
            except (RunConfigError, RunStateError):
                return 2  # as the command fails it: ``_fail``, exit 2
        run = RunGit(repo=call.target, run_dir=run_dir, run_id=config.run_id)
        plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
        keeper = StoreKeeper(run, run_dir / "store")
        session = AnswerSession(
            run,
            role="control",
            infra=self.infra,
            limited=self.limited,
            limit_resets_at=self.limit_resets_at,
            refused_credential=self.refused_credential,
            answer_name=self.answer_name,
            silent=self.silent,
            killed=self.killed,
            counter=self.sessions,
        )
        loop = Loop(
            config=config,
            run_dir=run_dir,
            gate=Gate(),
            reviewers={
                r: Reviewer(model=m, ids=uuid.uuid4().hex[:6])
                for r, m in config.models.reviewers.items()
            },
            dispatcher=session,
            changes=GitChangeChecker(
                run, run_dir / "store", {e.subtask_id: e.module_dir for e in plan}
            ),
            merger=GitMerger(run, removal_timeout_s=60.0),
            graph=keeper,
            escalation=bind("rules"),
            material=CanaryCheck(
                held_out=frozenset(config.held_out_canaries), review_material=frozenset()
            ),
            sleep=lambda _: None,
            clock=self.clock,
        )
        word = "a person" if call.limit_reset else None
        try:
            step = (
                loop.resume(limit_reset_by=word, credential_replaced=replaced)
                if call.resume
                else loop.run()
            )
        except LimitNotResetError:
            return EXIT_WAITING_FOR_LIMIT
        finally:
            loop.close()
            keeper.close()
        # The command's own exit status for the step the run stopped at.
        return printed_step(step.kind, loop.state)[1]


@dataclass
class PlanReview:
    """The plan's reviewer, scripted by its driver: a pass, a session left running, or an error."""

    driver: StandInDriver
    n: int
    root: Path
    hook: SpawnHook | None = None

    @property
    def model(self) -> str:
        return PLAN_REVIEWER

    def record_spawns(self, hook: SpawnHook) -> None:
        self.hook = hook

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        session_id = f"plan-review-{self.n}-{uuid.uuid4().hex[:8]}"
        if self.n in self.driver.killed_in_review:
            self._left_running(session_id)
            raise Killed
        error = self.driver.review_errs.get(self.n)
        if error == "invocation_error":
            if self.driver.review_shows is not None:
                # Its session spawned, recorded and wrote its stream, and ended before the error;
                # the reviewer removes the session's credential once it ends, as the real one does.
                ended = self._left_running(session_id)
                ended.kill()
                ended.wait()
                session = self.root / session_id / "session"
                remove_secrets(session / "state", session / "config")
            msg = "the review was answered by a model other than the pinned one"
            raise InvocationError(msg)
        if error == "model_separation":
            msg = "a reviewer may not run on the designer's model"
            raise ModelSeparationError(msg)
        if error == "credential_refused":
            # The review's session ended on an API error the credential's refusal gave: no verdict
            # and the instrument's, as the reviewer reads it, with the session's own cause beside.
            spent = Usage(
                input_tokens=3,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )
            msg = "the session ended with credential_refused"
            raise ReviewUnavailableError(
                msg,
                cause="infrastructure",
                session_id=session_id,
                reviewer_model=PLAN_REVIEWER,
                usage=(MessageUsage(message_id=f"r{self.n}", usage=spent),),
                session_cause="credential_refused",
            )
        usage = Usage(
            input_tokens=5,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return ReviewResult(
            verdict="pass",
            finding="the plan holds",
            reviewer_model=PLAN_REVIEWER,
            session_id=session_id,
            usage=(MessageUsage(message_id=f"r{self.n}", usage=usage),),
            items=(
                ItemVerdict(
                    item="every interface names its consumers",
                    section="acceptance_criteria",
                    result="met",
                    evidence="the plan's one interface",
                ),
            ),
            rubric_sha256=hashlib.sha256(b"the design rubric, scripted").hexdigest(),
        )

    def _left_running(self, session_id: str) -> subprocess.Popen[bytes]:
        """A review session spawned and recorded as the reviewer does, then left running."""
        process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
            [sys.executable, "-c", "import time; time.sleep(300)", "--session-id", session_id],
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        started = None
        for _ in range(200):
            started = started_at(process.pid)
            if started is not None:
                break
            time.sleep(0.05)
        assert started is not None, "the review session's start time could not be read"
        self.driver.left_reviews.append((process.pid, session_id))
        session = self.root / session_id / "session"
        (session / "state").mkdir(parents=True)
        (session / "config").mkdir(parents=True)
        # A credential's file, as a session's login puts one, and the review's stream.
        (session / "state" / "key").write_text("not-a-key\n")
        shown = self.driver.review_shows or "the plan reads well"
        (session / "stdout.jsonl").write_text(
            json.dumps({"type": "assistant", "text": shown}) + "\n"
        )
        assert self.hook is not None
        self.hook(session_id, process.pid, started)
        return process


@dataclass
class Rig:
    """A stand-in store with a registered run root, a target and the round's other inputs."""

    root: Path
    made: StandInStore
    target: Path
    run_root: Path
    params: Path
    library: Path

    def inputs(self, **changes: Any) -> Inputs:  # noqa: ANN401
        fields: dict[str, Any] = {
            "store": self.made.store,
            "role": "control",
            "version": self.made.version,
            "tiers": ("visible",),
            "trials": 2,
            "seed_base": 100,
            "params": self.params,
            "run_root": self.run_root,
            "target_from": self.target,
            "install": self.root / "install",
            "prices": load_price_sheet(PRICES),
            "out": self.root / "out",
            "tasks": 1,
        }
        fields.update(changes)
        return Inputs(**fields)

    def task(self, tier: str = "visible") -> Task:
        """The first task of ``tier`` in the round's order: by its brief's digest."""
        return min(
            self.made.tasks[tier], key=lambda t: hashlib.sha256(t.brief.encode()).hexdigest()
        )

    def driver(self, **how: Any) -> StandInDriver:  # noqa: ANN401
        return StandInDriver(library=self.library, answer_name=self.task().answer.path, **how)


def make_rig(tmp_path: Path, *, store: dict[str, Any] | None = None, **params_changes: Any) -> Rig:  # noqa: ANN401
    """The rig; ``store`` is given to the stand-in store, the rest to the run parameters."""
    root = tmp_path.resolve()
    made = stand_in_store(root, **(store or {}))
    run_root = root / "runs"
    run_root.mkdir()
    add_run_root(made.store, "control", run_root)
    target = target_repo(root)
    path = root / "params.json"
    path.write_text(json.dumps(params(made, **params_changes)))
    library = build_fixture_library(root / "library")
    return Rig(root, made, target, run_root, path, library)
