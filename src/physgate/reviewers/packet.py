"""Everything a review is shown, written into the one directory the reviewer may read.

A review's directory (``places.review_dir``) gets a ``read/`` directory holding:

- ``transcript-NN-of-MM.md``: the attempt's trajectory, in numbered parts. The
  trajectory is every session of the attempt, in order: a session that ended for
  infrastructure was followed by a fresh one in the same worktree, and each is part
  of what the attempt did. Each session's stream is read from the file it names
  only after its bytes are held to the seal taken when that session ended, and is
  rendered whole (``transcript.render``) under its own data marker. An artefact no
  session produced carries a written account instead, which is used as it is.
- ``worktree/``: the attempt's commit, exported. Not the implementing session's
  worktree: an export holds exactly what was committed, and no ``.git`` that points
  back into the target repository. A symbolic link in the commit is written as a
  note naming its target, never as a link, so nothing in the export reaches outside.
- ``diff-NN-of-MM.patch``: the attempt's change against where it left the run branch,
  in numbered parts.

The export and the diff leave out the attempt's disputes (``orchestrator.dispute``): a
dispute is a role's position for a person to arbitrate, recorded on the run's log, and the
reviewer judges the work without another session's free text in it.
- ``series-NN-of-MM.md``: for an attempt that sealed simulation records or named one
  from a graph quantity, the harness's listing of them (``series.summary``): each
  record summarised from its own samples, read back held to its seal, and each
  quantity's check against the record it names. Absent for an attempt with none.
- ``spec_as_issued.md``: the module specification exactly as the decomposition
  issued it, read from the commit that issued it. The attempt can edit its own
  specification, and the worktree's copy then says what the attempt made it say;
  only the issued one counts, and the diff shows any edit.
- ``rubric.md``: the role's rubric, its digest checked again against the one it
  was loaded with.
- ``person_order.md``: for an attempt a person ordered (the one fix after a review that
  blocked, or a retry after a person's reject), what it is and the exact instruction its
  session was given, quoted under a fixed label. Absent for every other attempt.
- ``integration_state.md``: for an attempt of integration's subtask, the issued state its session
  read, byte for byte (``orchestrator.integration_state``), held to the digest its line records.
  Absent for every other attempt.
- ``knowledge/``: the role's curated library files, copied from the harness; for a
  generalist review, only the standards every role reads.
- ``files-NN-of-MM.md``: the listing of every other file above, by full path and size,
  written last and read first. The reviewer has the Read tool and nothing that lists a
  directory, so a name it would otherwise guess is named here, and a name the listing
  does not hold does not exist.

**The transcript and the diff are issued in parts** cut at line boundaries, each one
small enough for the Read tool to show whole in one read (:data:`PART_MAX_BYTES`,
:data:`PART_MAX_LINES`), because a reader paging through a longer file was refused
for size and lost its place. Nothing is trimmed: the parts joined are the rendering
and the diff byte for byte, which :func:`check_parts` confirms against the seals and
the repository before the review starts; the listing's parts joined are held the same
way to the read directory as it then stands. A single line too long for one read is
refused when the packet is built.

What a review must read in full before it may answer is listed in
:attr:`Packet.required_reading`, and the hook layer refuses the verdict until it
has: every part of the file listing, of the transcript, of the diff and of the series
listing, the rubric, the issued specification, integration's issued state and the person's
order when there is one, and the library files.

The packet's own record (``packet.json``) sits beside ``read/``, outside it: it
holds every digest above and the observable indicators the trajectory shows
(``scan.scan``), and the reviewer reads none of it but the indicators, which go
into its prompt.
"""

from __future__ import annotations

import atexit
import functools
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
)

from physgate.knowledge import loader
from physgate.knowledge.library import LibraryError, read_library
from physgate.orchestrator.dispute import DISPUTES_DIR
from physgate.orchestrator.exceptions import GitError, TrajectoryTamperedError
from physgate.orchestrator.git import (
    EMPTY_TREES,
    FORCED_ENV,
    FORCED_FLAGS,
    GitDir,
    attr_source,
    harness_git,
    object_dirs,
    object_format,
    verified_git_dir,
)
from physgate.orchestrator.protocols import Artefact, IssuedSpec, PersonOrder
from physgate.orchestrator.repair import quoted
from physgate.orchestrator.trajectory import Seal, read_sealed
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import READ_DIRNAME
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.scan import ScanHit, ScanUnreadableError, scan
from physgate.reviewers.transcript import render
from physgate.series.exceptions import SeriesError
from physgate.series.summary import SERIES_PART, listing

TRANSCRIPT_NAME = "transcript.md"
WORKTREE_NAME = "worktree"
DIFF_NAME = "diff.patch"
#: The names of the parts the transcript and the diff are issued in.
TRANSCRIPT_PART = "transcript-{n:02d}-of-{total:02d}.md"
DIFF_PART = "diff-{n:02d}-of-{total:02d}.patch"
#: The names of the parts the listing of the read directory is issued in.
FILES_PART = "files-{n:02d}-of-{total:02d}.md"
#: The most one part holds. The Read tool shows a file whole only up to 256 KB and
#: 25,000 tokens, and at most 2,000 lines without an offset (measured on 2.1.283: a
#: 500-line page of a transcript was 33,022 tokens, about 0.82 per byte with its line
#: numbers). 20,000 bytes stays under the token limit even at one token per byte.
PART_MAX_BYTES = 20_000
PART_MAX_LINES = 2_000


def fits_one_read(data: bytes) -> bool:
    """Whether ``data``, issued as one file, is shown whole by one read."""
    return len(data) <= PART_MAX_BYTES and data.count(b"\n") <= PART_MAX_LINES


SPEC_AS_ISSUED_NAME = "spec_as_issued.md"
RUBRIC_NAME = "rubric.md"
PERSON_ORDER_NAME = "person_order.md"
INTEGRATION_STATE_NAME = "integration_state.md"
KNOWLEDGE_NAME = "knowledge"
RECORD_NAME = "packet.json"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class PacketError(ReviewError):
    """A review cannot be prepared as specified, so it does not run."""


_PART_NAME = r"^(transcript|diff|series|files)-[0-9]{2,}-of-[0-9]{2,}\.(md|patch)$"


class Part(BaseModel):
    """One numbered part of the transcript or the diff, as written."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Annotated[str, StringConstraints(pattern=_PART_NAME)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(ge=0)]
    lines: Annotated[int, Field(ge=0)]


class Packet(BaseModel):
    """What one review was shown, by path and digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    read_root: Annotated[str, StringConstraints(min_length=1)]
    #: The trajectory as the packet read it: held to the session's seal first.
    trajectory_seal: Seal
    transcript_sha256: Sha256
    #: The nonce the transcript's data fences carry; ``None`` for a written account.
    transcript_nonce: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] | None
    diff_sha256: Sha256
    #: ``None`` for an artefact no decomposition issued a specification for.
    spec_as_issued_sha256: Sha256 | None
    rubric_sha256: Sha256
    knowledge_sha256: dict[str, Sha256]
    #: How many files the attempt's commit holds, as exported: its disputes left out.
    worktree_files: Annotated[int, Field(ge=0)]
    indicators: tuple[ScanHit, ...]
    required_reading: Annotated[tuple[str, ...], Field(min_length=2)]
    #: The attempt as the review was given it, so the same attempt can be reviewed
    #: again (the generalist baseline) and held to the same seal and commit.
    artefact: Artefact | None = None
    #: Every session's seal, in the order the transcript shows them; the last is
    #: :attr:`trajectory_seal`. Empty in a packet recorded before sessions were joined.
    session_seals: tuple[Seal, ...] = ()
    #: Each session's data-fence nonce, in the same order.
    transcript_nonces: tuple[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")], ...] = ()
    transcript_parts: tuple[Part, ...] = ()
    diff_parts: tuple[Part, ...] = ()
    #: The series listing's digest and parts, for an attempt with simulation records. Left
    #: out of the record when absent, so a packet without them reads and hashes as before.
    series_sha256: Sha256 | None = None
    series_parts: tuple[Part, ...] = ()
    #: The listing of every other file under ``read/``, by full path. Empty in a packet
    #: recorded before the listing was issued.
    files_parts: tuple[Part, ...] = ()
    #: The digest of ``person_order.md``, for an attempt a person ordered. Left out of the
    #: record when absent, so every other packet reads and hashes as before.
    person_order_sha256: Sha256 | None = None
    #: The digest of ``integration_state.md``, for an attempt of integration's subtask. Left out
    #: of the record when absent, so every other packet reads and hashes as before.
    integration_state_sha256: Sha256 | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_series(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.series_sha256 is None:
            data.pop("series_sha256", None)
        if not self.series_parts:
            data.pop("series_parts", None)
        if self.person_order_sha256 is None:
            data.pop("person_order_sha256", None)
        if self.integration_state_sha256 is None:
            data.pop("integration_state_sha256", None)
        return data

    def sha256(self) -> str:
        """The digest of this record: what a review line carries to name its packet."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: Git as the packet runs it: the harness's one git binary (``harness_git``, never a
#: lookup on ``PATH``), with the forced core every harness git runs with (``FORCED_ENV`` and
#: ``FORCED_FLAGS``: replacement objects ignored, no system or user configuration, no
#: attributes file, no hooks, no file-system monitor, no shallow, graft or commit-graph file),
#: and attributes taken from the empty tree of the store's object format (``--attr-source``
#: and ``GIT_ATTR_SOURCE``). An attempt's session can add a replacement object, which would
#: change what a commit is shown to hold, commit an attribute file, which would hide or
#: rewrite a file in an archive or a diff, or leave a commit graph in an object directory the
#: store reaches, whose stored root trees would change the diff the reviewer reads.
_GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/dev/null", **FORCED_ENV}
_GIT_FLAGS = (*FORCED_FLAGS, "-c", "core.quotePath=false")


def _git_dir(repo: Path) -> GitDir:
    """The repository's git directory, resolved and verified from the filesystem without git.

    A normal repository keeps it at ``.git``; a ``git worktree`` checkout keeps a ``.git``
    file naming its admin directory, whose ``commondir`` names the directory its objects and
    config are read from. The packet reads through that ``commondir`` (the object store, the
    object format), so it is held to the harness's own check first (``verified_git_dir``): a
    pointer whose admin directory's ``gitdir`` does not point back at it, or whose
    ``commondir`` names any directory but the one the admin directory sits in, a ``.git`` that
    is a link, or a repository's own git directory that names a ``commondir``, is refused.
    What is returned carries the common directory the check confirmed, and every reader takes
    it from there, never reading ``commondir`` again. The check reads bytes on disk, so no
    configuration, hook or program is consulted.
    """
    try:
        return verified_git_dir(Path(repo), linked=False)
    except GitError as exc:
        msg = f"the attempt's repository has no git directory the review can verify: {exc}"
        raise PacketError(msg, **{**exc.context, "repo": str(repo)}) from None


def _place(repo: Path | GitDir) -> GitDir:
    """``repo`` verified, unless it already is: one check per sequence of reads."""
    return repo if isinstance(repo, GitDir) else _git_dir(repo)


def _object_dirs(where: GitDir) -> list[str]:
    """Every object directory the attempt's commits are read from (``git.object_dirs``).

    Each is a store of content-addressed objects: naming one grants only read access to objects
    a commit already pins, never a way to change what a commit holds, and never anything git
    would run. Alternates are followed by the store's own git, as git reads them.
    """
    try:
        return list(object_dirs(where))
    except GitError as exc:
        raise PacketError(str(exc), **{**exc.context, "repo": str(where.path)}) from None


_STORES: list[str] = []


@atexit.register
def _remove_stores() -> None:
    for store in _STORES:
        shutil.rmtree(store, ignore_errors=True)


def _object_format(where: GitDir) -> str:
    """The hash the attempt's repository names its objects with, as git decides it.

    The store must use the same one: a store of the other format cannot read a single object
    through its alternates. Read by the harness's one reader (``git.object_format``): git's own
    config parser run outside the repository on its config file, with git's rules for which
    format versions honour the setting, so no git command runs inside the attempt's repository.
    """
    try:
        return object_format(where)
    except GitError as exc:
        msg = "the attempt's object format cannot be read, or the review's store cannot use it"
        raise PacketError(msg, **{**exc.context, "repo": str(where.path)}) from None


@functools.cache
def _object_store(object_dirs: tuple[str, ...], object_format: str) -> str:
    """A throwaway bare git directory that reaches ``object_dirs`` and holds nothing else.

    Every packet git command runs against this, never with its working directory inside the
    attempt's repository, so that repository's own configuration, its ``.gitattributes``, its
    ``include`` paths and any submodule's configuration are never read and can run nothing.
    The store reaches the attempt's objects through ``alternates`` (read-only), carries a clean
    configuration, and has no working tree and no submodules, so a committed submodule is shown
    as its gitlink rather than recursed into — which is where the local configuration otherwise
    runs a program. It is created with the attempt's ``object_format``.
    """
    store = tempfile.mkdtemp(prefix="physgate-review-store-")
    _STORES.append(store)
    done = subprocess.run(
        [_git_path(), attr_source(object_format), *_GIT_FLAGS, "init", "-q", "--bare",
         f"--object-format={object_format}", store],
        capture_output=True,
        check=False,
        env={**_GIT_ENV, "GIT_ATTR_SOURCE": EMPTY_TREES[object_format]},
    )  # fmt: skip
    if done.returncode != 0:
        msg = "git could not prepare the object store the review reads"
        raise PacketError(msg, stderr=done.stderr.decode()[-300:])
    (Path(store) / "objects" / "info" / "alternates").write_text("\n".join(object_dirs) + "\n")
    return store


def _git_path() -> str:
    """The harness's git binary, by absolute path.

    Raises:
        PacketError: no git at 2.42 or later is found.
    """
    try:
        return harness_git().path
    except GitError as exc:
        raise PacketError(str(exc), **exc.context) from None


def _git_bytes(repo: Path | GitDir, *args: str) -> bytes:
    where = _place(repo)
    object_format = _object_format(where)
    store = _object_store(tuple(_object_dirs(where)), object_format)
    done = subprocess.run(
        [_git_path(), attr_source(object_format), "--git-dir", store, *_GIT_FLAGS, *args],
        cwd=store,
        capture_output=True,
        check=False,
        env={**_GIT_ENV, "GIT_ATTR_SOURCE": EMPTY_TREES[object_format]},
    )
    if done.returncode != 0:
        msg = "git could not produce what the review is shown"
        raise PacketError(msg, command=" ".join(args[:2]), stderr=done.stderr.decode()[-300:])
    return done.stdout


def issued_spec_sha256(repo: Path, commit: str, path: str) -> str:
    """The digest of the specification ``commit`` issued at ``path``, read from git's objects.

    Taken before the session is spawned, so the review can hold the bytes it reads
    to it.

    Raises:
        PacketError: git cannot read it.
    """
    return _digest(_git_bytes(_git_dir(Path(repo)), "cat-file", "blob", f"{commit}:{path}"))


def _sealed(artefact: Artefact) -> list[tuple[str, bytes, Seal]]:
    """Every session's stream of the attempt, in order, each held to its seal."""
    if artefact.trajectory_sha256 is None or artefact.trajectory_length is None:
        msg = "a review reads a trajectory held to its seal, and this attempt carries none"
        raise PacketError(msg, subtask=artefact.subtask_id, trajectory=artefact.trajectory)
    sessions = [
        (s.trajectory, Seal(sha256=s.trajectory_sha256, length=s.trajectory_length))
        for s in artefact.earlier_sessions
    ]
    final = Seal(sha256=artefact.trajectory_sha256, length=artefact.trajectory_length)
    sessions.append((artefact.trajectory, final))
    found = []
    for path, expected in sessions:
        try:
            data = read_sealed(Path(path), expected)
        except TrajectoryTamperedError as exc:
            raise PacketError(str(exc), **exc.context) from None
        found.append((path, data, expected))
    if not found[-1][1].strip():
        msg = "a review reads the whole trajectory, and this one is empty"
        raise PacketError(msg, trajectory=artefact.trajectory)
    return found


#: Before a transcript of more than one session, the harness's own lines.
SESSIONS_PREFACE = (
    "This attempt ran in {total} sessions, shown in order. A session that ended for\n"
    "infrastructure (its turn limit, its wall clock, an API error) was followed by a\n"
    "fresh session in the same worktree, which carried on from the files the earlier one\n"
    "left. Each session below has its own data marker.\n"
)


def _decoded(path: str, data: bytes) -> str:
    try:
        # The bytes the seal covers, decoded once and strictly: a stream that is not
        # UTF-8 is not one the runtime wrote, and replacing what does not decode
        # would show the reviewer something the seal does not cover.
        return data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "the trajectory is not UTF-8, so it is not a stream the runtime wrote"
        raise PacketError(msg, trajectory=path) from None


def indicator_scan_runs(artefact: Artefact | None) -> bool:
    """Whether the marker scan (``scan.scan``) is run on this attempt's trajectory.

    Only a session's own stream is scanned. A written account (the instrument's) is shown
    as it is and never scanned, so an empty list of indicators says nothing about it.
    """
    return artefact is not None and artefact.trajectory_form == "session_stream"


def _rendered(
    artefact: Artefact, sessions: list[tuple[str, bytes, Seal]], nonces: tuple[str, ...] = ()
) -> tuple[bytes, tuple[ScanHit, ...], tuple[str, ...]]:
    """The transcript of every session, the indicators it shows, and each session's nonce.

    Given ``nonces`` (the ones a packet recorded), it renders with them, so the same
    sealed streams give the same bytes again.
    """
    if not indicator_scan_runs(artefact):
        return sessions[-1][1], (), ()
    streams = [_decoded(path, data) for path, data, _ in sessions]
    if nonces and len(nonces) != len(streams):
        msg = "the packet's nonces do not match the attempt's sessions"
        raise PacketError(msg, subtask=artefact.subtask_id)
    chosen: list[str] = list(nonces)
    while len(chosen) < len(streams):
        candidate = secrets.token_hex(8)
        if candidate not in chosen and not any(candidate in stream for stream in streams):
            chosen.append(candidate)
    indicators: list[ScanHit] = []
    pieces = []
    for number, (stream, nonce) in enumerate(zip(streams, chosen, strict=True), start=1):
        try:
            indicators.extend(scan(stream))
        except ScanUnreadableError as exc:
            raise PacketError(str(exc), trajectory=sessions[number - 1][0]) from None
        text, used = render(stream, nonce=nonce)
        if used != nonce:
            msg = "a session's transcript could not use its recorded nonce"
            raise PacketError(msg, trajectory=sessions[number - 1][0])
        heading = f"# Session {number} of {len(streams)}\n\n" if len(streams) > 1 else ""
        pieces.append(heading + text)
    if len(streams) > 1:
        pieces.insert(0, SESSIONS_PREFACE.format(total=len(streams)))
    return "\n".join(pieces).encode("utf-8"), tuple(indicators), tuple(chosen)


def split_parts(data: bytes, pattern: str) -> list[tuple[str, bytes]]:
    """``data`` cut at line boundaries into parts one read can show whole, named by ``pattern``.

    Raises:
        PacketError: a single line is longer than one part may be.
    """
    parts: list[list[bytes]] = []
    size = 0
    for line in data.splitlines(keepends=True):
        if len(line) > PART_MAX_BYTES:
            msg = "a line is longer than one read can show whole, so it cannot be issued"
            raise PacketError(msg, bytes=str(len(line)), limit=str(PART_MAX_BYTES))
        if not parts or size + len(line) > PART_MAX_BYTES or len(parts[-1]) >= PART_MAX_LINES:
            parts.append([])
            size = 0
        parts[-1].append(line)
        size += len(line)
    if not parts:
        parts.append([])
    total = len(parts)
    return [
        (pattern.format(n=number, total=total), b"".join(lines))
        for number, lines in enumerate(parts, start=1)
    ]


#: What the listing says before its lines. The reviewer has the Read tool and nothing that
#: lists a directory, so without it a reviewer guesses names (measured: three reads of
#: names that did not exist, and eight reads of a directory, in six reviews).
LISTING_HEAD = (
    "# Every file you may read\n\n"
    "These are all the files under {read}/, one per line, by full path and size. A "
    "directory cannot be read, and a name it does not list does not exist: open only the "
    "paths below, with the Read tool. This list is itself issued in the files-NN-of-MM.md "
    "parts beside them.\n\n"
)
_LISTED = re.compile(r"^- (.+) \(([0-9]+) bytes\)$")


def file_listing(read: Path, own: set[str]) -> bytes:
    """The listing of every file under ``read``, but the names in ``own`` directly beneath it.

    One line per file, ``- <full path> (<n> bytes)``, in the order of the paths beneath
    ``read``. Only files are listed; a directory is never read.

    Raises:
        PacketError: a path holds a control character, which would break its line.
    """
    read = Path(read)
    lines = [LISTING_HEAD.format(read=read).encode()]
    for path in sorted(read.rglob("*"), key=lambda p: p.relative_to(read).as_posix()):
        if not path.is_file() or (path.parent == read and path.name in own):
            continue
        relative = path.relative_to(read).as_posix()
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in relative):
            msg = "a path in the packet holds a control character, so it cannot be listed"
            raise PacketError(msg, path=repr(relative))
        lines.append(f"- {path} ({path.stat().st_size} bytes)\n".encode())
    return b"".join(lines)


def listed_paths(listing: str) -> list[str]:
    """The paths a listing names, in its order."""
    return [m.group(1) for line in listing.splitlines() if (m := _LISTED.fullmatch(line))]


def _write_parts(read: Path, parts: list[tuple[str, bytes]]) -> tuple[Part, ...]:
    written = []
    for name, body in parts:
        if len(body) > PART_MAX_BYTES or body.count(b"\n") > PART_MAX_LINES:
            msg = "a part is more than one read can show whole"
            raise PacketError(msg, part=name, bytes=str(len(body)))
        (read / name).write_bytes(body)
        written.append(
            Part(name=name, sha256=_digest(body), bytes=len(body), lines=len(body.splitlines()))
        )
    return tuple(written)


def _export(repo: Path | GitDir, commit: str, into: Path) -> int:
    """Write ``commit``'s files, its disputes left out, under ``into``: no attribute applied.

    Not ``git archive``, which honours an attribute file committed in the tree: one
    can leave a file out of the archive or rewrite it on the way, so the reviewer
    would read something other than the commit. A symbolic link becomes a note naming
    its target, and a submodule a note naming its commit, so nothing exported reaches
    outside.

    Raises:
        PacketError: git cannot list or read the tree, or a path leaves the export.
    """
    repo = _place(repo)
    listing = _git_bytes(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    entries = []
    for entry in listing.split(b"\0"):
        if entry:
            meta, _, raw_path = entry.partition(b"\t")
            mode, kind, oid = meta.decode().split()
            if not raw_path.startswith(DISPUTES_DIR.encode() + b"/"):
                entries.append((mode, kind, oid, raw_path.decode("utf-8")))
    _refuse_merging_paths([relative for _, _, _, relative in entries])
    into.mkdir()
    root = into.resolve()
    written: dict[Path, bytes] = {}
    for mode, kind, oid, relative in entries:
        target = (into / relative).resolve()
        if (
            relative.startswith("/")
            or ".." in Path(relative).parts
            or not target.is_relative_to(root)
        ):
            msg = "a path in the commit leaves the export"
            raise PacketError(msg, path=relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "commit":
            body = f"[a submodule at commit {oid}]\n".encode()
        elif mode == "120000":
            link = _git_bytes(repo, "cat-file", "blob", oid).decode("utf-8", errors="replace")
            body = f"[a symbolic link to: {link}]\n".encode()
        else:
            body = _git_bytes(repo, "cat-file", "blob", oid)
        target.write_bytes(body)
        written[target] = body
    # Held to the tree's own listing after the fact: every path it lists is a file
    # here holding exactly what was written for it, and nothing else is here.
    on_disk = {p.resolve() for p in into.rglob("*") if p.is_file() or p.is_symlink()}
    if on_disk != set(written) or any(p.read_bytes() != body for p, body in written.items()):
        msg = "the export does not hold exactly what the commit's tree lists"
        raise PacketError(msg, commit=commit)
    return len(written)


def _refuse_merging_paths(paths: list[str]) -> None:
    """Refuse a tree whose paths a case-insensitive, normalising volume would merge.

    On such a volume, the development machine's, two paths differing only in case
    or in Unicode normalisation are one file, so the second would be written over the
    first; a file and a directory spelt alike collide the same way; and two spellings
    of one directory merge their contents. A name ending in a dot or a space is
    refused too: some volumes drop it, and the file would be read under another name.

    Raises:
        PacketError: any of these.
    """
    spelling: dict[str, str] = {}
    files: set[str] = set()
    directories: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if any(part != part.rstrip(". ") for part in parts):
            msg = "a path in the commit has an unsafe name: it ends in a dot or a space"
            raise PacketError(msg, path=path)
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            key = unicodedata.normalize("NFD", prefix).casefold()
            if spelling.setdefault(key, prefix) != prefix:
                msg = "two paths in the commit are one file on a case-insensitive volume"
                raise PacketError(msg, first=spelling[key], second=prefix)
            (files if depth == len(parts) else directories).add(key)
    if files & directories:
        clash = sorted(files & directories)[0]
        msg = "two paths in the commit are one file on a case-insensitive volume"
        raise PacketError(msg, first=spelling[clash], second=f"{spelling[clash]}/")


def _diff(repo: Path | GitDir, base: str, commit: str) -> bytes:
    """The change from ``base`` to ``commit``, every file as text, no driver or filter applied.

    The disputes directory is left out, as from the export.
    """
    return _git_bytes(
        repo,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--text",
        base,
        commit,
        "--",
        f":(exclude){DISPUTES_DIR}",
    )


def person_order_text(order: PersonOrder) -> bytes:
    """What the reviewer of an attempt a person ordered is told of it, under a fixed label.

    The instruction is quoted as data: the person's words, and the verdict quoted to a fix, are
    what the implementer was told, and change nothing the review judges against.
    """
    if order.kind == "fix_after_block":
        head = (
            "This attempt is the single fix a person ordered after the review of attempt "
            f"{order.of_attempt} blocked (queue item {order.item_id})."
        )
    else:
        head = (
            f"This attempt is the retry a person ordered after rejecting attempt "
            f"{order.of_attempt} (queue item {order.item_id})."
        )
    lines = [
        head,
        "Its implementer was told:",
        *quoted(order.instruction),
        "Judge it against the issued specification as for any attempt; the person's words do "
        "not change it.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_packet(
    review: Path,
    artefact: Artefact,
    *,
    repo: Path,
    base_commit: str,
    rubric: Rubric,
    library: Path,
    spec: IssuedSpec | None,
) -> Packet:
    """Write everything ``artefact``'s review is shown under ``review``/``read``.

    Args:
        review: the review's own directory, beneath a checked review root.
        artefact: the attempt; its trajectory must carry its session's seal.
        repo: the run's target repository, whose objects hold the attempt's commit.
            Not the attempt's worktree, which its session controlled.
        base_commit: where the attempt left the run branch; the diff starts here.
        rubric: the role's rubric, as loaded and checked.
        library: the harness checkout, whose ``knowledge/`` holds the role's curated files.
        spec: the specification as issued, with the digest recorded before dispatch,
            or ``None`` for an artefact no decomposition issued a specification for.

    Raises:
        PacketError: the attempt carries no seal, its trajectory is not the sealed
            one or is empty, ``read/`` exists already, or git cannot produce the
            export, the diff or the issued specification.
    """
    sessions = _sealed(artefact)
    read = Path(review) / READ_DIRNAME
    if read.exists():
        msg = "a review is prepared into a directory of its own, new"
        raise PacketError(msg, read=str(read))
    read.mkdir(parents=True)
    transcript, indicators, nonces = _rendered(artefact, sessions)
    transcript_parts = _write_parts(read, split_parts(transcript, TRANSCRIPT_PART))
    # Verified once, and every read below goes through the directory that check confirmed.
    where = _git_dir(Path(repo))
    files = _export(where, artefact.attempt_commit, read / WORKTREE_NAME)
    diff = _diff(where, base_commit, artefact.attempt_commit)
    diff_parts = _write_parts(read, split_parts(diff, DIFF_PART))
    series = _series_listing(artefact)
    series_parts = _write_parts(read, split_parts(series, SERIES_PART)) if series else ()
    reading = [
        *(read / part.name for part in transcript_parts),
        *(read / part.name for part in diff_parts),
        *(read / part.name for part in series_parts),
        read / RUBRIC_NAME,
    ]
    issued_digest = None
    if spec is not None:
        issued = _git_bytes(where, "cat-file", "blob", f"{spec.commit}:{spec.path}")
        if _digest(issued) != spec.sha256:
            msg = "the issued specification is not the one recorded before dispatch"
            raise PacketError(msg, path=spec.path, recorded=spec.sha256, found=_digest(issued))
        (read / SPEC_AS_ISSUED_NAME).write_bytes(issued)
        issued_digest = spec.sha256
        reading.append(read / SPEC_AS_ISSUED_NAME)
    state_digest = None
    if artefact.integration_state is not None:
        # What integration's session read, byte for byte, as its line recorded it.
        state = artefact.integration_state
        (read / INTEGRATION_STATE_NAME).write_bytes(state.text.encode("utf-8"))
        state_digest = state.sha256
        reading.append(read / INTEGRATION_STATE_NAME)
    order_digest = None
    if artefact.ordered_by_person is not None:
        order = person_order_text(artefact.ordered_by_person)
        if not fits_one_read(order):
            msg = "the person's order is longer than one read shows whole"
            raise PacketError(msg, bytes=str(len(order)))
        (read / PERSON_ORDER_NAME).write_bytes(order)
        order_digest = _digest(order)
        reading.append(read / PERSON_ORDER_NAME)
    text = rubric.text.encode("utf-8")
    if _digest(text) != rubric.sha256:
        msg = "the rubric is not the one that was loaded"
        raise PacketError(msg, role=rubric.role)
    (read / RUBRIC_NAME).write_bytes(text)
    knowledge: dict[str, str] = {}
    try:
        # A generalist review is shown what every role reads, not the role's own files.
        roles = [loader.CROSS] if rubric.kind == "generalist" else [rubric.role]
        curated = read_library(Path(library), roles)
    except LibraryError as exc:
        raise PacketError(str(exc), **exc.context) from None
    for relative, body in sorted(curated.items()):
        copy = read / KNOWLEDGE_NAME / relative.relative_to(loader.DEFAULT_ROOT)
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(body)
        knowledge[relative.as_posix()] = _digest(body)
        reading.append(copy)
    # Last, once every other file is in place: the listing of them, read first.
    files_parts = _write_parts(read, split_parts(file_listing(read, set()), FILES_PART))
    reading = [*(read / part.name for part in files_parts), *reading]
    packet = Packet(
        read_root=str(read),
        trajectory_seal=sessions[-1][2],
        transcript_sha256=_digest(transcript),
        transcript_nonce=nonces[-1] if nonces else None,
        diff_sha256=_digest(diff),
        spec_as_issued_sha256=issued_digest,
        rubric_sha256=rubric.sha256,
        knowledge_sha256=knowledge,
        worktree_files=files,
        indicators=indicators,
        required_reading=tuple(str(p) for p in reading),
        artefact=artefact,
        session_seals=tuple(seal for _, _, seal in sessions),
        transcript_nonces=nonces,
        transcript_parts=transcript_parts,
        diff_parts=diff_parts,
        series_sha256=_digest(series) if series else None,
        series_parts=series_parts,
        files_parts=files_parts,
        person_order_sha256=order_digest,
        integration_state_sha256=state_digest,
    )
    (Path(review) / RECORD_NAME).write_text(packet.model_dump_json(indent=1) + "\n")
    return packet


def _series_listing(artefact: Artefact) -> bytes | None:
    """The attempt's series listing, or ``None`` for an attempt with no records and no checks.

    Raises:
        PacketError: a record is gone or is not what was sealed when its session ended.
    """
    series = artefact.series
    if series is None or not (series.records or series.checks):
        return None
    try:
        return listing(series)
    except SeriesError as exc:
        raise PacketError(str(exc), **exc.context) from None


def joined_parts(read: Path, parts: tuple[Part, ...]) -> bytes:
    """The parts as written under ``read``, joined in their order."""
    return b"".join((Path(read) / part.name).read_bytes() for part in parts)


def check_parts(packet: Packet, *, repo: Path, base_commit: str) -> None:
    """Hold the issued parts to what they were cut from, before a review starts.

    Each part must be on disk as written; the transcript's parts joined must be the
    rendering of every sealed session again, with the nonces the packet recorded; the
    diff's parts joined must be the repository's diff of the attempt again; the series
    listing's parts joined must be the listing of the attempt's sealed records again, and
    an attempt with records must have one. Nothing trimmed, nothing changed.

    Raises:
        PacketError: a part is missing or changed, or the parts joined are not what
            they were cut from.
    """
    artefact = packet.artefact
    if artefact is None:
        msg = "a packet that names no attempt cannot be held to it"
        raise PacketError(msg, read=packet.read_root)
    read = Path(packet.read_root)
    joined = {}
    issued = (
        ("transcript", packet.transcript_parts),
        ("diff", packet.diff_parts),
        ("listing", packet.files_parts),
    )
    for kind, parts in issued:
        if not parts:
            msg = f"the packet issued no {kind} parts"
            raise PacketError(msg, read=str(read))
        bodies = []
        for part in parts:
            path = read / part.name
            body = path.read_bytes() if path.is_file() else None
            if body is None or _digest(body) != part.sha256:
                msg = f"a {kind} part is missing or is not what was issued"
                raise PacketError(msg, part=part.name)
            bodies.append(body)
        joined[kind] = b"".join(bodies)
    transcript, _, _ = _rendered(artefact, _sealed(artefact), packet.transcript_nonces)
    if joined["transcript"] != transcript or _digest(transcript) != packet.transcript_sha256:
        msg = "the transcript's parts joined are not the sealed trajectory's rendering"
        raise PacketError(msg, read=str(read))
    diff = _diff(Path(repo), base_commit, artefact.attempt_commit)
    if joined["diff"] != diff or _digest(diff) != packet.diff_sha256:
        msg = "the diff's parts joined are not the attempt's diff"
        raise PacketError(msg, read=str(read))
    _check_series_parts(packet, artefact, read)
    _check_person_order(packet, artefact, read)
    _check_integration_state(packet, artefact, read)
    # The listing names every file under ``read/`` as it stands now, and nothing else.
    if joined["listing"] != file_listing(read, {part.name for part in packet.files_parts}):
        msg = "the listing's parts joined are not the files under the read directory"
        raise PacketError(msg, read=str(read))


def _check_series_parts(packet: Packet, artefact: Artefact, read: Path) -> None:
    """Hold the series listing's parts to the listing of the attempt's sealed records again."""
    series = _series_listing(artefact)
    if series is None:
        if packet.series_parts or packet.series_sha256 is not None:
            msg = "the packet issued a series listing for an attempt with no records"
            raise PacketError(msg, read=str(read))
        return
    if not packet.series_parts:
        msg = "the attempt has simulation records, and the packet issued no listing of them"
        raise PacketError(msg, read=str(read))
    bodies = []
    for part in packet.series_parts:
        path = read / part.name
        body = path.read_bytes() if path.is_file() else None
        if body is None or _digest(body) != part.sha256:
            msg = "a series part is missing or is not what was issued"
            raise PacketError(msg, part=part.name)
        bodies.append(body)
    if b"".join(bodies) != series or _digest(series) != packet.series_sha256:
        msg = "the series parts joined are not the listing of the attempt's sealed records"
        raise PacketError(msg, read=str(read))


def _check_integration_state(packet: Packet, artefact: Artefact, read: Path) -> None:
    """Hold ``integration_state.md`` to the attempt's issued state: there exactly when it is."""
    path = read / INTEGRATION_STATE_NAME
    state = artefact.integration_state
    if state is None:
        if packet.integration_state_sha256 is not None or path.exists():
            msg = "the packet issued an issued state for an attempt that carries none"
            raise PacketError(msg, read=str(read))
        return
    found = _digest(path.read_bytes()) if path.is_file() else None
    if packet.integration_state_sha256 != state.sha256 or found != state.sha256:
        msg = "integration's issued state is missing or is not the one its session read"
        raise PacketError(msg, read=str(read))


def _check_person_order(packet: Packet, artefact: Artefact, read: Path) -> None:
    """Hold ``person_order.md`` to the order the attempt carries: there exactly when it does."""
    path = read / PERSON_ORDER_NAME
    order = artefact.ordered_by_person
    if order is None:
        if packet.person_order_sha256 is not None or path.exists():
            msg = "the packet issued a person's order for an attempt no person ordered"
            raise PacketError(msg, read=str(read))
        return
    expected = _digest(person_order_text(order))
    found = _digest(path.read_bytes()) if path.is_file() else None
    if packet.person_order_sha256 != expected or found != expected:
        msg = "the person's order is missing or is not the one the attempt carries"
        raise PacketError(msg, read=str(read))
