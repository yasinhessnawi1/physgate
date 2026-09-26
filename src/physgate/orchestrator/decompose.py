"""The run's one model call: a brief in, a plan out, and the run started from it.

ARCH-001 allows exactly one model call per run, here. It is one Claude Code
invocation with no tools but the structured answer and one turn, so it is one
request: a plain-text or schema-violating answer ends the call rather than the
binary asking again (measured). The answer is untrusted input. ``success`` from
the binary does not mean a plan was produced (measured: a plain-text answer can
end ``success`` with no structured output), so the plan is read from the
structured output, validated here, and a missing or invalid one fails the run.
A second call would be a second model call; a rerun is a new run.

From a valid plan the orchestrator, not the model, mints the subtask ids from
the run's seed, writes each module's specification onto the run branch, writes
every interface node into the store (they are immutable from creation), commits
the store, and records the run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.common import NonEmptyStr, first_problem
from physgate.orchestrator.credentials import (
    REDACTED_TEXT,
    Credential,
    remove_secrets,
    write_login,
)
from physgate.orchestrator.exceptions import DecompositionError, InvocationError, RunStateError
from physgate.orchestrator.git import commit_all, init_repo
from physgate.orchestrator.invocation import (
    claude_binary,
    decomposition_argv,
    isolated_env,
    require_pinned,
    version_argv,
)
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.record import (
    DecompositionCall,
    DecompositionSummary,
    PlanEntry,
    RunRecord,
)
from physgate.orchestrator.run_config import RunConfig
from physgate.state.schema import Node
from physgate.state.store import Store

FailureCause = Literal[
    "no_structured_output",
    "invalid_plan",
    "model_mismatch",
    "api_error",
    "credential_refused",
    "wall_clock",
    "turn_limit",
    "no_result",
    "unexpected_exit",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PlannedModule(_Frozen):
    """One module of the design, as the decomposition proposes it."""

    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
    role: NonEmptyStr
    module_dir: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}$")]
    spec: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class Plan(_Frozen):
    """The decomposition's answer: modules with their specifications, and interfaces."""

    modules: Annotated[tuple[PlannedModule, ...], Field(min_length=1, max_length=50)]
    interface_nodes: Annotated[tuple[Node, ...], Field(min_length=1)]


def plan_schema() -> str:
    """The JSON schema the structured answer is held to by the binary."""
    return json.dumps(Plan.model_json_schema(), sort_keys=True, separators=(",", ":"))


def plan_problems(plan: Plan, roles: Sequence[str]) -> list[str]:
    """Everything wrong with a schema-valid plan that the schema cannot say."""
    found: list[str] = []
    names = [m.name for m in plan.modules]
    dirs = [PurePosixPath(m.module_dir) for m in plan.modules]
    if len(set(names)) != len(names):
        found.append("two modules share a name")
    for module, path in zip(plan.modules, dirs, strict=True):
        if module.role not in roles:
            found.append(f"module {module.name!r} is assigned a role the run has no model for")
        if path.is_absolute() or ".." in path.parts or path.parts[:1] == (".physgate",):
            found.append(f"module {module.name!r} has a directory outside the modules' space")
    for i, one in enumerate(dirs):
        for other in dirs[i + 1 :]:
            if one == other or one.is_relative_to(other) or other.is_relative_to(one):
                found.append(f"module directories {one} and {other} overlap")
    ids = [n.id for n in plan.interface_nodes]
    if len(set(ids)) != len(ids):
        found.append("two interface nodes share an id")
    owners = {m.role for m in plan.modules}
    for node in plan.interface_nodes:
        if node.kind != "interface":
            found.append(f"node {node.id!r} is not an interface node")
        if node.owner_role not in owners:
            found.append(f"interface node {node.id!r} is owned by a role no module has")
    return found


def prompt_for(brief: str, roles: Sequence[str]) -> str:
    """The decomposition prompt: a fixed template around the brief."""
    return (
        "Decompose the design brief below into modules, one per role that has work to do, "
        "and the interface nodes between them.\n\n"
        f"Roles available: {', '.join(sorted(roles))}.\n\n"
        "For each module give a short lowercase name, its role, a directory of its own "
        "under modules/ that no other module's directory contains, and a specification "
        "an implementer can work from. For each interface give one graph node of kind "
        '"interface", owned by the role that produces it, with every quantity as a value, a '
        "unit, a source and the role that wrote it.\n\n"
        "Answer by calling StructuredOutput once.\n\n"
        f"Brief:\n{brief}\n"
    )


def mint_id(seed: int, index: int, name: str) -> str:
    """A subtask id from the run's seed: the orchestrator's choice, not the model's."""
    digest = hashlib.sha256(f"{seed}:{index}:{name}".encode()).hexdigest()[:6]
    return f"{name}-{digest}"


class Outcome(_Frozen):
    """What the one call produced."""

    session_id: NonEmptyStr
    ok: bool
    cause: FailureCause | None
    detail: str
    plan: Plan | None
    usage: tuple[MessageUsage, ...]
    model: str | None
    num_turns: int


def read_stream(
    stdout: str,
) -> tuple[dict[str, Any] | None, tuple[MessageUsage, ...], frozenset[str]]:
    """The result object, the per-message usage and the answering models of a stream.

    Usage is taken once per message id: the stream repeats a message's usage once
    per content block. The answering model is each assistant message's own
    ``model``, not the result's ``modelUsage``: measured on 2.1.272 with the
    endpoint answering as another model, ``modelUsage`` still named the model
    that was asked for, and only the messages named the one that answered. A
    line that is not JSON is skipped, not trusted.
    """
    # The binary's JSON stream is an untyped boundary: its events are read as
    # plain objects, and only the fields named here are taken from them.
    result: dict[str, Any] | None = None
    seen: dict[str, MessageUsage] = {}
    models: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            result = event
        message = event.get("message") if event.get("type") == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            raw = message.get("usage") or {}
            usage = Usage(
                input_tokens=int(raw.get("input_tokens") or 0),
                output_tokens=int(raw.get("output_tokens") or 0),
                cache_read_input_tokens=int(raw.get("cache_read_input_tokens") or 0),
                cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens") or 0),
            )
            seen.setdefault(message["id"], MessageUsage(message_id=message["id"], usage=usage))
            if isinstance(message.get("model"), str):
                models.add(message["model"])
    return result, tuple(seen.values()), frozenset(models)


def judge(
    # The result object from the binary's JSON stream: an untyped boundary.
    result: dict[str, Any] | None,
    *,
    exit_code: int | None,
    timed_out: bool,
    model: str,
    roles: Sequence[str],
    answered: frozenset[str],
) -> tuple[FailureCause | None, str, Plan | None, str | None, int]:
    """Decide from the result object whether the call produced a usable plan."""
    end = classify_session_end(result, exit_code=exit_code, stopped_at_wall_clock=timed_out)
    turns = int((result or {}).get("num_turns") or 0)
    echoed = sorted(answered)
    seen_model = echoed[0] if len(echoed) == 1 else None
    if end.cause is not None:
        return end.cause, f"the call ended with {end.cause}", None, seen_model, turns
    if echoed != [model]:
        return "model_mismatch", f"asked for {model}, answered by {echoed}", None, seen_model, turns
    answer = (result or {}).get("structured_output")
    if answer is None:
        return "no_structured_output", "the call succeeded with no plan", None, seen_model, turns
    try:
        plan = Plan.model_validate_json(json.dumps(answer))
    except ValidationError as exc:
        return "invalid_plan", first_problem(exc), None, seen_model, turns
    problems = plan_problems(plan, roles)
    if problems:
        return "invalid_plan", "; ".join(problems), None, seen_model, turns
    return None, "a plan", plan, seen_model, turns


def binary_version(binary: str | None = None) -> str:
    """The version the Claude Code binary reports, refused unless it is the pinned one.

    Recorded in every run's configuration and checked again before every spawn:
    a binary that updates itself would otherwise change the tool under
    measurement between two runs of one spec, or in the middle of one.

    Raises:
        InvocationError: there is no binary, or it reports another version.
    """
    found = binary or claude_binary()
    done = subprocess.run(
        version_argv(found), capture_output=True, text=True, check=False, timeout=60
    )
    return require_pinned(done.stdout)


def call(
    brief: str,
    *,
    config: RunConfig,
    workdir: Path,
    base_url: str | None,
    credential: Credential,
) -> Outcome:
    """Make the run's one model call, isolated, and judge what came back.

    The call has no tools, so no agent runs in it. An API key goes in its
    environment; a subscription token goes in as the binary's login file in the
    call's own configuration directory, removed when the call ends.
    """
    binary = claude_binary()
    reported = binary_version(binary)
    if reported != config.claude_version:
        msg = "the binary is not the version this run recorded"
        raise InvocationError(msg, reported=reported, recorded=config.claude_version)
    for name in ("home", "config", "cwd"):
        (workdir / name).mkdir(parents=True, exist_ok=True)
    settings = workdir / "settings.json"
    settings.write_text("{}\n")
    session_id = str(uuid.uuid4())
    roles = sorted(config.models.roles)
    argv = decomposition_argv(
        binary,
        prompt=prompt_for(brief, roles),
        schema=plan_schema(),
        model=config.models.decomposition,
        session_id=session_id,
        settings=settings,
    )
    env = isolated_env(
        home=workdir / "home",
        config_dir=workdir / "config",
        binary=binary,
        max_retries=config.bounds.binary_max_retries,
        base_url=base_url,
        api_key=credential.secret if credential.mode == "api_key" else None,
    )
    if credential.mode == "subscription":
        write_login(workdir / "config", credential.secret)
    try:
        done = subprocess.run(
            argv,
            cwd=workdir / "cwd",
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.bounds.session_wall_clock_s,
        )
        stdout, exit_code, timed_out = done.stdout, done.returncode, False
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        stdout = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        exit_code, timed_out = None, True
    finally:
        remove_secrets(workdir / "state", workdir / "config")
    (workdir / "stdout.jsonl").write_text(stdout.replace(credential.secret, REDACTED_TEXT))
    result, usage, answered = read_stream(stdout)
    cause, detail, plan, model, turns = judge(
        result,
        exit_code=exit_code,
        timed_out=timed_out,
        model=config.models.decomposition,
        roles=roles,
        answered=answered,
    )
    return Outcome(
        session_id=session_id,
        ok=cause is None,
        cause=cause,
        detail=detail,
        plan=plan,
        usage=usage,
        model=model,
        num_turns=turns,
    )


def require_fresh(run_dir: Path) -> None:
    """Refuse a run directory that already holds a run, before any token is spent.

    Raises:
        RunStateError: it holds a run's log, configuration or store.
    """
    if any((run_dir / name).exists() for name in ("events.jsonl", "run.json", "store")):
        msg = (
            "the run directory already holds a run; a rerun is a new run in a new directory. "
            "A directory left by an interrupted decomposition is inert: remove it by hand, "
            "nothing here deletes it"
        )
        raise RunStateError(msg, run_dir=str(run_dir))


def start_run(
    outcome: Outcome, *, config: RunConfig, run_dir: Path, target_repo: Path
) -> RunRecord:
    """Start the run from the call's outcome: record a failure, or write the plan.

    Raises:
        RunStateError: the run directory already holds a run.
        DecompositionError: the store refused an interface node the plan validated.
    """
    require_fresh(run_dir)
    store_root = run_dir / "store"
    record = RunRecord(config, run_dir)
    spent = DecompositionCall(session_id=outcome.session_id, usage=outcome.usage)
    if not outcome.ok or outcome.plan is None:
        record.fail_decomposition(spent, f"{outcome.cause}: {outcome.detail}")
        return record
    plan = outcome.plan
    entries: list[PlanEntry] = []
    run = RunGit(repo=target_repo, run_dir=run_dir, run_id=config.run_id)
    run.open_run_branch(config.target_head)
    for index, module in enumerate(plan.modules):
        subtask_id = mint_id(config.seed, index, module.name)
        spec_path = f".physgate/specs/{subtask_id}.md"
        (run.integration / ".physgate" / "specs").mkdir(parents=True, exist_ok=True)
        (run.integration / spec_path).write_text(module.spec.rstrip("\n") + "\n")
        entries.append(
            PlanEntry(
                subtask_id=subtask_id,
                spec_path=spec_path,
                assigned_role=module.role,
                module_dir=module.module_dir,
            )
        )
    spec_commit = commit_all(
        run.integration, f"Specifications for run {config.run_id}\n\nWritten at decomposition.\n"
    )
    store = Store(store_root)
    try:
        for node in plan.interface_nodes:
            payload = node.model_dump()
            written = store.write_node(payload, actor_role=node.owner_role)
            if not written.accepted:
                msg = "the store refused an interface node the plan validated"
                raise DecompositionError(msg, node=node.id, reason=str(written.reason))
        head = store.head_revision()
    finally:
        store.close()
    init_repo(store_root)
    commit_all(store_root, f"Interface nodes of run {config.run_id}, written at decomposition\n")
    record.start(
        entries,
        call=spent,
        decomposed=DecompositionSummary(
            session_id=outcome.session_id,
            model=outcome.model or config.models.decomposition,
            num_turns=outcome.num_turns,
            subtasks=len(entries),
            interface_nodes=tuple(n.id for n in plan.interface_nodes),
            spec_commit=spec_commit,
            head_revision=head,
        ),
    )
    return record
