"""The small shapes every record in this package shares.

Kept apart so the event log, the run configuration and the gate and reviewer
Protocols can all use them without importing each other.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, StringConstraints, ValidationError

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

#: The architecture's physics-gate flag (ARCH-140): blocking, not run, or run and logged
#: without blocking. Required for every run; there is no default.
GateMode = Literal["on", "off", "observe"]

# A full model string names a family and a version ("claude-sonnet-4-5",
# "claude-sonnet-4-5-20250929"). An alias ("sonnet", "opus") is resolved inside the
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
