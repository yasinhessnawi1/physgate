"""What the binary itself recorded about each call: its cache writes by time to live, and its cost.

A call is one session of the binary: the decomposition, a role session, or a
review. Its captured stream ends in the runtime's result event, whose usage says
how many of the call's cache-write tokens went to the five-minute cache and how
many to the one-hour cache (``usage.cache_creation``), and whose
``total_cost_usd`` is what the binary priced the call at, at list price. The run's
own account holds every token the call spent but not which cache each write went
to, which is billed at a different rate; so the split is read here, per call,
from the record the binary wrote, never assumed.

A stream is read up to the runtime's result and no further, as every reader of a
session's stream reads it: a line after the result is not the runtime's. The
harness never resumes a session (no ``--resume`` is passed), so a stream holds
one result and the figure on it is the call's own; a resumed session's figure
would be cumulative over its resumes, and is not read here.

Where the streams are: the decomposition's in the run directory's
``decomposition/``, each role session's under ``sessions/<id>/``, and each
review's under ``<review root>/<id>/session/`` of whichever review root it was
given. The review root is not recorded in the run, so it is named by the reader.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.observe.exceptions import ManifestError

STREAM_NAME = "stdout.jsonl"
DECOMPOSITION_DIRNAME = "decomposition"
SESSIONS_DIRNAME = "sessions"
#: Where a review's own files sit under its directory in a review root.
REVIEW_SESSION_DIRNAME = "session"

Count = Annotated[int, Field(ge=0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CacheWrites(_Frozen):
    """One call's cache-write tokens by the cache they went to, as its result recorded them."""

    five_minute: Count
    one_hour: Count

    def total(self) -> int:
        """Every cache-write token of the call."""
        return self.five_minute + self.one_hour


class RecordedCall(_Frozen):
    """What a call's result event recorded about it, for pricing and for checking a price."""

    session_id: str
    #: ``None`` where the result records no split.
    cache_writes: CacheWrites | None
    #: The binary's own figure for the call, at list price; ``None`` where it reports none.
    binary_usd: Decimal | None


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _runtime_result(text: str) -> dict[str, Any] | None:
    """The stream's first result event: the runtime's own. Lines after it are not read."""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    return None


def read_call(stream: Path, session_id: str) -> RecordedCall | None:
    """What the call's result event recorded, or ``None`` if its stream holds no result.

    Raises:
        ManifestError: the result is another session's than the call it is read for.
    """
    result = _runtime_result(Path(stream).read_bytes().decode(errors="replace"))
    if result is None:
        return None
    if result.get("session_id") != session_id:
        msg = "the stream at the call's place records another session's result"
        raise ManifestError(
            msg, stream=str(stream), call=session_id, found=str(result.get("session_id"))
        )
    usage = result.get("usage")
    split = usage.get("cache_creation") if isinstance(usage, dict) else None
    writes = None
    if isinstance(split, dict):
        five = _count(split.get("ephemeral_5m_input_tokens"))
        hour = _count(split.get("ephemeral_1h_input_tokens"))
        if five is not None and hour is not None:
            writes = CacheWrites(five_minute=five, one_hour=hour)
    cost = result.get("total_cost_usd")
    binary = (
        Decimal(repr(cost))
        if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0
        else None
    )
    return RecordedCall(session_id=session_id, cache_writes=writes, binary_usd=binary)


def call_streams(run_dir: Path, attribution: str, review_roots: Sequence[Path] = ()) -> list[Path]:
    """Every place the stream of the call ``attribution`` names may be, in the order tried."""
    kind, who = attribution.split(":", 1)
    if kind == "decomposition":
        return [Path(run_dir) / DECOMPOSITION_DIRNAME / STREAM_NAME]
    if kind == "session":
        return [Path(run_dir) / SESSIONS_DIRNAME / who / STREAM_NAME]
    if kind == "reviewer":
        return [Path(root) / who / REVIEW_SESSION_DIRNAME / STREAM_NAME for root in review_roots]
    return []


def run_calls(
    run_dir: Path,
    attributions: Iterable[str],
    review_roots: Sequence[Path] = (),
    resolve: Callable[[Path], Path] = Path,
) -> dict[str, RecordedCall]:
    """What each call's result recorded, by its attribution, for every call whose result is read.

    ``resolve`` is how a path is opened: a reader that may open only some paths (the
    operator UI's server) passes its own check, which refuses the others.

    Raises:
        ManifestError: a result is another session's than its call's.
    """
    found: dict[str, RecordedCall] = {}
    for attribution in attributions:
        who = attribution.split(":", 1)[1]
        for place in call_streams(run_dir, attribution, review_roots):
            path = resolve(place)
            if not path.is_file():
                continue
            recorded = read_call(path, who)
            if recorded is not None:
                found[attribution] = recorded
                break
    return found
