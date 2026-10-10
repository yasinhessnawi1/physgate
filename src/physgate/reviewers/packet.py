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
- ``spec_as_issued.md``: the module specification exactly as the decomposition
  issued it, read from the commit that issued it. The attempt can edit its own
  specification, and the worktree's copy then says what the attempt made it say;
  only the issued one counts, and the diff shows any edit.
- ``rubric.md``: the role's rubric, its digest checked again against the one it
  was loaded with.
- ``knowledge/``: the role's curated library files, copied from the harness; for a
  generalist review, only the standards every role reads.

**The transcript and the diff are issued in parts** cut at line boundaries, each one
small enough for the Read tool to show whole in one read (:data:`PART_MAX_BYTES`,
:data:`PART_MAX_LINES`), because a reader paging through a longer file was refused
for size and lost its place. Nothing is trimmed: the parts joined are the rendering
and the diff byte for byte, which :func:`check_parts` confirms against the seals and
the repository before the review starts. A single line too long for one read is
refused when the packet is built.

What a review must read in full before it may answer is listed in
:attr:`Packet.required_reading`, and the hook layer refuses the verdict until it
has: every part of the transcript and of the diff, the rubric, the issued
specification and the library files.

The packet's own record (``packet.json``) sits beside ``read/``, outside it: it
holds every digest above and the observable indicators the trajectory shows
(``scan.scan``), and the reviewer reads none of it but the indicators, which go
into its prompt.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import unicodedata
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.knowledge import loader
from physgate.knowledge.library import LibraryError, read_library
from physgate.orchestrator.exceptions import TrajectoryTamperedError
from physgate.orchestrator.protocols import Artefact, IssuedSpec
from physgate.orchestrator.trajectory import Seal, read_sealed
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import READ_DIRNAME
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.scan import ScanHit, ScanUnreadableError, scan
from physgate.reviewers.transcript import render

TRANSCRIPT_NAME = "transcript.md"
WORKTREE_NAME = "worktree"
DIFF_NAME = "diff.patch"
#: The names of the parts the transcript and the diff are issued in.
TRANSCRIPT_PART = "transcript-{n:02d}-of-{total:02d}.md"
DIFF_PART = "diff-{n:02d}-of-{total:02d}.patch"
#: The most one part holds. The Read tool shows a file whole only up to 256 KB and
#: 25,000 tokens, and at most 2,000 lines without an offset (measured on 2.1.283: a
#: 500-line page of a transcript was 33,022 tokens, about 0.82 per byte with its line
#: numbers). 20,000 bytes stays under the token limit even at one token per byte.
PART_MAX_BYTES = 20_000
PART_MAX_LINES = 2_000
SPEC_AS_ISSUED_NAME = "spec_as_issued.md"
RUBRIC_NAME = "rubric.md"
KNOWLEDGE_NAME = "knowledge"
RECORD_NAME = "packet.json"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class PacketError(ReviewError):
    """A review cannot be prepared as specified, so it does not run."""


_PART_NAME = r"^(transcript|diff)-[0-9]{2,}-of-[0-9]{2,}\.(md|patch)$"


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
    #: How many files the attempt's commit holds, as exported.
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

    def sha256(self) -> str:
        """The digest of this record: what a review line carries to name its packet."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: Git as the packet runs it: replacement objects ignored, no system or user
#: configuration, no attributes file. An attempt's session can add a replacement
#: object, which would change what a commit is shown to hold, or commit an
#: attribute file, which would hide or rewrite a file in an archive or a diff.
_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_ATTR_NOSYSTEM": "1",
}
_GIT_FLAGS = (
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.quotePath=false",
)


def _git_bytes(repo: Path, *args: str) -> bytes:
    done = subprocess.run(
        ["git", *_GIT_FLAGS, *args], cwd=repo, capture_output=True, check=False, env=_GIT_ENV
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
    return _digest(_git_bytes(Path(repo), "cat-file", "blob", f"{commit}:{path}"))


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


def _export(repo: Path, commit: str, into: Path) -> int:
    """Write ``commit``'s files under ``into``, from git's objects, no attribute applied.

    Not ``git archive``, which honours an attribute file committed in the tree: one
    can leave a file out of the archive or rewrite it on the way, so the reviewer
    would read something other than the commit. A symbolic link becomes a note naming
    its target, and a submodule a note naming its commit, so nothing exported reaches
    outside.

    Raises:
        PacketError: git cannot list or read the tree, or a path leaves the export.
    """
    listing = _git_bytes(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    entries = []
    for entry in listing.split(b"\0"):
        if entry:
            meta, _, raw_path = entry.partition(b"\t")
            mode, kind, oid = meta.decode().split()
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


def _diff(repo: Path, base: str, commit: str) -> bytes:
    """The change from ``base`` to ``commit``, every file as text, no driver or filter applied."""
    return _git_bytes(
        repo,
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--text",
        base,
        commit,
    )


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
    files = _export(Path(repo), artefact.attempt_commit, read / WORKTREE_NAME)
    diff = _diff(Path(repo), base_commit, artefact.attempt_commit)
    diff_parts = _write_parts(read, split_parts(diff, DIFF_PART))
    reading = [
        *(read / part.name for part in transcript_parts),
        *(read / part.name for part in diff_parts),
        read / RUBRIC_NAME,
    ]
    issued_digest = None
    if spec is not None:
        issued = _git_bytes(Path(repo), "cat-file", "blob", f"{spec.commit}:{spec.path}")
        if _digest(issued) != spec.sha256:
            msg = "the issued specification is not the one recorded before dispatch"
            raise PacketError(msg, path=spec.path, recorded=spec.sha256, found=_digest(issued))
        (read / SPEC_AS_ISSUED_NAME).write_bytes(issued)
        issued_digest = spec.sha256
        reading.append(read / SPEC_AS_ISSUED_NAME)
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
    )
    (Path(review) / RECORD_NAME).write_text(packet.model_dump_json(indent=1) + "\n")
    return packet


def joined_parts(read: Path, parts: tuple[Part, ...]) -> bytes:
    """The parts as written under ``read``, joined in their order."""
    return b"".join((Path(read) / part.name).read_bytes() for part in parts)


def check_parts(packet: Packet, *, repo: Path, base_commit: str) -> None:
    """Hold the issued parts to what they were cut from, before a review starts.

    Each part must be on disk as written; the transcript's parts joined must be the
    rendering of every sealed session again, with the nonces the packet recorded; the
    diff's parts joined must be the repository's diff of the attempt again. Nothing
    trimmed, nothing changed.

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
    for kind, parts in (("transcript", packet.transcript_parts), ("diff", packet.diff_parts)):
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
