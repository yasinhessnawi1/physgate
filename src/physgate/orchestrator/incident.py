"""A person resolves a managed-settings incident at a terminal, and the record says so.

A run's sessions are each held to the policy limits its decomposition call received. Limits that
differ halt the run as a ``managed_settings_changed`` incident: the account's side can change
them, and they are applied with no trace the hooks see. A provider's rollout that makes the
account stricter is such a change too, and without a way to resolve it every run that spans one
is lost. So a person resolves it, by ``physgate incident resolve``:

- it is refused unless a person is at a terminal (:func:`require_interactive`, the promotion
  command's own check), and nothing here offers a way around it;
- it is taken only on the halt of one ``managed_settings_changed`` incident whose session's end
  shows other policy limits than the baseline: other managed settings, or an incident beside
  it, are not resolved here;
- it shows the change by key and value, read from the two files the record names, each held to
  its digest; a value that is not a flag, a number or null is shown by its kind and size only;
- it records who resolved it, why, both digests and the change, once the person types ``yes``.

The resume then accepts the run, and every later session is held to the new limits. The
baseline moves by that line alone; the replay refuses a resolution the record does not support.
A change that only adds restrictions set to ``allowed: false`` is resolved by the owner's rule
as the session ends, recorded the same way with ``by: "rule"``, and never halts the run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from physgate.knowledge.promote import PromotionError, require_interactive
from physgate.orchestrator.events import RULE, IncidentResolved
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.managed import (
    PolicyEntry,
    UnshowableKeyError,
    diff_lines,
    limits_with,
    policy_diff,
    policy_limits_change,
    read_limits,
    session_limits,
)
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.replay import RunState
from physgate.orchestrator.run_config import load_run_config

#: What a person types to record the resolution once the change is shown.
YES = "yes"


class Proposed(NamedTuple):
    """The resolution a halted run's record supports, before anyone confirms it."""

    subtask_id: str
    session_id: str
    old_sha256: str | None
    new_sha256: str | None
    changes: tuple[PolicyEntry, ...]
    omitted: int
    #: The incident's own words, which are the policy-limits check's for these two digests.
    detail: str


def proposed(state: RunState, run_dir: Path) -> Proposed:
    """The change a person would resolve on the run ``state`` replays, read from its files.

    Raises:
        RunStateError: the run is not halted on one ``managed_settings_changed`` incident that a
            session's end shows as other policy limits, it is resolved already, or either set of
            limits is not on disk as the record names it.
    """
    halted, incident = state.halted, state.incident
    if (
        halted is None
        or halted.reason != "incident"
        or incident is None
        or incident.cause != "managed_settings_changed"
        or state.open_incidents != [incident]
    ):
        msg = "only a run halted on one managed-settings incident is resolved here"
        raise RunStateError(msg, halted=halted.detail if halted else "not halted")
    if state.halt_resumable():
        msg = "the incident is resolved already; resume the run"
        raise RunStateError(msg, detail=halted.detail)
    sub = state.subtasks.get(incident.subtask_id or "")
    ended = sub.attempts[-1].session if sub is not None and sub.attempts else None
    old, new = state.policy_baseline, ended.policy_limits_sha256 if ended else None
    if sub is None or ended is None or incident.detail != policy_limits_change(old, new):
        msg = (
            "the incident is not a change of the policy limits a session's end shows: other "
            "managed settings changed, and a person looks at those without this command"
        )
        raise RunStateError(msg, detail=incident.detail)
    before = None if old is None else limits_with(run_dir, old)
    after = None if new is None else read_limits(session_limits(run_dir, ended.session_id), new)
    if (old is not None and before is None) or (new is not None and after is None):
        msg = "the policy limits the record names are not on disk as it names them"
        raise RunStateError(msg, baseline=str(old), session=ended.session_id, found=str(new))
    try:
        changes, omitted = policy_diff(before, after)
    except UnshowableKeyError as exc:
        msg = "the policy limits hold a key that cannot be shown as written: not resolved here"
        raise RunStateError(msg, reason=str(exc)) from None
    return Proposed(
        sub.plan.subtask_id, ended.session_id, old, new, changes, omitted, incident.detail
    )


def shown(change: Proposed) -> list[str]:
    """What the person is shown before confirming: the digests, then the change by key."""
    lines = [
        f"session {change.session_id} of subtask {change.subtask_id} received other policy "
        "limits than the run's",
        f"incident: {change.detail}",
        f"before: {change.old_sha256 or 'no policy limits'}",
        f"after:  {change.new_sha256 or 'no policy limits'}",
    ]
    return lines + (diff_lines(change.changes, change.omitted) or ["(no key differs)"])


def record_resolution(
    run_dir: Path,
    *,
    by: str,
    reason: str,
    confirm: Callable[[str], str],
    notice: Callable[[str], None],
) -> IncidentResolved:
    """Show the change, ask, and record the resolution: everything but the terminal check.

    Raises:
        RunStateError: no name or no reason, the rule's name given as a person's, nothing to
            resolve (:func:`proposed`), or anything but ``yes`` typed; nothing is then written.
    """
    by, reason = by.strip(), reason.strip()
    if not by or not reason or by == RULE:
        msg = f"a person resolves an incident by name and with a reason; {RULE!r} is the rule's"
        raise RunStateError(msg, by=by)
    run_dir = Path(run_dir).resolve()
    record = RunRecord(load_run_config(run_dir / "run.json"), run_dir)
    try:
        change = proposed(record.state, run_dir)
        for line in shown(change):
            notice(line)
        if confirm(f"Type {YES} to record this resolution by {by}: ").strip() != YES:
            msg = "nothing was recorded: the resolution was not confirmed"
            raise RunStateError(msg, by=by)
        event = IncidentResolved(
            **record.envelope(),
            subtask_id=change.subtask_id,
            session_id=change.session_id,
            by=by,
            reason=reason,
            rule=False,
            old_sha256=change.old_sha256,
            new_sha256=change.new_sha256,
            changes=change.changes,
            omitted=change.omitted,
        )
        record.emit(event)
        return event
    finally:
        record.close()


def resolve(run_dir: Path, *, by: str, reason: str) -> IncidentResolved:
    """Refuse unless a person is at a terminal, then show, ask and record the resolution.

    The one function the command calls. Nothing calls :func:`record_resolution` past this check
    but a test of what it does.

    Raises:
        RunStateError: ``stdin`` is not a terminal, or as :func:`record_resolution`.
    """
    try:
        require_interactive()
    except PromotionError:
        msg = (
            "an incident is resolved only by a person at a terminal: this command refuses to "
            "run non-interactively"
        )
        raise RunStateError(msg, run_dir=str(run_dir)) from None
    return record_resolution(run_dir, by=by, reason=reason, confirm=input, notice=print)
