"""Whether a session a run spawned has ended, by the run's own records: one rule for every reader.

Three kinds of session are spawned, and each is recorded at its spawn while its process is held
before it runs anything:

- **A role session**, on the run's event log (``session_spawned``). Its end is its own line,
  ``session_ended``, written after its tokens; or, where its orchestrator was killed first, the
  ``leftover_read`` a resume writes once it has read the session's stream.
- **A module review's session**, on the same log and with the same line: the loop records a
  review's spawn as it records a role session's, so a resume holds the review's process record to
  it too. A review has no end line of its own. What the loop writes once the review is back names
  it: its tokens and then its verdict (``review_ran``) or why there is none
  (``review_unavailable``), the try that halts the run with the review owed again (the usage
  limit, the machine's retries spent, a refused credential, an OS layer that would not start)
  among them; or, where the review's try ends the run for a while with no such line (held-out
  material in its stream, a change of managed settings, and every such halt of a log written
  before those tries had their line), its tokens and, written at once with them, the incident or
  the halt (:func:`halted_with`). A resume's ``leftover_read`` ends it as it ends a role session.
  A review in its repair resume is spawned again under the same id, so only a line after its last
  spawn ends it.
- **The plan's review**, beside the decomposition's rounds (``decomposition/review_session.json``),
  never on the event log. The record is removed once its round's end is journalled, so it is open
  while the record is there.

A spawn no such line names is open, whatever it was spawned for: a kind of session this rule does
not know is never taken as ended. Its tokens lines alone do not end a review either: a process
killed between them leaves the rest of the review's spend on no record, and a resume then reads
its stream again as it reads any session left open.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from physgate.orchestrator.events import (
    Event,
    Halted,
    Incident,
    LeftoverRead,
    ReviewRan,
    ReviewUnavailable,
    SessionEnded,
    SessionSpawned,
    StageEntered,
    TokensUsed,
)

#: Where the plan's review records its spawn, in the run directory, until its round's end.
PLAN_REVIEW_SPAWN = PurePosixPath("decomposition", "review_session.json")

#: The kinds of session this rule knows the end of.
SpawnKind = Literal["role session", "module review", "plan review"]

#: The stage the loop enters before it spawns each kind of session on the event log.
_SPAWNED_AT: dict[str, SpawnKind] = {"spawn": "role session", "review": "module review"}


@dataclass(frozen=True)
class OpenSession:
    """A session the run spawned and no record says has ended."""

    session_id: str
    #: What the records say it was spawned as, or why they cannot say.
    kind: str

    def __str__(self) -> str:
        """The session as a refusal names it: its kind, then its id."""
        return f"{self.kind} {self.session_id}"


def ended_by(session_id: str, events: Sequence[Event]) -> Event | None:
    """The line that ends the last spawn of ``session_id``, or ``None``: still open, or unspawned.

    For a review whose try ended the run for a while, the line is the incident or the halt written
    with its tokens.
    """
    last = None
    for i, event in enumerate(events):
        if isinstance(event, SessionSpawned) and event.session_id == session_id:
            last = i
    if last is None:
        return None
    after = events[last + 1 :]
    for i, event in enumerate(after):
        if _names_end(event, session_id):
            return event
        halt = _halt_with(after, i, session_id)
        if halt is not None:
            return halt
    return None


def halted_with(session_id: str, events: Sequence[Event]) -> Halted | Incident | None:
    """The incident or halt written at once with a review's tokens, where that ends the review.

    Read after the session's last spawn, as :func:`ended_by` reads it; on a log that records no
    spawn of the session, over the whole log. ``None`` where a line naming the session ends it
    first, or where nothing does. A reader that must find which review the try was (its subtask,
    its model) and finds no line naming the session takes it from here.
    """
    last = None
    for i, event in enumerate(events):
        if isinstance(event, SessionSpawned) and event.session_id == session_id:
            last = i
    after = events if last is None else events[last + 1 :]
    for i, event in enumerate(after):
        if _names_end(event, session_id):
            return None
        halt = _halt_with(after, i, session_id)
        if halt is not None:
            return halt
    return None


def _halt_with(events: Sequence[Event], i: int, session_id: str) -> Halted | Incident | None:
    """The incident or halt right after ``events[i]``, where that line is the review's tokens."""
    event = events[i]
    if isinstance(event, TokensUsed) and event.attribution == f"reviewer:{session_id}":
        following = events[i + 1] if i + 1 < len(events) else None
        if isinstance(following, Halted | Incident):
            return following
    return None


def _names_end(event: Event, session_id: str) -> bool:
    return (
        (isinstance(event, SessionEnded | LeftoverRead) and event.session_id == session_id)
        or (isinstance(event, ReviewRan) and event.result.session_id == session_id)
        or (isinstance(event, ReviewUnavailable) and event.session_id == session_id)
    )


def session_open(session_id: str, events: Sequence[Event]) -> bool:
    """Whether the log records a spawn of ``session_id`` that no line after it ends."""
    spawned = any(isinstance(e, SessionSpawned) and e.session_id == session_id for e in events)
    return spawned and ended_by(session_id, events) is None


def spawn_kind(session_id: str, events: Sequence[Event]) -> SpawnKind | None:
    """What ``session_id`` was spawned as on the event log, or ``None`` if the records cannot say.

    Its end line says, where it has one that only one kind writes. Otherwise the stage the loop
    entered last before its first spawn: a role session is spawned at the spawn stage, a module
    review at the review stage.
    """
    end = ended_by(session_id, events)
    if isinstance(end, SessionEnded):
        return "role session"
    if isinstance(end, ReviewRan | ReviewUnavailable | Halted | Incident):
        return "module review"
    stage = None
    for event in events:
        if isinstance(event, StageEntered):
            stage = event.stage
        elif isinstance(event, SessionSpawned) and event.session_id == session_id:
            return _SPAWNED_AT.get(stage or "")
    return None


def open_sessions(events: Sequence[Event], run_dir: Path | None = None) -> tuple[OpenSession, ...]:
    """Every session the run spawned that no record says has ended, in the order first spawned.

    With ``run_dir``, the plan's review too, while its spawn's record is there.
    """
    found: list[OpenSession] = []
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, SessionSpawned) or event.session_id in seen:
            continue
        seen.add(event.session_id)
        if session_open(event.session_id, events):
            found.append(OpenSession(event.session_id, _kind_named(event.session_id, events)))
    if run_dir is not None:
        plan = _plan_review_left(run_dir)
        if plan is not None:
            found.append(plan)
    return tuple(found)


def _kind_named(session_id: str, events: Sequence[Event]) -> str:
    kind = spawn_kind(session_id, events)
    if kind is not None:
        return kind
    stage = None
    for event in events:
        if isinstance(event, StageEntered):
            stage = event.stage
        elif isinstance(event, SessionSpawned) and event.session_id == session_id:
            break
    where = f"at the {stage} stage" if stage is not None else "before any stage"
    return f"session of a kind no end rule knows (spawned {where})"


def _plan_review_left(run_dir: Path) -> OpenSession | None:
    path = Path(run_dir) / PLAN_REVIEW_SPAWN
    if not path.exists():
        return None
    try:
        named = json.loads(path.read_text())["session_id"]
        if not isinstance(named, str) or not named:
            raise TypeError(type(named).__name__)
    except (OSError, ValueError, KeyError, TypeError):
        named = "(its spawn's record cannot be read)"
    return OpenSession(named, "plan review")
