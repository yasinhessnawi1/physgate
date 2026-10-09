"""The small shapes every record in this package shares.

Kept apart so the event log, the run configuration and the gate and reviewer
Protocols can all use them without importing each other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, StringConstraints, ValidationError

# The gate mode is defined by the flag register and re-exported here, where the
# orchestrator's records have always taken it from.
from physgate.flags import GateMode as GateMode

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

#: How a run's model calls authenticate: the subscription's long-lived token, or an
#: API key. Required for every run; the secret itself is never recorded.
AuthMode = Literal["subscription", "api_key"]

# A full model string names a family and a version ("claude-sonnet-5",
# "claude-haiku-4-5-20251001"). An alias ("sonnet", "opus") is resolved inside the
# Claude Code binary and was measured to move with it: on 2.1.272 "sonnet" reached
# the endpoint as a different model than the same alias names on an older binary.
# A run pinned to an alias is pinned to nothing.
_FULL_MODEL = re.compile(r"^[a-z][a-z0-9._/-]*-[0-9][a-z0-9._-]*$")


def _full_model_string(value: str) -> str:
    if not _FULL_MODEL.match(value):
        msg = f"{value!r} is not a full model string (an alias moves with the binary)"
        raise ValueError(msg)
    return value


ModelString = Annotated[str, AfterValidator(_full_model_string)]


def first_problem(exc: ValidationError) -> str:
    """The first thing wrong with a record, as a sentence rather than a report."""
    problems = exc.errors()
    if not problems:
        return "the line is not a valid record"
    where = ".".join(str(part) for part in problems[0]["loc"]) or "the record"
    return f"{where}: {problems[0]['msg']}"


#: A UTC timestamp to the microsecond, as every record here writes it.
Timestamp = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")]


def utc_now() -> datetime:
    """The current time, in UTC."""
    return datetime.now(UTC)


def utc_stamp(moment: datetime) -> str:
    """``moment`` as a record's timestamp.

    Raises:
        ValueError: ``moment`` is naive or not in UTC.
    """
    if moment.utcoffset() != timedelta(0):
        msg = "record timestamps are UTC"
        raise ValueError(msg)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def render_jsonl(records: Iterable[BaseModel]) -> str:
    """One JSON line per record, each ending in a newline: what a command prints.

    The command line and the operator UI's server both write a record list through
    this, so the two cannot serialise the same records differently.
    """
    return "".join(record.model_dump_json() + "\n" for record in records)
