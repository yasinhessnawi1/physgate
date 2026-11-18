"""The gap trend, published for the Evidence page as its one reader read it, or why it could not be.

**Why a publication.** The trend's reader (:func:`read_gap_trend`) holds the trend to its head
and its vectors to the register, and both lie beneath the role's withheld root, which no
session reads and no folder the operator UI is given may reach. The UI's server could not run
the reader without reading there, so it does not: a person runs it at a terminal
(``physgate gaps trend --publish DIR``), and the server serves what that wrote. Nothing here
computes a number or reads anything the reader does not.

**What is published.** One file per role, :func:`published_name`, written whole (a temporary
file renamed into place) into the folder named: the reader's weeks through the day it was read,
as :func:`gap_weeks` gives them (a week with no line shown missing, never filled in), and the
time it was read. A trend the reader refuses is published as that refusal, its reason and its
sentence, in place of whatever was published before: a page never shows numbers the reader
would now refuse. A sentence that names a place on disk is replaced by one that names none.

**What it holds against.** It names no store, no path, no register line and no reason a mark
carries, only what the reader returns. It is written by a person, never inside a session, and
never into the store or a folder that holds it, since the folder is then given to the UI's
server to read. Its parser (:func:`read_published`) refuses anything its writer could not have
written, a file cut part way, a publication of another role and one over its size bound. **A
stated limit:** the publication is a copy as it was read. A later line, a later exposure or a
later edit of the trend is not on it until it is published again, and whoever can write the
folder can write the copy; the folder is the hold, so it is one of its own that no run names.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.evaluation.gaps.measure import GapWeek, RoleName, gap_weeks, read_gap_trend
from physgate.evaluation.gaps.vector import GapsError
from physgate.evaluation.per_role.exceptions import PerRoleError

__all__ = [
    "MOST_PUBLISHED_BYTES",
    "ROLES",
    "GapsError",
    "PublishedTrend",
    "publish_trend",
    "published_name",
    "read_for_publication",
    "read_published",
]

#: The roles a trend is published for, in the order a page shows them.
ROLES: tuple[RoleName, ...] = ("control", "firmware")
#: The most bytes a publication is read to: a trend of years of weekly lines is far less.
MOST_PUBLISHED_BYTES = 4 * 1024 * 1024
#: What a harness session's environment carries, as the register's writers read it.
SESSION_MARKERS = (
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
    "CLAUDE_CODE_TMPDIR",
    "CLAUDE_CODE_SHELL_PREFIX",
)
#: A sentence names a place on disk where a word of it starts with the separator.
_PLACE = re.compile(r"(^|[\s'\"(=])" + re.escape(os.sep) + r"\S")

Reason = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Sentence = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Refused(_Frozen):
    """Why the reader refused the trend as it was published: its reason and its sentence."""

    refused_because: Reason
    error: Sentence


class PublishedTrend(_Frozen):
    """A role's trend as its reader read it at ``read_at``: its weeks, or why there are none."""

    format: Literal[1]
    role: RoleName
    read_at: AwareDatetime
    #: Every ISO week from the first line through the day it was read; empty when the trend has
    #: no line yet. ``None`` exactly when the reader refused the trend.
    weeks: tuple[GapWeek, ...] | None
    refused: Refused | None

    @model_validator(mode="after")
    def _one_or_the_other(self) -> PublishedTrend:
        if (self.weeks is None) == (self.refused is None):
            msg = "a publication holds the trend's weeks or the reader's refusal, never both"
            raise ValueError(msg)
        return self


def published_name(role: str) -> str:
    """The name a role's publication is written under, and found under at the top of a root."""
    return f"gap-trend-{role}.json"


def _refuse(reason: str, msg: str) -> GapsError:
    return GapsError(msg, refused_because=reason)


def _said(exc: PerRoleError) -> Refused:
    """The reader's refusal as published: its sentence, unless that names a place on disk."""
    reason = exc.context.get("refused_because", type(exc).__name__)
    sentence = str(exc)
    if _PLACE.search(sentence):
        sentence = (
            f"the trend could not be read ({reason}); the reader's sentence names a place on "
            "disk, so it is not published: read the trend at a terminal to see it"
        )
    return Refused(refused_because=reason[:200], error=sentence[:2000])


def read_for_publication(
    trend: Path, *, store: Path, role: RoleName, now: datetime | None = None
) -> PublishedTrend:
    """``role``'s trend in ``store`` as :func:`read_gap_trend` reads it now, or its refusal."""
    read_at = now or datetime.now(UTC)
    try:
        lines = read_gap_trend(trend, store=store, role=role)
    except PerRoleError as exc:
        return PublishedTrend(format=1, role=role, read_at=read_at, weeks=None, refused=_said(exc))
    weeks = gap_weeks(lines, through=read_at.date())
    return PublishedTrend(format=1, role=role, read_at=read_at, weeks=weeks, refused=None)


def _inside(path: Path, other: Path) -> bool:
    return path == other or other in path.parents


def _folder_refusal(out: Path, store: Path) -> str | None:
    """Why ``out`` may not hold a publication, or ``None``: a folder of its own, not the store's."""
    if not os.path.lexists(out):
        return "the folder to publish into is not there"
    if os.path.islink(out) or not os.path.isdir(out):
        return "the place to publish into is a link or not a folder; name the folder itself"
    real, home = Path(os.path.realpath(out)), Path(os.path.realpath(store))
    if _inside(real, home) or _inside(home, real):
        return (
            "the folder to publish into lies in the store or holds it, and the page's server is "
            "then given the store to read; name a folder of its own, outside the store"
        )
    return None


def _write_whole(out: Path, name: str, data: bytes) -> None:
    """Write ``data`` to ``out/name`` whole: a temporary file beside it, renamed into place."""
    fd = os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        partial = f".{name}.{os.getpid()}.{time.monotonic_ns()}"
        handle = os.open(
            partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd
        )
        try:
            try:
                os.write(handle, data)
                os.fsync(handle)
            finally:
                os.close(handle)
            os.replace(partial, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(partial, dir_fd=fd)
            raise
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_trend(
    trend: Path, *, store: Path, role: RoleName, out: Path, now: datetime | None = None
) -> Path:
    """Publish ``role``'s trend, as its reader reads it now, into the folder ``out``; its path.

    A trend the reader refuses is published as the refusal, replacing what was there.

    Raises:
        GapsError: asked for inside a harness session; ``out`` is not a folder of its own (it
            is missing, a link, in the store or holds it).
    """
    found = sorted(name for name in SESSION_MARKERS if name in os.environ)
    if found:
        msg = f"the gap trend is published by a person, never from a session ({', '.join(found)})"
        raise _refuse("inside_a_session", msg)
    refusal = _folder_refusal(Path(out), Path(store))
    if refusal is not None:
        raise _refuse("publish_refused", refusal)
    record = read_for_publication(trend, store=store, role=role, now=now)
    name = published_name(role)
    _write_whole(Path(out), name, record.model_dump_json().encode() + b"\n")
    return Path(out) / name


def read_published(data: bytes, role: str) -> PublishedTrend:
    """The publication ``data`` of ``role``, as its writer wrote it.

    Raises:
        GapsError: it is over its size bound, cut, edited into what its writer could not have
            written, or another role's.
    """
    if len(data) > MOST_PUBLISHED_BYTES:
        msg = (
            f"the published gap trend is over {MOST_PUBLISHED_BYTES} bytes, which no trend its "
            "writer publishes reaches; publish it again"
        )
        raise _refuse("publication_unreadable", msg)
    try:
        published = PublishedTrend.model_validate_json(data)
    except ValidationError:
        msg = (
            "the published gap trend is not one its writer could have written: it was cut, "
            "edited or written by something else; publish it again"
        )
        raise _refuse("publication_unreadable", msg) from None
    if published.role != role:
        msg = f"the published gap trend under the {role} role's name is another role's"
        raise _refuse("publication_unreadable", msg)
    return published
