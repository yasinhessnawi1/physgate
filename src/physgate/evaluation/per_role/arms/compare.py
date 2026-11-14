"""The two arms held equal: the raw arm's record against the harness run's, both read from disk.

The comparison is fair only if the raw arm differs from the harness arm in the harness
alone. So nothing here takes a pin from the caller: the harness run's configuration, event
log and role sessions' generated settings are read from its run directory, and the raw
arm's record, stream and generated settings from its own. Every difference is named.

**Nothing passes unclassed.** Every field of the harness run's recorded configuration is in
:data:`RUN_FIELDS` with how it bears on the raw arm, and every pin the raw arm records is
in :data:`RAW_PINS`. A field or a pin added later without a decision here is itself named
as a difference, so a new switch of the harness (an advisor, a tool environment) cannot be
compared as equal by being overlooked.

**The harness run must be one a baseline may be held to:** a run that is not reportable,
or whose checkout was not clean, is named as a difference whatever the raw arm did. The
fields recorded and not compared are listed in :data:`RUN_FIELDS`, each with its reason.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel

from physgate.evaluation.per_role.arms.raw import canaries_sha256
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.task import Task
from physgate.hooks.settings import CONFIG_NAME
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.dispatch import read_captured
from physgate.orchestrator.events import (
    LeftoverRead,
    SessionEnded,
    SessionSpawned,
    TokensUsed,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.replay import replay
from physgate.orchestrator.run_config import RunConfig, load_run_config

#: How each field of a harness run's recorded configuration bears on the raw arm, by its
#: path: every field of a model nested in the configuration has a decision of its own, so a
#: field added inside one (an advisor among the models, a new bound) is named like one
#: added at the top.
#:
#: - ``compared``: the raw arm records the same pin, and it must be equal (a nested field
#:   of a compared model is compared with it);
#: - ``nested``: a model whose fields are each decided by their own path;
#: - ``harness``: a part of the harness the raw arm is measured without;
#: - ``intended``: the raw arm differs on purpose, as its own code says;
#: - ``identity``: names the run, says nothing about how it answered;
#: - ``required``: the harness run must hold it, or it is no arm to compare against, and
#:   the pair is named whatever the raw arm did;
#: - ``not_compared``: recorded by the harness run and not held against the raw arm, each
#:   with its reason beside it.
RunFieldClass = Literal[
    "compared", "nested", "harness", "intended", "identity", "required", "not_compared"
]
RUN_FIELDS: dict[str, RunFieldClass] = {
    "auth": "compared",
    "brief_sha256": "compared",
    "claude_version": "compared",
    "effort": "compared",
    "endpoint": "compared",
    "held_out": "compared",
    # Compared as digests: the raw arm records its canaries' digest, never the canaries.
    "held_out_canaries": "compared",
    "max_output_tokens": "compared",
    # The model a role session of the task's role is pinned to: the raw arm's ``model``.
    "models": "nested",
    "models.roles": "compared",
    "models.decomposition": "harness",
    "models.reviewers": "harness",
    "network": "compared",
    "os_layer": "compared",
    "os_layer.state": "compared",
    "os_layer.mechanism": "compared",
    "os_layer.claude_version": "compared",
    "os_layer.reason": "compared",
    "os_layer.no_os_protection": "compared",
    "role_python": "compared",
    "role_python.path": "compared",
    "role_python.resolved": "compared",
    "role_python.version": "compared",
    "role_python.prefix": "compared",
    "role_python.distributions": "compared",
    "thinking_display": "compared",
    "gate_mode": "harness",
    "escalation_backend": "harness",
    "queue_decisions": "harness",
    # Whether the plan is reviewed before anything is dispatched; the raw arm has no plan.
    "design_review": "harness",
    # Whether a person is asked which parts they have; the raw arm has no plan to ask about.
    "parts_on_hand": "harness",
    # Who reviews a role's work, whether a role session is given its skill file, and whether
    # its hooks enforce the design discipline: the raw arm has no reviewer, library or hooks
    # of the harness's.
    "reviewers": "harness",
    "skills": "harness",
    "hooks": "harness",
    # The binary's retries and the infrastructure retry delays must be equal: retries in
    # the binary hide requests from the raw arm's cap. The turn and wall-clock bounds are
    # compared at the harness's times its repair budget, so neither binds before the cap.
    "bounds": "compared",
    "bounds.binary_max_retries": "compared",
    "bounds.infra_retry_delays_s": "compared",
    "bounds.session_max_turns": "compared",
    "bounds.session_wall_clock_s": "compared",
    # The hook layer's ceiling on what a session loads always; the raw agent loads nothing
    # always, so its ceiling is set where it never binds.
    "token_ceiling": "intended",
    "run_id": "identity",
    "seed": "identity",
    "target_head": "identity",
    # A reportable run starts from a clean checkout with a commit; a development run's
    # numbers are no baseline's.
    "harness": "required",
    "harness.clean": "required",
    # ``None`` exactly when the tree is clean.
    "harness.uncommitted_sha256": "required",
    "harness.commit": "identity",
    "reportable": "required",
    # An ablation run is never reportable, and a run that is not reportable is named already.
    "ablation": "not_compared",
    # The git the harness's own commands ran; the raw arm runs none of them.
    "git_binary": "not_compared",
    "git_binary.path": "not_compared",
    "git_binary.version": "not_compared",
    # The tier's digests as the harness run recorded them before it started; the raw arm
    # records the roots it withheld (``held_out``), not their digests.
    "held_out_sha256": "not_compared",
    # Measured from ``network`` and ``os_layer``, which are both compared.
    "network_enforced": "not_compared",
    # Whether the run may go on where the OS layer is absent; the layer each arm ran
    # with is compared (``os_layer``), and a reportable run allows no absence.
    "os_layer_absent": "not_compared",
    # The bytes the harness run executed, by digest and platform build. The raw arm records
    # its binary's version, which is compared, and not the digest of its bytes.
    "binary": "not_compared",
    "binary.sha256": "not_compared",
    "binary.platform": "not_compared",
    # The account the harness run's calls drew on; the raw arm records none.
    "account": "not_compared",
    "account.name": "not_compared",
    "account.token_sha256_prefix": "not_compared",
}

#: Every pin the raw arm's record carries. Each is compared below; one the record lacks,
#: or one it carries that is not here, is named.
RAW_PINS = frozenset(
    {
        "advisor",
        "answer",
        "auth",
        "bounds",
        "brief_sha256",
        "claude_version",
        "effort",
        "endpoint",
        "held_out",
        "held_out_canaries_sha256",
        "max_output_tokens",
        "model",
        "network",
        "os_layer",
        "role_python",
        "thinking_display",
    }
)


def run_field_paths(model: type[BaseModel] = RunConfig, prefix: str = "") -> set[str]:
    """Every field of ``model`` by its path, and every field of every model nested in it.

    A model is nested where a field's type names it: alone, optional, in a union or in a
    container.
    """
    found = set()
    for name, field in model.model_fields.items():
        found.add(prefix + name)
        for inner in _models_in(field.annotation):
            found |= run_field_paths(inner, f"{prefix}{name}.")
    return found


def _models_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for arg in get_args(annotation) for model in _models_in(arg)]


class ComparisonError(PerRoleError):
    """The two arms cannot be compared from what they recorded."""


def harness_total(run_dir: Path) -> int:
    """Every token the harness run spent, each message once: roles, reviewers, decomposition.

    The raw arm's cap is this total, so a total that undercounts makes the baseline quietly
    weaker. It is refused, never returned, when the log cannot show every token:

    - a line was cut off at the log's end;
    - a message's usage was read from a session a killed orchestrator left behind, with no
      result to check it against (``partial``), or such a session was read incomplete;
    - a role session was spawned and never ended or read;
    - the log is empty, or the run has not ended: its last step, replayed from the log as
      the loop takes it, is not done, halted or escalated. A run killed during a review,
      during its decomposition or between sessions spawned nothing left open, and is
      refused here.

    Raises:
        ComparisonError: the run's token account is not complete.
    """
    log = run_dir / "events.jsonl"
    data = log.read_bytes()
    if not data:
        msg = "the run's event log is empty; it shows no token the run spent"
        raise ComparisonError(msg, log=str(log))
    if not data.endswith(b"\n"):
        msg = "the run's event log ends in a cut-off line; its last tokens are not counted"
        raise ComparisonError(msg, log=str(log))
    events = parse_events(data, log=str(log))
    for event in events:
        if isinstance(event, TokensUsed) and event.partial:
            msg = "a message's usage in the run is partial; the run's total is a lower bound"
            raise ComparisonError(msg, seq=str(event.seq), attribution=event.attribution)
        if isinstance(event, LeftoverRead) and not event.complete:
            msg = "a session the run read at a resume was incomplete; its tokens are uncounted"
            raise ComparisonError(msg, seq=str(event.seq), session_id=event.session_id)
    spawned = {e.session_id for e in events if isinstance(e, SessionSpawned)}
    ended = {e.session_id for e in events if isinstance(e, SessionEnded | LeftoverRead)}
    if spawned - ended:
        msg = "a session of the run was spawned and never ended; its tokens are uncounted"
        raise ComparisonError(msg, sessions=",".join(sorted(spawned - ended)))
    try:
        step = replay(events).next_step().kind
    except CorruptEventLogError as exc:
        msg = "the run's event log does not replay as a run"
        raise ComparisonError(msg, log=str(log), reason=str(exc)) from None
    if step not in ("done", "halted", "escalated"):
        msg = "the run has not ended; what it would still have spent is uncounted"
        raise ComparisonError(msg, log=str(log), next_step=step)
    return TokenAccount.from_events(events).total().total()


def _tools(config_file: Path) -> tuple[str, str | None, list[str]]:
    """A generated session configuration's profile, role and tool list, as it was installed.

    Raises:
        ComparisonError: the file cannot be read, or does not have the installer's shape.
    """
    try:
        config = json.loads(config_file.read_bytes())
        profile, role, tools = config["profile"], config["role"], config["tools_allowed"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = "a session's generated configuration could not be read"
        raise ComparisonError(msg, file=str(config_file), error=repr(exc)) from None
    if not (
        isinstance(profile, str)
        and (role is None or isinstance(role, str))
        and isinstance(tools, list)
        and all(isinstance(t, str) for t in tools)
    ):
        msg = "a session's generated configuration does not have the installer's shape"
        raise ComparisonError(msg, file=str(config_file))
    return profile, role, sorted(tools)


def _harness_tools(run_dir: Path, role: str) -> list[list[str]]:
    """The tool list of every role session of ``role`` the run installed, one per session."""
    lists = []
    for config_file in sorted((run_dir / "sessions").glob(f"*/session/{CONFIG_NAME}")):
        profile, session_role, tools = _tools(config_file)
        if profile == "role" and session_role == role:
            lists.append(tools)
    return lists


def _expected(config: RunConfig, role: str, task: Task) -> dict[str, Any]:
    """Each raw pin as the harness run recorded it."""
    return {
        # No session of either arm is given an advisor today, and no run records one. The
        # field census names the run field that will record it until it is compared here.
        "advisor": None,
        "answer": task.answer.model_dump(mode="json"),
        "auth": config.auth,
        "bounds": {
            "binary_max_retries": config.bounds.binary_max_retries,
            "infra_retry_delays_s": list(config.bounds.infra_retry_delays_s),
            "session_max_turns": config.bounds.session_max_turns * REPAIR_BUDGET,
            "session_wall_clock_s": config.bounds.session_wall_clock_s * REPAIR_BUDGET,
        },
        "brief_sha256": config.brief_sha256,
        "claude_version": config.claude_version,
        "effort": config.effort,
        "endpoint": config.endpoint,
        "held_out": sorted(config.held_out),
        "held_out_canaries_sha256": canaries_sha256(config.held_out_canaries),
        "max_output_tokens": config.max_output_tokens,
        "model": config.models.roles.get(role),
        "network": config.network,
        "os_layer": None if config.os_layer is None else config.os_layer.model_dump(mode="json"),
        "role_python": (
            None if config.role_python is None else config.role_python.model_dump(mode="json")
        ),
        "thinking_display": config.thinking_display,
    }


def differences(run_dir: Path, raw_dir: Path, *, role: str, task: Task) -> list[str]:
    """Each way the raw arm differs from the harness run on ``task`` but the harness itself.

    ``run_dir`` is the harness run's directory; ``raw_dir`` is where the raw arm ran on
    the same task and trial (its ``raw.json``, its stream and its generated settings).
    An empty list is the only fair pair.

    Raises:
        ComparisonError: either arm's records cannot be read, or the harness run's token
            account is not complete (:func:`harness_total`).
    """
    config = load_run_config(run_dir / "run.json")
    try:
        record: dict[str, Any] = json.loads((raw_dir / "raw.json").read_bytes())
        pins: dict[str, Any] = record["pins"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = "the raw arm's record could not be read"
        raise ComparisonError(msg, raw_dir=str(raw_dir), error=repr(exc)) from None
    found = [
        f"run.json field {name!r}: no decision says how it bears on the raw arm"
        for name in sorted(run_field_paths(RunConfig) - set(RUN_FIELDS))
    ]
    found += [
        f"{name}: the raw arm recorded a pin no comparison knows"
        for name in sorted(set(pins) - RAW_PINS)
    ]
    found += [
        f"{name}: the raw arm's record does not carry this pin"
        for name in sorted(RAW_PINS - set(pins))
    ]
    found += [
        f"{name}: the harness ran with {want!r}, the raw arm with {pins[name]!r}"
        for name, want in _expected(config, role, task).items()
        if name in pins and pins[name] != want
    ]
    if not config.reportable:
        found.append("reportable: the harness run is not reportable; no baseline is held to it")
    if not config.harness.clean:
        found.append("harness: the harness run's checkout was not clean")
    if hashlib.sha256(task.brief.encode()).hexdigest() != config.brief_sha256:
        found.append("brief: the harness run was not given this task's brief")
    if record.get("task") != task.id:
        found.append(f"task: the raw arm's record is of {record.get('task')!r}, not {task.id!r}")
    # The model that answered, read from the stream itself: an endpoint that answers as
    # another model is caught here whatever the record and the configuration say.
    pinned = config.models.roles.get(role)
    answered = sorted(read_captured(raw_dir / "session" / "stdout.jsonl").answered)
    if answered != [pinned]:
        found.append(
            f"answered_by: the harness pinned {pinned!r}, the raw arm was answered by {answered!r}"
        )
    raw_profile, _, raw_tools = _tools(raw_dir / "session" / "session" / CONFIG_NAME)
    if raw_profile != "baseline":
        found.append(f"profile: the raw arm was installed as {raw_profile!r}, not 'baseline'")
    harness_lists = _harness_tools(run_dir, role)
    if not harness_lists:
        found.append(f"tools: no {role} session of the harness run left its installed tool list")
    elif any(tools != harness_lists[0] for tools in harness_lists):
        found.append(f"tools: the harness run's {role} sessions were given different tools")
    elif raw_tools != harness_lists[0]:
        found.append(
            f"tools: the harness ran with {harness_lists[0]!r}, the raw arm with {raw_tools!r}"
        )
    total = harness_total(run_dir)
    if record.get("cap") != total:
        found.append(
            f"cap: the harness spent {total} tokens, the raw arm was capped at {record.get('cap')}"
        )
    return found
