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
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.task import Task
from physgate.hooks.settings import CONFIG_NAME
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.dispatch import read_captured
from physgate.orchestrator.events import (
    LeftoverRead,
    SessionEnded,
    SessionSpawned,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.run_config import RunConfig, load_run_config

#: How each field of a harness run's recorded configuration bears on the raw arm.
#:
#: - ``compared``: the raw arm records the same pin, and it must be equal;
#: - ``harness``: a part of the harness the raw arm is measured without;
#: - ``intended``: the raw arm differs on purpose, as its own code says;
#: - ``identity``: names the run, says nothing about how it answered;
#: - ``not_compared``: recorded by the harness run, not yet held against the raw arm.
#:   Each is a known gap, listed where the comparison is built, never a silent one.
RunFieldClass = Literal["compared", "harness", "intended", "identity", "not_compared"]
RUN_FIELDS: dict[str, RunFieldClass] = {
    "auth": "compared",
    "brief_sha256": "compared",
    "claude_version": "compared",
    "effort": "compared",
    "endpoint": "compared",
    "held_out": "compared",
    "max_output_tokens": "compared",
    "models": "compared",
    "network": "compared",
    "os_layer": "compared",
    "role_python": "compared",
    "thinking_display": "compared",
    "gate_mode": "harness",
    "escalation_backend": "harness",
    "queue_decisions": "harness",
    # A role session's turn and wall-clock bounds; the raw arm's are these times the
    # harness's repair budget, so neither binds before its token cap would.
    "bounds": "intended",
    # The hook layer's ceiling on what a session loads always; the raw agent loads nothing
    # always, so its ceiling is set where it never binds.
    "token_ceiling": "intended",
    "run_id": "identity",
    "seed": "identity",
    "target_head": "identity",
    "git_binary": "not_compared",
    "harness": "not_compared",
    "held_out_canaries": "not_compared",
    "held_out_sha256": "not_compared",
    "network_enforced": "not_compared",
    "os_layer_absent": "not_compared",
    "reportable": "not_compared",
}

#: Every pin the raw arm's record carries. Each is compared below; one the record lacks,
#: or one it carries that is not here, is named.
RAW_PINS = frozenset(
    {
        "advisor",
        "answer",
        "auth",
        "brief_sha256",
        "claude_version",
        "effort",
        "endpoint",
        "held_out",
        "max_output_tokens",
        "model",
        "network",
        "os_layer",
        "role_python",
        "thinking_display",
    }
)


class ComparisonError(PerRoleError):
    """The two arms cannot be compared from what they recorded."""


def harness_total(run_dir: Path) -> int:
    """Every token the harness run spent, each message once: roles, reviewers, decomposition.

    The raw arm's cap is this total, so a total that undercounts makes the baseline quietly
    weaker. It is refused, never returned, when the log cannot show every token:

    - a line was cut off at the log's end;
    - a message's usage was read from a session a killed orchestrator left behind, with no
      result to check it against (``partial``), or such a session was read incomplete;
    - a role session was spawned and never ended or read.

    Raises:
        ComparisonError: the run's token account is not complete.
    """
    log = run_dir / "events.jsonl"
    data = log.read_bytes()
    if data and not data.endswith(b"\n"):
        msg = "the run's event log ends in a cut-off line; its last tokens are not counted"
        raise ComparisonError(msg, log=str(log))
    events = read_events(log)
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
        "brief_sha256": config.brief_sha256,
        "claude_version": config.claude_version,
        "effort": config.effort,
        "endpoint": config.endpoint,
        "held_out": sorted(config.held_out),
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
        for name in sorted(set(RunConfig.model_fields) - set(RUN_FIELDS))
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
