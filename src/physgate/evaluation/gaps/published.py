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
would now refuse. So is any failure once the folder is judged, and a copy that cannot be written
removes the one before it: a publish that fails leaves nothing older to read as current. A
sentence that names a place on disk, in any spelling (absolute, relative, from the home, a
Windows path), is replaced by one that names none.

**What it holds against.** It names no store, no path, no register line and no reason a mark
carries, only what the reader returns. It is written by a person, never inside a session, and
never into the store or a folder that holds it, since the folder is then given to the UI's
server to read. Nor into a place the harness knows a session, a reviewer or a commit reaches,
each known the way the code that makes it marks it (:func:`known_places`, :func:`_marked`): a
run's directory (its ``run.json`` or ``instrument.json``) or a folder that holds one, a git
checkout or worktree (the harness's own, a run's target and its worktrees), an installation (its
manifest) or a folder that holds one, a review root or a review's directory, the machine's
shared temporary directories (which every session's OS layer leaves open to read and write), and
a folder the operator UI would refuse to read as a root. Nor into a folder that holds the
published tier status (:mod:`physgate.evaluation.tiers.published`), whose publisher refuses a
folder holding this in turn: each is published into a folder of its own, so neither publish can
be blocked by the other's file. Its parser (:func:`read_published`)
refuses anything its writer could not have written, a file cut part way, a publication of
another role and one over its size bound.

**Stated limits.** The command is given no run, so it cannot know every place a run's sessions
read: their OS layer and file tools refuse only what a session's configuration names, and a
folder of a person's own is not among those. It says so, in its help and in each refusal: the
folder is one of its own that no run names, given to the operator UI as a root. The publication
is a copy as it was read: a later line, a later exposure or a later edit of the trend is not on
it until it is published again, and whoever can write the folder can write the copy.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
    "WHERE_TO_PUBLISH",
    "GapsError",
    "KnownPlaces",
    "PublishedTrend",
    "beside_another",
    "folder_refusal",
    "known_places",
    "publish_trend",
    "published_name",
    "read_for_publication",
    "read_published",
    "write_all",
    "write_whole",
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
#: A word that holds a separator of either kind names a place on disk, however it is spelt:
#: absolute, relative, a Windows path, or after a quote, a backtick or a bracket.
_SEPARATOR = re.compile(r"[/\\]")
#: A home-relative place: ``~`` at the start of a word, before a name or a separator.
_HOME = re.compile(r"(?<![\w~])~(?=[A-Za-z_/\\])")
#: A word of digits and slashes alone is a number (``1/4``, ``2026/11/18``), not a place.
_FRACTION = re.compile(r"\d+(?:/\d+)+")
#: What is stripped from a word's ends before it is read as a number.
_AROUND = "\"'`()[]{}<>.,;:!?"

#: Which folder to publish into, said in the command's help and in every refusal of a folder.
WHERE_TO_PUBLISH = (
    "This command is given no run, so it cannot know every place a run's sessions may read: "
    "publish into a folder of its own that no run names and nothing else writes, and give that "
    "folder to the operator UI as a root (physgate ui --root)."
)

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


def _names_a_place(sentence: str) -> bool:
    """Whether ``sentence`` names a place on disk, in any spelling a path takes."""
    if _HOME.search(sentence):
        return True
    for word in sentence.split():
        if _SEPARATOR.search(word) and not _FRACTION.fullmatch(word.strip(_AROUND)):
            return True
    return False


def _said(exc: PerRoleError) -> Refused:
    """The reader's refusal as published: its sentence, unless that names a place on disk."""
    reason = str(exc.context.get("refused_because") or type(exc).__name__)
    if _names_a_place(reason):
        reason = type(exc).__name__
    sentence = str(exc) or reason
    if _names_a_place(sentence):
        sentence = (
            f"the trend could not be read ({reason}); the reason given names a place on disk, "
            "so it is not shown here: read the trend at a terminal to see it"
        )
    return Refused(refused_because=reason[:200], error=sentence[:2000])


def _failed(role: RoleName, read_at: datetime, exc: Exception) -> PublishedTrend:
    """A publish that failed once its folder was judged, published in place of the last copy."""
    sentence = (
        f"the gap trend could not be read for publishing ({type(exc).__name__}), so no number "
        "of it is shown: read the trend at a terminal to see why, then publish it again"
    )
    refused = Refused(refused_because="publish_failed", error=sentence)
    return PublishedTrend(format=1, role=role, read_at=read_at, weeks=None, refused=refused)


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


@dataclass(frozen=True)
class KnownPlaces:
    """The places on this machine the harness itself names, where a publication must not lie.

    ``harness``: the checkout the command runs from, or ``None``; ``review_root``: the standing
    root reviews are read beneath; ``shared_temps``: the machine's shared temporary directories,
    which every session's OS layer leaves open, and Claude Code's own inside them.
    """

    harness: Path | None
    review_root: Path
    shared_temps: tuple[Path, ...]


def known_places() -> KnownPlaces:
    """The places as the launchers name them: the harness checkout, the review root, the temps.

    Its own function so a test can name places of its own.
    """
    from physgate.orchestrator.run_config import harness_root
    from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs
    from physgate.reviewers.places import standing_root

    temps = tuple(Path(p) for p in (*shared_temp_dirs(), *claude_temp_dirs()))
    return KnownPlaces(
        harness=harness_root(), review_root=standing_root(Path.home()), shared_temps=temps
    )


def _marked(folder: Path) -> str | None:
    """What ``folder`` is, by the mark its maker leaves in it: a run, an installation, a review."""
    from physgate.evaluation.inject.runner import CONFIG_NAME as INSTRUMENT_CONFIG
    from physgate.orchestrator.dispatch import RUN_CONFIG_NAME
    from physgate.orchestrator.install import MANIFEST_NAME
    from physgate.reviewers.places import READ_DIRNAME, REVIEW_ID, SESSION_DIRNAME

    if any(os.path.lexists(folder / name) for name in (RUN_CONFIG_NAME, INSTRUMENT_CONFIG)):
        return "a run's directory, where its sessions work"
    if os.path.lexists(folder / MANIFEST_NAME):
        return "an installation sessions run from"
    if REVIEW_ID.fullmatch(folder.name) and any(
        os.path.isdir(folder / name) for name in (READ_DIRNAME, SESSION_DIRNAME)
    ):
        return "a review's directory, where a reviewer reads"
    return None


def _held(real: Path) -> str | None:
    """What a folder directly beneath ``real`` is, if one is a run, an installation or a review.

    Raises:
        OSError: ``real`` cannot be listed.
    """
    with os.scandir(real) as entries:
        children = sorted(entry.name for entry in entries if entry.is_dir())
    for name in children:
        what = _marked(real / name)
        if what is not None:
            return what
    return None


def _ui_refusal(real: Path, harness: Path | None) -> str | None:
    """Why the operator UI would refuse ``real`` as a root, in its own words, or ``None``."""
    from physgate.ui.exceptions import StartupRefusedError
    from physgate.ui.paths import Allowlist

    try:
        Allowlist.build([str(real)], held_out=(), answer_keys=(), harness=harness)
    except StartupRefusedError as exc:
        return str(exc)
    return None


def _place_refusal(real: Path, places: KnownPlaces) -> str | None:
    """Why the real folder ``real`` is a place a session, a reviewer or a commit reaches."""
    from physgate.reviewers.places import inside_a_checkout

    if places.harness is not None:
        harness = Path(os.path.realpath(places.harness))
        if _inside(real, harness) or _inside(harness, real):
            return "lies in the harness's own checkout or holds it"
    for temp in places.shared_temps:
        if _inside(real, Path(os.path.realpath(temp))):
            return "lies in the machine's shared temporary directory, which every session reads"
    review = Path(os.path.realpath(places.review_root))
    if _inside(real, review) or _inside(review, real):
        return "lies in the review root, where reviewers read, or holds it"
    for folder in (real, *real.parents):
        what = _marked(folder)
        if what is not None:
            return f"lies in {what}"
    if inside_a_checkout(real) is not None:
        return (
            "lies in a git checkout or worktree (a run's target, one of its worktrees, or another)"
        )
    try:
        what = _held(real)
    except OSError:
        return "cannot be listed, so what it holds cannot be told"
    if what is not None:
        return f"holds {what}"
    why = _ui_refusal(real, places.harness)
    if why is not None:
        return f"is one the operator UI would refuse to read ({why})"
    return None


def folder_refusal(out: Path, store: Path, places: KnownPlaces) -> str | None:
    """Why ``out`` may not hold a publication, or ``None``: a folder of its own, not the store's.

    The one judgement of a folder to publish into, used by every publication made for the page.
    """
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
    why = _place_refusal(real, places)
    if why is not None:
        return f"the folder to publish into {why}, so it may not hold a publication"
    return None


def beside_another(out: Path, names: Iterable[str], what: str) -> str | None:
    """Why ``out`` holds another publication made for the page (``what``, in words), or ``None``.

    Each publication is written into a folder of its own, so one never blocks the other's.
    """
    found = frozenset(names)
    try:
        with os.scandir(out) as entries:
            held = any(entry.name in found for entry in entries)
    except OSError:
        return "the folder to publish into cannot be listed"
    if held:
        return (
            f"the folder to publish into holds {what}; each publication made for the page is "
            "published into a folder of its own"
        )
    return None


def _stage(fd: int, name: str, data: bytes) -> str:
    """Write ``data`` whole beneath ``fd`` under a temporary name beside ``name``; that name."""
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
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(partial, dir_fd=fd)
        raise
    return partial


def _remove_every(fd: int, names: Iterable[str]) -> bool:
    """Remove each of ``names`` beneath ``fd``; whether none of them is left."""
    gone = True
    for name in names:
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            continue
        except OSError:
            gone = False
    return gone


def write_all(out: Path, files: Mapping[str, bytes], *, what: str) -> None:
    """Write every one of ``files`` (``what`` they are, in words) into ``out`` whole, or none.

    Each is written whole under a temporary name first, and only once all are written are they
    renamed into place. If any step fails, every temporary file and every copy published before
    under the names is removed, so no older copy reads as current, and none beside a newer one.

    Raises:
        GapsError: the folder cannot be opened, or a file cannot be written; the copies before
            them are then removed, and the sentence says whether they could be.
    """
    try:
        fd = os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        msg = f"the folder to publish into cannot be opened ({os.strerror(exc.errno or 0)})"
        raise _refuse("publish_failed", msg) from None
    staged: list[str] = []
    try:
        try:
            for name, data in files.items():
                staged.append(_stage(fd, name, data))
            for partial, name in zip(staged, files, strict=True):
                os.replace(partial, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        except OSError as exc:
            _remove_every(fd, staged)
            gone = _remove_every(fd, files)
            done = (
                "what was published before is removed, so the page shows none rather than an "
                "older copy"
                if gone
                else "what was published before could not all be removed: remove it by hand, "
                "or the page shows it as it was"
            )
            msg = f"{what} could not be written ({os.strerror(exc.errno or 0)}); {done}"
            raise _refuse("publish_failed", msg) from None
    finally:
        os.close(fd)


def write_whole(out: Path, name: str, data: bytes, *, what: str) -> None:
    """Write ``data`` (``what`` it is, in words) to ``out/name`` whole, or remove the copy before.

    Raises:
        GapsError: as :func:`write_all` does for one file.
    """
    write_all(out, {name: data}, what=what)


def _tier_status_names() -> frozenset[str]:
    """The tier status's publications' names, as its own module gives them."""
    from physgate.evaluation.tiers.published import ROLES as TIER_ROLES
    from physgate.evaluation.tiers.published import published_name as tier_status_name

    return frozenset(tier_status_name(role) for role in TIER_ROLES)


def publish_trend(
    trend: Path, *, store: Path, role: RoleName, out: Path, now: datetime | None = None
) -> Path:
    """Publish ``role``'s trend, as its reader reads it now, into the folder ``out``; its path.

    A trend the reader refuses is published as the refusal, replacing what was there, and so is
    any other failure once ``out`` is judged a folder of its own.

    Raises:
        GapsError: asked for inside a harness session; ``out`` is not a folder of its own (it
            is missing, a link, in the store or holds it, holds the published tier status, or
            in a place a run's sessions, a reviewer or a commit reach); or the publication
            cannot be written, and the copy before it is then removed.
    """
    found = sorted(name for name in SESSION_MARKERS if name in os.environ)
    if found:
        msg = f"the gap trend is published by a person, never from a session ({', '.join(found)})"
        raise _refuse("inside_a_session", msg)
    refusal = folder_refusal(Path(out), Path(store), known_places())
    if refusal is None:
        refusal = beside_another(Path(out), _tier_status_names(), "the published tier status")
    if refusal is not None:
        raise _refuse("publish_refused", f"{refusal}. {WHERE_TO_PUBLISH}")
    read_at = now or datetime.now(UTC)
    try:
        record = read_for_publication(trend, store=store, role=role, now=read_at)
    except Exception as exc:  # noqa: BLE001 - any failure once the folder is judged is published
        record = _failed(role, read_at, exc)
    name = published_name(role)
    data = record.model_dump_json().encode() + b"\n"
    write_whole(Path(out), name, data, what="the gap trend")
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
            "the published gap trend is not a file the publish command wrote: it was cut, "
            "edited or written by something else; publish it again"
        )
        raise _refuse("publication_unreadable", msg) from None
    if published.role != role:
        msg = f"the published gap trend under the {role} role's name is another role's"
        raise _refuse("publication_unreadable", msg)
    return published
