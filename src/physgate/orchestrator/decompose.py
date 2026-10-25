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
the run's seed, writes each module's specification onto the run branch with each
interface node beside them as a contract a role session must read, writes every
interface node into the store (they are immutable from creation), commits the
store, and records the run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from physgate.contracts.pairs import ContractError, ContractPair, pairing_problems, plan_pairs
from physgate.gate.catalogue import shadowing_names
from physgate.hooks.settings import protected_in_a_worktree
from physgate.knowledge.library import LibraryError, put_into, read_library
from physgate.orchestrator.accounting import require_matching_totals
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.common import GateMode, NonEmptyStr, first_problem
from physgate.orchestrator.credentials import (
    REDACTED_TEXT,
    Credential,
    remove_secrets,
    write_login,
)
from physgate.orchestrator.exceptions import DecompositionError, InvocationError, RunStateError
from physgate.orchestrator.git import commit_all, common_dir, git, init_repo
from physgate.orchestrator.invocation import (
    claude_binary,
    decomposition_argv,
    isolated_env,
    require_pinned,
    version_argv,
)
from physgate.orchestrator.managed import (
    ObservedTraffic,
    drift,
    flags_off_by_setting,
    observe_traffic,
    policy_limits_digest,
    system_managed_facts,
)
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.plan import INTEGRATION_MODULE_DIR as INTEGRATION_MODULE_DIR
from physgate.orchestrator.plan import REQUIREMENT_MAX_CHARS as REQUIREMENT_MAX_CHARS
from physgate.orchestrator.plan import SPEC_MAX_CHARS as SPEC_MAX_CHARS
from physgate.orchestrator.plan import Contribution as Contribution
from physgate.orchestrator.plan import IntegratedPlan as IntegratedPlan
from physgate.orchestrator.plan import InterfaceConsumers as InterfaceConsumers
from physgate.orchestrator.plan import Plan as Plan
from physgate.orchestrator.plan import PlannedModule as PlannedModule
from physgate.orchestrator.plan import SystemRequirement as SystemRequirement
from physgate.orchestrator.plan import list_problems as list_problems
from physgate.orchestrator.plan import plan_sha256 as plan_sha256
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.record import (
    DecompositionCall,
    DecompositionSummary,
    PlanEntry,
    RunRecord,
)
from physgate.orchestrator.run_config import RunConfig
from physgate.reviewers.contract import issued_criteria
from physgate.roles import CrossCuttingDuty, owners_of
from physgate.series.collect import series_library
from physgate.state.exceptions import MalformedNodeIdError
from physgate.state.schema import Node, validate_node_id
from physgate.state.store import Store

#: Where the run branch holds each interface node the decomposition planned, one JSON file
#: per node named by its id, written in the commit that issues the specifications. Every
#: file there is required reading for every role session of the run (ARCH-020).
INTERFACES_DIR = ".physgate/interfaces"


def interface_contract(node_id: str) -> str:
    """Where the run branch holds the interface node ``node_id``, relative to a worktree."""
    return f"{INTERFACES_DIR}/{node_id}.json"


#: The most interface nodes a plan may hold. Every role session must Read every interface
#: contract of its run before any other tool, one Read and so one turn each, on top of its
#: knowledge files and its specification. The smallest turn budget any recorded run has
#: given a session is 80, and 20 contracts keep that preamble to a quarter of it; the
#: recorded plans have held one or two interface nodes. Checked as a plan problem, not put
#: on the schema, so the schema the decomposition call is sent stays as it was.
MAX_INTERFACE_NODES = 20


def contracts_of(nodes: Sequence[Node]) -> dict[str, str]:
    """Each interface node's contract file, by its path relative to a worktree."""
    return {interface_contract(node.id): node.model_dump_json(indent=2) + "\n" for node in nodes}


def interface_contracts(repo: Path, commit: str) -> tuple[str, ...]:
    """Every interface contract ``commit`` issued, relative to a worktree, sorted.

    Read from git's objects, never from a worktree, so nothing a session did in its own
    worktree can take a contract off the list. A commit from before contracts were
    issued holds none, and the answer is empty.

    Raises:
        GitError: git cannot list ``commit``.
    """
    listing = git(
        repo,
        *("ls-tree", "-r", "-z", "--name-only", "--full-tree", commit, f"{INTERFACES_DIR}/"),
        objects_only=True,
    )
    return tuple(sorted(name for name in listing.split("\0") if name))


FailureCause = Literal[
    "no_structured_output",
    "invalid_plan",
    "model_mismatch",
    "api_error",
    "credential_refused",
    "sandbox_unavailable",
    "schema_refused",
    "managed_settings_changed",
    "wall_clock",
    "turn_limit",
    "no_result",
    "unexpected_exit",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _in_run(duty: CrossCuttingDuty, roles: Sequence[str]) -> tuple[str, ...]:
    """The run's roles that the register names as owning ``duty``, asked of it now.

    Found by what they own, never by a name, as the hook and the apply step find them.
    """
    owners = owners_of(duty)
    return tuple(role for role in sorted(set(roles)) if role in owners)


def plan_model(roles: Sequence[str]) -> type[Plan]:
    """The plan's form for a run of ``roles``: integration's, where the run has that role."""
    return IntegratedPlan if _in_run("completion", roles) else Plan


#: Root-level keys that name the schema rather than shape the answer. Left in, they
#: invite a wrapper: measured on the real API, the model answered with the whole
#: plan inside a ``"Plan"`` key, which the root's title names.
_ROOT_NAMING = ("title", "description", "$id", "$comment")


def plan_schema(roles: Sequence[str]) -> str:
    """The JSON schema the structured answer is held to by the binary, unnamed at its root.

    The schema of the plan's form for a run of ``roles`` (:func:`plan_model`). A run
    without the integration role is sent the base plan's, byte for byte as before that
    role was planned for.
    """
    model = plan_model(roles)
    schema = {k: v for k, v in model.model_json_schema().items() if k not in _ROOT_NAMING}
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


#: How the binary reports a structured answer its schema check refused.
_SCHEMA_REFUSAL = "Output does not match required schema"


def schema_refusal(stdout: str) -> str | None:
    """The binary's refusal of a structured answer, if the stream holds one.

    With one turn, a refused answer ends the call at the turn limit: the refusal
    is the cause, and it is read from the stream's tool result, since the result
    object says only that the turns ran out.
    """
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "user":
            continue
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            text = block.get("content")
            if isinstance(text, str) and text.startswith(_SCHEMA_REFUSAL):
                return text
    return None


def plan_problems(plan: Plan, roles: Sequence[str], brief: str) -> list[str]:
    """Everything wrong with a schema-valid plan that the schema cannot say.

    ``roles`` are the run's, and ``brief`` the brief the plan was made from: a system
    requirement is held to the criteria the brief numbers.
    """
    found: list[str] = []
    names = [m.name for m in plan.modules]
    dirs = [PurePosixPath(m.module_dir) for m in plan.modules]
    protected = protected_in_a_worktree()
    if len(set(names)) != len(names):
        found.append("two modules share a name")
    for module, path in zip(plan.modules, dirs, strict=True):
        if module.role not in roles:
            found.append(f"module {module.name!r} is assigned a role the run has no model for")
        if path.is_absolute() or ".." in path.parts or path.parts[:1] == (".physgate",):
            found.append(f"module {module.name!r} has a directory outside the modules' space")
        # Git refuses to add any path with a component named .git, whatever its case, so
        # what a session wrote there would be left out of its commit without a word.
        if any(part.casefold() == ".git" for part in path.parts):
            found.append(
                f"module {module.name!r} has a directory with a .git component, beneath which "
                "git records nothing a session writes"
            )
        for root, allowed in protected:
            if _overlap(path, root) and not any(_within(path, a) for a in allowed):
                found.append(
                    f"module {module.name!r} has a directory that overlaps {root}, which the "
                    "hooks protect from every session"
                )
    for i, one in enumerate(dirs):
        for other in dirs[i + 1 :]:
            if _overlap(one, other):
                found.append(f"module directories {one} and {other} overlap")
    ids = [n.id for n in plan.interface_nodes]
    if len(ids) > MAX_INTERFACE_NODES:
        found.append(
            f"the plan has {len(ids)} interface nodes; at most {MAX_INTERFACE_NODES} are "
            "allowed, since every session reads every contract before it works"
        )
    if len(set(ids)) != len(ids):
        found.append("two interface nodes share an id")
    owners = {m.role for m in plan.modules}
    for node in plan.interface_nodes:
        if node.kind != "interface":
            found.append(f"node {node.id!r} is not an interface node")
        if node.owner_role not in owners:
            found.append(f"interface node {node.id!r} is owned by a role no module has")
        # The same rule the hook and the apply step hold a session's proposal to: a name
        # that shadows a relation's quantity steps out of the relation without saying so.
        # The plan is written straight into the store, so the check is made here.
        for name, relation in shadowing_names(node.quantities):
            found.append(
                f"interface node {node.id!r} names {name!r}, which shadows {relation!r}, a "
                "quantity a relation reads; it is written under the catalogue's name"
            )
    return found + _cross_cutting_problems(plan, roles) + _integration_problems(plan, roles, brief)


def _overlap(one: PurePosixPath, other: PurePosixPath) -> bool:
    """Whether two module directories are one directory, or one holds the other.

    Compared with case folded, as a file system that ignores case (macOS's default, where
    runs are made) resolves them: there ``modules/Power`` and ``modules/power`` are one
    directory, and two modules given them would share it. A directory's name may hold
    upper case, so the comparison cannot be left to the names as written.
    """
    a, b = PurePosixPath(str(one).casefold()), PurePosixPath(str(other).casefold())
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _within(path: PurePosixPath, root: PurePosixPath) -> bool:
    """Whether ``path`` is ``root`` or lies beneath it, with case folded as in :func:`_overlap`."""
    return PurePosixPath(str(path).casefold()).is_relative_to(str(root).casefold())


def _cross_cutting_problems(plan: Plan, roles: Sequence[str]) -> list[str]:
    """What the plan gives a cross-cutting role of the run that it may not give it."""
    found: list[str] = []
    for owner in _in_run("cross_nodes", roles):
        count = sum(module.role == owner for module in plan.modules)
        if count > 1:
            found.append(
                f"the plan has {count} modules of the {owner} role; at most one is allowed, "
                "since that one module opens and closes the domain work"
            )
    for taken in _harness_names(plan, roles):
        for module in plan.modules:
            if module.name == taken:
                found.append(
                    f"module {module.name!r} is named {taken!r}, the name the harness gives a "
                    "subtask of its own"
                )
            elif module.name.startswith(f"{taken}-"):
                found.append(
                    f"module {module.name!r} is named for {taken!r}, the name the harness gives "
                    "a subtask of its own, with more after a hyphen"
                )
    completion = _in_run("completion", roles)
    if not completion:
        return found
    reserved = PurePosixPath(INTEGRATION_MODULE_DIR)
    for module in plan.modules:
        if module.role in completion:
            found.append(
                f"module {module.name!r} is assigned the {module.role} role, whose "
                "specification the harness writes from the plan"
            )
        if _overlap(PurePosixPath(module.module_dir), reserved):
            found.append(
                f"module {module.name!r} has a directory that overlaps {INTEGRATION_MODULE_DIR}, "
                "which the harness keeps for the integration subtask"
            )
    return found


def _integration_problems(plan: Plan, roles: Sequence[str], brief: str) -> list[str]:
    """What is wrong with the lists of what integration checks, or with their absence."""
    completion = _in_run("completion", roles)
    if not isinstance(plan, IntegratedPlan):
        if completion:
            return [
                f"the run has the {', '.join(completion)} role, and the plan has no list of "
                "the consumers and system requirements it checks"
            ]
        return []
    if not completion:
        return [
            "the plan lists consumers and system requirements, and the run has no "
            "integration role to check them"
        ]
    interfaces = [node.id for node in plan.interface_nodes]
    return (
        list_problems(interfaces, plan.interface_consumers, plan.system_requirements)
        + _consumer_problems(plan)
        + pairing_problems(plan)
        + _requirement_problems(plan, brief)
    )


def _consumer_problems(plan: IntegratedPlan) -> list[str]:
    """Every consumer the plan's modules cannot back.

    A consumer is a module of the plan, and a module of the node's producing role is never
    its consumer: the producer is the module of the role that owns the node. What needs
    only the lists and the nodes' ids (an entry for an unknown node, a node with none or
    two, a consumer named twice) is :func:`list_problems`'s.
    """
    found: list[str] = []
    role_of = {module.name: module.role for module in plan.modules}
    producer_of = {node.id: node.owner_role for node in plan.interface_nodes}
    for entry in plan.interface_consumers:
        if entry.interface not in producer_of:
            continue
        for consumer in entry.consumers:
            role = role_of.get(consumer)
            if role is None:
                found.append(
                    f"interface node {entry.interface!r} names {consumer!r} as a consumer, "
                    "which is no module of the plan"
                )
            elif role == producer_of[entry.interface]:
                found.append(
                    f"interface node {entry.interface!r} names {consumer!r} as a consumer, "
                    f"which is a module of its producing role {role!r}"
                )
    return found


def _requirement_problems(plan: IntegratedPlan, brief: str) -> list[str]:
    """Every system requirement the plan or the brief cannot back.

    A contributing criterion is one the module's specification numbers under its
    acceptance criteria, the same reading its reviewer is held to. Where the brief
    numbers its own acceptance criteria, a requirement is one of those numbers. A
    requirement listed twice is :func:`list_problems`'s.
    """
    found: list[str] = []
    numbered = issued_criteria(brief)
    criteria_of = {module.name: issued_criteria(module.spec) or () for module in plan.modules}
    for entry in plan.system_requirements:
        if numbered is not None and entry.requirement not in numbered:
            found.append(
                f"system requirement {entry.requirement!r} is not one of the brief's numbered "
                f"acceptance criteria ({', '.join(numbered)})"
            )
        for part in entry.contributing:
            if part.module not in criteria_of:
                found.append(
                    f"system requirement {entry.requirement!r} names {part.module!r}, which is "
                    "no module of the plan"
                )
            elif part.criterion not in criteria_of[part.module]:
                found.append(
                    f"system requirement {entry.requirement!r} names criterion "
                    f"{part.criterion!r} of {part.module!r}, which that module's specification "
                    "does not number under its acceptance criteria"
                )
    return found


#: The sentences the prompt gains in a run with the integration role: the system
#: requirements, and how the module criteria they cite are numbered, which is the form
#: the plan check and the reviewers read a criterion's number in.
REQUIREMENTS_SENTENCE = (
    "List each requirement of the brief that only the assembled system can show, with the "
    "module criteria that contribute to it."
)
NUMBERING_SENTENCE = (
    'Number each module\'s acceptance criteria "1.", "2." and so on under a '
    '"## Acceptance criteria" heading in its specification, since the system requirements '
    "cite them by number."
)


def _one_module_sentence(role: str) -> str:
    """The one sentence the prompt gains for the role that owns the cross nodes."""
    return (
        f"At most one module may have the {role} role: it alone writes the quantities more "
        "than one domain depends on, such as a motor's torque and current or a battery's "
        "capacity, and the other modules read them."
    )


def prompt_for(brief: str, roles: Sequence[str]) -> str:
    """The decomposition prompt: a fixed template around the brief.

    A cross-cutting role of the run adds its sentences: sizing's, that it has one module
    at most; integration's, which ask for the system requirements and for module criteria
    numbered as they are read. Integration is not offered as a module's role, since the
    harness writes its specification. A run with neither is sent the template as it was
    before either was planned for.
    """
    completion = _in_run("completion", roles)
    offered = sorted(role for role in roles if role not in completion)
    added = "".join(f"{_one_module_sentence(role)}\n\n" for role in _in_run("cross_nodes", roles))
    if completion:
        added += f"{REQUIREMENTS_SENTENCE}\n\n{NUMBERING_SENTENCE}\n\n"
    return (
        "Decompose the design brief below into modules, one per role that has work to do, "
        "and the interface nodes between them.\n\n"
        f"Roles available: {', '.join(offered)}.\n\n"
        "For each module give a short lowercase name, its role, a directory of its own "
        "under modules/ that no other module's directory contains, and a specification "
        "an implementer can work from. For each interface give one graph node of kind "
        '"interface", owned by the role that produces it, with every quantity as a value, a '
        "unit, a source and the role that wrote it.\n\n"
        f"{added}"
        "Answer by calling StructuredOutput once.\n\n"
        f"Brief:\n{brief}\n"
    )


#: The decomposition call's debug log, read for the catalog and flag state, then removed.
DEBUG_LOG = "debug.log"


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
    #: The digest of the policy limits the call received, ``None`` if none (or no call).
    policy_limits_sha256: str | None = None
    #: The served catalog and feature flags as the call's debug log showed them.
    observed_traffic: ObservedTraffic | None = None


def read_stream(
    stdout: str,
) -> tuple[dict[str, Any] | None, tuple[MessageUsage, ...], frozenset[str]]:
    """The result object, the per-message usage and the answering models of a stream.

    Usage is each message's **final** usage, taken once per message id. The
    ``assistant`` events carry the usage the message started with, and it is
    repeated once per content block; measured against the real API, that
    recorded 2 output tokens for a message whose result counted 673. The final
    usage is in the message's ``message_delta`` event, which the stream holds only
    with ``--include-partial-messages``; it follows the message's own
    ``message_start`` in the same thread. A message with no ``message_delta``
    (a session killed mid-message) keeps the usage it started with.

    The answering model is each assistant message's own
    ``model``, not the result's ``modelUsage``: measured on 2.1.272 with the
    endpoint answering as another model, ``modelUsage`` still named the model
    that was asked for, and only the messages named the one that answered. A
    line that is not JSON is skipped, not trusted.
    """
    # The binary's JSON stream is an untyped boundary: its events are read as
    # plain objects, and only the fields named here are taken from them.
    result: dict[str, Any] | None = None
    raw_usage: dict[str, dict[str, Any]] = {}
    current: dict[str | None, str] = {}  # the open message per thread
    models: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "result":
            result = event
        elif kind == "stream_event" and isinstance(event.get("event"), dict):
            inner, thread = event["event"], event.get("parent_tool_use_id")
            started = inner.get("message") if inner.get("type") == "message_start" else None
            if isinstance(started, dict) and isinstance(started.get("id"), str):
                current[thread] = started["id"]
                raw_usage.setdefault(started["id"], dict(started.get("usage") or {}))
            elif inner.get("type") == "message_delta" and thread in current:
                raw_usage[current[thread]].update(inner.get("usage") or {})
        message = event.get("message") if kind == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            raw_usage.setdefault(message["id"], dict(message.get("usage") or {}))
            if isinstance(message.get("model"), str):
                models.add(message["model"])
    usages = tuple(
        MessageUsage(
            message_id=message_id,
            usage=Usage(
                input_tokens=int(raw.get("input_tokens") or 0),
                output_tokens=int(raw.get("output_tokens") or 0),
                cache_read_input_tokens=int(raw.get("cache_read_input_tokens") or 0),
                cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens") or 0),
            ),
        )
        for message_id, raw in raw_usage.items()
    )
    return result, usages, frozenset(models)


def judge(
    # The result object from the binary's JSON stream: an untyped boundary.
    result: dict[str, Any] | None,
    *,
    exit_code: int | None,
    timed_out: bool,
    model: str,
    roles: Sequence[str],
    answered: frozenset[str],
    brief: str,
    refused: str | None = None,
) -> tuple[FailureCause | None, str, Plan | None, str | None, int]:
    """Decide from the result object whether the call produced a usable plan.

    The answer is read as the plan's form for a run of ``roles`` and held to the
    ``brief`` it was planned from. ``refused`` is the binary's schema refusal from the
    stream, if any: a call that ran out of turns after one is ``schema_refused``, not
    ``turn_limit``.
    """
    end = classify_session_end(result, exit_code=exit_code, stopped_at_wall_clock=timed_out)
    turns = int((result or {}).get("num_turns") or 0)
    echoed = sorted(answered)
    seen_model = echoed[0] if len(echoed) == 1 else None
    if refused is not None and end.cause == "turn_limit":
        return "schema_refused", refused, None, seen_model, turns
    if end.cause is not None:
        return end.cause, f"the call ended with {end.cause}", None, seen_model, turns
    if echoed != [model]:
        return "model_mismatch", f"asked for {model}, answered by {echoed}", None, seen_model, turns
    answer = (result or {}).get("structured_output")
    if answer is None:
        return "no_structured_output", "the call succeeded with no plan", None, seen_model, turns
    try:
        plan = plan_model(roles).model_validate_json(json.dumps(answer))
    except ValidationError as exc:
        return "invalid_plan", first_problem(exc), None, seen_model, turns
    problems = plan_problems(plan, roles, brief)
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
        schema=plan_schema(roles),
        model=config.models.decomposition,
        session_id=session_id,
        settings=settings,
        effort=config.effort,
        debug_file=workdir / DEBUG_LOG,
    )
    env = isolated_env(
        home=workdir / "home",
        config_dir=workdir / "config",
        binary=binary,
        claude_version=reported,
        max_retries=config.bounds.binary_max_retries,
        max_output_tokens=config.max_output_tokens,
        base_url=base_url,
        api_key=credential.secret if credential.mode == "api_key" else None,
    )
    system_before = system_managed_facts()
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
        observed = read_debug_log(
            workdir / DEBUG_LOG, flags_off_by_setting=flags_off_by_setting(reported, env)
        )
    (workdir / "stdout.jsonl").write_text(stdout.replace(credential.secret, REDACTED_TEXT))
    result, usage, answered = read_stream(stdout)
    require_matching_totals(result, usage)
    cause, detail, plan, model, turns = judge(
        result,
        exit_code=exit_code,
        timed_out=timed_out,
        model=config.models.decomposition,
        roles=roles,
        answered=answered,
        brief=brief,
        refused=schema_refusal(stdout),
    )
    changed = drift(workdir / "config", system_before)
    if not observed.all_off():
        seen = (
            f"the binary's served model catalog is {observed.served_catalog} and its remote "
            f"feature flags are {observed.feature_flags}"
        )
        changed = f"{changed}; {seen}" if changed else seen
    if changed is not None:
        cause, detail, plan = "managed_settings_changed", changed, None
    return Outcome(
        session_id=session_id,
        ok=cause is None,
        cause=cause,
        detail=detail,
        plan=plan,
        usage=usage,
        model=model,
        num_turns=turns,
        policy_limits_sha256=policy_limits_digest(workdir / "config"),
        observed_traffic=observed,
    )


def read_debug_log(path: Path, *, flags_off_by_setting: bool = False) -> ObservedTraffic:
    """What the call's debug log says about the catalog and the flags; the log is removed.

    The log is the binary's own and may hold anything the call saw, a credential
    included, so it never stays in the run directory: only the closed-vocabulary
    reading of it is kept. A log that is missing reads as nothing reported off.
    """
    try:
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        text = ""
    finally:
        path.unlink(missing_ok=True)
    return observe_traffic(text, flags_off_by_setting=flags_off_by_setting)


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


def _blob_id(data: bytes, object_format: str) -> str:
    """The id git gives ``data`` as a file's content, in the repository's object format."""
    header = f"blob {len(data)}\0".encode()
    digest = hashlib.sha256 if object_format == "sha256" else hashlib.sha1
    return digest(header + data).hexdigest()


def _require_library_fits(repo: Path, commit: str, curated: Mapping[Path, bytes]) -> None:
    """Refuse a target whose ``commit`` holds other content where the curated library goes.

    Read from git, not from any working tree, so it judges exactly the commit the
    run branch starts from. Identical bytes in an ordinary file pass, and the copy
    then leaves them as they are; anything else is refused, never overwritten.

    Raises:
        DecompositionError: a file with other bytes, a link or a directory where a
            curated file goes, or a file or link where one of its directories goes.
    """
    if not curated:
        return
    listing = git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, objects_only=True)
    entries: dict[str, tuple[str, str]] = {}
    for item in listing.split("\0"):
        if item:
            meta, name = item.split("\t", 1)
            mode, _, oid = meta.split()
            entries[name] = (mode, oid)
    # The clean store is created with the repository's object format, so it reports the same.
    object_format = git(repo, "rev-parse", "--show-object-format", objects_only=True).strip()
    for relative, data in sorted(curated.items()):
        name = relative.as_posix()
        parts = name.split("/")
        for depth in range(1, len(parts)):
            above = "/".join(parts[:depth])
            if above in entries:
                msg = "the target holds something other than a directory where the library goes"
                raise DecompositionError(msg, path=above)
        if any(other.startswith(name + "/") for other in entries):
            msg = "the target already holds a different file where the curated library goes"
            raise DecompositionError(msg, path=name)
        if name in entries:
            mode, oid = entries[name]
            if mode not in ("100644", "100755") or oid != _blob_id(data, object_format):
                msg = "the target already holds a different file where the curated library goes"
                raise DecompositionError(msg, path=name)


#: The sentence integration's specification states the run's gate mode in, one per mode. The
#: checks are the gate's: with them off there is no system-scope result to read, by design.
#: Observing blocks no merge, but completion is a declaration, not work: a failed
#: system-scope result withholds it whether the checks block or only observe, and with them
#: off completion has no system-scope precondition.
GATE_MODE_SENTENCES: Mapping[GateMode, str] = {
    "on": (
        "The run's automated design-quantity checks are on, and a failed system-scope result "
        "withholds completion."
    ),
    "observe": (
        "The run's automated design-quantity checks are on, and they block nothing; a failed "
        "system-scope result still withholds completion."
    ),
    "off": (
        "The run's automated design-quantity checks are off: there is no system-scope result, "
        "and completion has no system-scope precondition."
    ),
}

#: What the closing pass's subtask is named after: the sizing module's own name, then this.
CLOSING_SUFFIX = "-closing"


def _closing_name(module: str) -> str:
    """The name the closing pass over ``module`` is minted from."""
    return f"{module}{CLOSING_SUFFIX}"


def _harness_names(plan: Plan, roles: Sequence[str]) -> tuple[str, ...]:
    """The names the harness mints its own subtasks from, in a run of ``roles``.

    The closing pass's, after each module of the role that owns the cross nodes, and the
    name of the role that owns completion, for integration's subtask: the names
    :func:`_planned_subtasks` mints them from. A plan module may take none of them.
    """
    sizing = _in_run("cross_nodes", roles)
    closing = tuple(_closing_name(m.name) for m in plan.modules if m.role in sizing)
    return closing + _in_run("completion", roles)


@dataclass(frozen=True)
class _Issued:
    """One subtask as the run plans it: its ledger entry, its module and its specification."""

    entry: PlanEntry
    module: str
    spec: str


def _quoted(text: str) -> str:
    """``text`` as one JSON string: untrusted words, kept on one line, whatever they hold.

    Escaped to ASCII, so no character the specification's readers split lines on (a
    line or paragraph separator among them) survives to start a heading or a numbered
    criterion of its own.
    """
    return json.dumps(text)


def _issued(
    seed: int, index: int, *, minted: str, module: str, role: str, module_dir: str, spec: str
) -> _Issued:
    """The subtask whose id is minted from ``minted`` at ``index``, working on ``module``.

    Raises:
        DecompositionError: ``spec`` is longer than a module's may be. A plan module's is
            held to it by the schema; one the harness writes is held to it here, since the
            plan's words are quoted into it and can make it longer than they are.
    """
    subtask_id = mint_id(seed, index, minted)
    if len(spec) > SPEC_MAX_CHARS:
        msg = "the specification of a subtask is longer than a module's may be"
        raise DecompositionError(
            msg, subtask=subtask_id, length=str(len(spec)), limit=str(SPEC_MAX_CHARS)
        )
    entry = PlanEntry(
        subtask_id=subtask_id,
        spec_path=f".physgate/specs/{subtask_id}.md",
        assigned_role=role,
        module_dir=module_dir,
    )
    return _Issued(entry=entry, module=module, spec=spec)


def _line_of(issued: _Issued) -> str:
    entry = issued.entry
    return (
        f"- `{entry.subtask_id}`: module {_quoted(issued.module)}, role "
        f"{_quoted(entry.assigned_role)}, directory `{entry.module_dir}`"
    )


def _closing_spec(opening: _Issued, domains: Sequence[_Issued]) -> str:
    """The closing pass's specification: revisit what the domain work changed (ARCH-051).

    Written from the recorded plan before any module runs, so it names the subtasks and
    never what they will write; what changed is read from the design graph when it runs.
    """
    role = _quoted(opening.entry.assigned_role)
    ran = [_line_of(one) for one in domains] or ["- none: the plan has no domain module"]
    return "\n".join(
        [
            f"# Closing pass of the {role} role",
            "",
            "The harness wrote this specification from the recorded plan. It is the second "
            f"pass of the {role} role over module {_quoted(opening.module)}, in "
            f"`{opening.entry.module_dir}`, placed after every domain module below. The first "
            f"pass, subtask `{opening.entry.subtask_id}`, was issued "
            f"`{opening.entry.spec_path}`; read it for what this module owns.",
            "",
            "The domain modules that ran between the two passes:",
            "",
            *ran,
            "",
            "## Acceptance criteria",
            "",
            f"1. Every node of the {role} role is read again, with every node it constrains "
            "and every node that constrains it, as the design graph holds them now.",
            "2. Where a node read under criterion 1 changed after the first pass, each node of "
            f"the {role} role joined to it is rewritten to agree with it, or keeps its values "
            "and states why in its `no_change_justified`, under the changed node's id.",
            "3. No node of another role is written.",
            "",
        ]
    )


def _integration_spec(plan: IntegratedPlan, checked: Sequence[_Issued], gate_mode: GateMode) -> str:
    """Integration's specification: what it checks, fixed by the plan before any module runs.

    The run's gate mode, every subtask it checks, each interface with its producing role
    and consumers, and the system requirements the plan allocated to it (ARCH-051). Every
    word the plan holds is quoted on one line (:func:`_quoted`).
    """
    consumers = {entry.interface: entry.consumers for entry in plan.interface_consumers}
    interfaces = []
    for node in plan.interface_nodes:
        readers = consumers.get(node.id, ())
        read = (
            f"read by module{'s' if len(readers) > 1 else ''} "
            + ", ".join(_quoted(name) for name in readers)
            if readers
            else "read by no module the plan names"
        )
        interfaces.append(
            f"- {_quoted(node.id)}: produced by the {_quoted(node.owner_role)} role; {read}; "
            f"contract `{interface_contract(node.id)}`"
        )
    requirements = [
        f"- {_quoted(item.requirement)}: "
        + "; ".join(
            f"criterion {_quoted(part.criterion)} of module {_quoted(part.module)}"
            for part in item.contributing
        )
        for item in plan.system_requirements
    ] or ["The plan allocates no system requirement to integration."]
    return "\n".join(
        [
            "# Integration",
            "",
            "The harness wrote this specification from the recorded plan. Integration checks "
            "the modules below together, after each of them has merged: every quantity of "
            "every interface node against its producer and each of its consumers, the "
            "modules' analysis and test scripts run together on the merged design, and the "
            "system requirements below. It writes no node and no file another role owns, and "
            "it declares a module complete only when every precondition holds.",
            "",
            GATE_MODE_SENTENCES[gate_mode],
            "",
            "## Subtasks it checks",
            "",
            "Each subtask with its module, the module's role and directory, and the "
            "specification it was issued.",
            "",
            *(f"{_line_of(one)}, specification `{one.entry.spec_path}`" for one in checked),
            "",
            "## Interfaces",
            "",
            "Each interface node with the role that produces it, the modules that read it, and "
            "its contract.",
            "",
            *interfaces,
            "",
            "## System requirements",
            "",
            "Each requirement of the brief that only the assembled system can show, as the "
            "plan gives it (the brief's criterion number, or the brief's words), with the "
            "module criteria that contribute to it.",
            "",
            *requirements,
            "",
            "## Acceptance criteria",
            "",
            "1. Every quantity of every interface node above has a clause line for each of its "
            "consumers, judged from the producer's and the consumer's own files and nodes.",
            "2. Every module's analysis and test scripts are run together on the merged design, "
            "and each run is recorded with its command, commit, exit status and output.",
            "3. Each system requirement above is shown verified at system level, with its "
            "evidence, or named as not verified.",
            "4. The system-scope result is reported as recorded or, with the checks off, the "
            "record says there is none.",
            "5. A module is declared complete only when every precondition holds, each with its "
            "evidence; a module with an open precondition is listed as not complete, with the "
            "open item named.",
            "6. The record states what was exercised and what was not.",
            "7. No node and no file of another role is written.",
            "",
        ]
    )


def _planned_subtasks(plan: Plan, config: RunConfig) -> list[_Issued]:
    """The run's subtasks in the order the harness runs them, each with its specification.

    The order is the harness's, never the plan's (ARCH-051): the module of the role that
    owns the cross nodes opens the domain work; the domain modules follow in the plan's
    order; a second pass of that role over its own module and directory closes it; the
    role that owns completion ends the run. The closing pass and integration are no
    modules of the plan: the harness writes their specifications here. A plan module keeps
    the id its place in the plan mints; the harness's own take the indices after the
    plan's, in the order they run. A run with neither role is planned as before either
    existed.

    Raises:
        DecompositionError: the plan is not of the form the run's roles call for, its lists
            break the rules the run-event log holds them to, a specification is longer than
            a module's may be, or two subtasks were minted one id.
    """
    roles = sorted(config.models.roles)
    sizing, completion = _in_run("cross_nodes", roles), _in_run("completion", roles)
    if isinstance(plan, IntegratedPlan) != bool(completion):
        msg = "the plan is not of the form the run's roles call for"
        raise DecompositionError(
            msg, integrated=str(isinstance(plan, IntegratedPlan)), completion=", ".join(completion)
        )
    if isinstance(plan, IntegratedPlan):
        # The plan check holds them first; held again here, before anything is written,
        # since the line that records them is refused on these rules.
        problems = list_problems(
            [node.id for node in plan.interface_nodes],
            plan.interface_consumers,
            plan.system_requirements,
        )
        if problems:
            msg = "the plan's lists of what integration checks break its rules: " + "; ".join(
                problems
            )
            raise DecompositionError(msg)
    ordered = sorted(enumerate(plan.modules), key=lambda pair: pair[1].role not in sizing)
    planned = [
        _issued(
            config.seed,
            i,
            minted=m.name,
            module=m.name,
            role=m.role,
            module_dir=m.module_dir,
            spec=m.spec,
        )
        for i, m in ordered
    ]
    openings = [one for one in planned if one.entry.assigned_role in sizing]
    domains = [one for one in planned if one.entry.assigned_role not in sizing]
    index = len(plan.modules)
    for opening in openings:
        planned.append(
            _issued(
                config.seed,
                index,
                minted=_closing_name(opening.module),
                module=opening.module,
                role=opening.entry.assigned_role,
                module_dir=opening.entry.module_dir,
                spec=_closing_spec(opening, domains),
            )
        )
        index += 1
    if isinstance(plan, IntegratedPlan):
        spec = _integration_spec(plan, tuple(planned), config.gate_mode)
        for role in completion:
            planned.append(
                _issued(
                    config.seed,
                    index,
                    minted=role,
                    module=role,
                    role=role,
                    module_dir=INTEGRATION_MODULE_DIR,
                    spec=spec,
                )
            )
            index += 1
    ids = Counter(one.entry.subtask_id for one in planned)
    if len(ids) != len(planned):
        msg = "two subtasks of the plan were minted one id"
        repeated = sorted(i for i, n in ids.items() if n > 1)
        raise DecompositionError(msg, ids=", ".join(repeated))
    return planned


def start_run(
    outcome: Outcome,
    *,
    config: RunConfig,
    run_dir: Path,
    target_repo: Path,
    library: Path | None,
) -> RunRecord:
    """Start the run from the call's outcome: record a failure, or write the plan.

    The subtasks are planned in the harness's order (:func:`_planned_subtasks`), each
    with its specification. With them, the run branch gets the curated library every
    planned role reads, copied from ``library`` (the checkout the orchestrator runs
    from) byte for byte, in the same commit. The run records the plan's digest, taken
    from the plan itself (an outcome's dump is of the base form and drops an integrated
    plan's lists), and, in a run with the integration role, the two lists it checks.

    Raises:
        RunStateError: the run directory already holds a run.
        DecompositionError: the plan is not of the form the run's roles call for, two
            subtasks were minted one id, an interface node's id is not a node id, the
            store refused an interface node the plan validated, or the curated library
            cannot be put into the target: a planned role's
            file missing or empty, or the target holding other bytes where it goes.
    """
    require_fresh(run_dir)
    curated: dict[Path, bytes] = {}
    planned: list[_Issued] = []
    pairs: tuple[ContractPair, ...] | None = None
    if outcome.ok and outcome.plan is not None:
        # Before anything is written: a refusal here leaves no run record, no run
        # branch and no worktree behind, so the same run directory can be used again.
        planned = _planned_subtasks(outcome.plan, config)
        pairs = _contract_pairs(outcome.plan, planned)
        try:
            curated = read_library(library, (one.entry.assigned_role for one in planned))
        except LibraryError as exc:
            raise DecompositionError(str(exc), **exc.context) from None
        # The series writer goes with the library: a role's scripts import it from
        # .physgate/lib, and the run branch holds the very bytes the harness ships.
        curated.update(series_library())
        _require_library_fits(target_repo, config.target_head, curated)
        # A contract's file is named by its node's id, so an id that is no node id would
        # name a file outside the contracts' directory; the store would refuse it only
        # after the specifications were committed.
        for node in outcome.plan.interface_nodes:
            try:
                validate_node_id(node.id)
            except MalformedNodeIdError as exc:
                msg = "an interface node's id is not a node id"
                raise DecompositionError(msg, node=node.id[:64], reason=str(exc)) from None
    store_root = run_dir / "store"
    record = RunRecord(config, run_dir)
    spent = DecompositionCall(session_id=outcome.session_id, usage=outcome.usage)
    if not outcome.ok or outcome.plan is None:
        record.fail_decomposition(spent, f"{outcome.cause}: {outcome.detail}")
        return record
    plan = outcome.plan
    entries = [one.entry for one in planned]
    run = RunGit(repo=target_repo, run_dir=run_dir, run_id=config.run_id)
    run.open_run_branch(config.target_head)
    try:
        put_into(run.integration, curated)
    except LibraryError as exc:
        raise DecompositionError(str(exc), **exc.context) from None
    for one in planned:
        (run.integration / ".physgate" / "specs").mkdir(parents=True, exist_ok=True)
        (run.integration / one.entry.spec_path).write_text(one.spec.rstrip("\n") + "\n")
    # Beside the specifications and in the same commit: what each role designs against.
    for relative, contract in contracts_of(plan.interface_nodes).items():
        (run.integration / relative).parent.mkdir(parents=True, exist_ok=True)
        (run.integration / relative).write_text(contract)
    spec_commit = commit_all(
        run.integration,
        f"Specifications for run {config.run_id}\n\n"
        "Written at decomposition, with the curated library each planned role reads.\n",
        linked=True,
        common=common_dir(run.repo),
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
    consumers, requirements = _lists(plan)
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
            policy_limits_sha256=outcome.policy_limits_sha256,
            observed_traffic=outcome.observed_traffic,
            plan_sha256=plan_sha256(plan),
            interface_consumers=consumers,
            system_requirements=requirements,
            contract_pairs=pairs,
        ),
    )
    return record


def _contract_pairs(plan: Plan, planned: Sequence[_Issued]) -> tuple[ContractPair, ...] | None:
    """The plan's contract pairs, with each module's subtask; ``None`` for a base plan.

    The plan modules are the first of ``planned``, one each, minted from their places in the
    plan; a closing pass and integration follow them and are no module of the plan.

    Raises:
        DecompositionError: the pairs cannot be formed, from a plan the plan check did not hold.
    """
    if not isinstance(plan, IntegratedPlan):
        return None
    subtask_of = {one.module: one.entry.subtask_id for one in planned[: len(plan.modules)]}
    try:
        return plan_pairs(plan, subtask_of)
    except ContractError as exc:
        raise DecompositionError(str(exc), **exc.context) from None


def _lists(
    plan: Plan,
) -> tuple[tuple[InterfaceConsumers, ...] | None, tuple[SystemRequirement, ...] | None]:
    """The two lists integration checks, as the plan holds them; ``None`` for a base plan."""
    if isinstance(plan, IntegratedPlan):
        return plan.interface_consumers, plan.system_requirements
    return None, None
