"""``staging.append``: one write path for a subtask's outcome, and for a drafted file (ARCH-100).

A successful episode's candidate skill and a failed one's candidate
antipattern both come through here, and only here — nothing in this module
ever touches ``standards.md`` or ``skill.md``. ``promote.py`` is the library's
only writer, and it is a human, run interactively.

A third kind, ``standards``, covers the case ARCH-101 itself does not emit
from an episode: a domain's first standards or skill file, researched and
drafted whole rather than accumulated one finding at a time. It goes through
the same staging-then-promotion shape because the promotion gate — a human,
run interactively — is the property that matters, not which kind of writing
produced the candidate.

Emission is the orchestrator's, not a role session's: nothing in the harness
wires a role session's tool calls to this module, so ``staging/`` needs none of
the protection `standards.md`/`skill.md` get from `hooks/settings.py` — a role
session cannot reach this code to begin with.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from physgate.knowledge.exceptions import StagingError

Kind = Literal["skill", "antipattern", "standards"]

#: Where a candidate lands unless the caller names another directory: a
#: subtree of the tracked `knowledge/` directory, sibling to the promoted
#: content a candidate might become, so a reviewer finds it beside what it
#: would turn into.
STAGING_ROOT = Path("knowledge/staging")

_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
_DOMAIN_PATTERN = r"^[a-z][a-z0-9_]*$"


class Candidate(BaseModel):
    """One candidate exactly as it was written: never edited after, only promoted or left."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Kind
    #: The domain directory under `knowledge/` this candidate is destined for
    #: (`loader.py`'s own role/domain naming: a safe, lower-case directory
    #: name), so a human reviewer and `promote.py` both know where it goes
    #: without parsing `content` for it.
    domain: Annotated[str, StringConstraints(pattern=_DOMAIN_PATTERN)]
    content: Annotated[str, StringConstraints(min_length=1)]
    episode_id: Annotated[str, StringConstraints(pattern=_ID_PATTERN)]
    candidate_id: Annotated[str, StringConstraints(pattern=_ID_PATTERN)]
    #: Informational only — nothing in this package reads it to decide anything.
    written: Annotated[str, StringConstraints(min_length=1)]


def append(
    kind: Kind,
    content: str,
    episode_id: str,
    *,
    domain: str,
    staging_root: Path = STAGING_ROOT,
) -> Path:
    """Write one candidate under ``staging_root``; never reads or writes the library.

    Raises:
        StagingError: ``content`` is empty or whitespace-only, or ``episode_id``
            or ``domain`` is not a safe identifier.
    """
    if not content.strip():
        msg = "a candidate's content must not be empty"
        raise StagingError(msg, kind=kind, episode_id=episode_id)
    candidate_id = uuid.uuid4().hex
    try:
        record = Candidate(
            kind=kind,
            domain=domain,
            content=content,
            episode_id=episode_id,
            candidate_id=candidate_id,
            written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
    except ValidationError as exc:
        msg = "a candidate did not validate"
        raise StagingError(msg, reason=str(exc), episode_id=episode_id) from None
    directory = Path(staging_root) / kind
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{candidate_id}.json"
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def candidates(kind: Kind, *, staging_root: Path = STAGING_ROOT) -> tuple[Candidate, ...]:
    """Every candidate of ``kind`` currently staged, in path order.

    An empty tuple when ``staging_root / kind`` does not exist yet — no
    candidate has ever been written, not an error.
    """
    directory = Path(staging_root) / kind
    if not directory.is_dir():
        return ()
    return tuple(
        Candidate.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    )
