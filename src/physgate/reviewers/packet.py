"""Everything a review is shown, written into the one directory the reviewer may read.

A review's directory (``places.review_dir``) gets a ``read/`` directory holding:

- ``transcript.md``: the implementing session's trajectory, read from the file the
  attempt names only after its bytes are held to the seal taken when the session
  ended, then rendered whole (``transcript.render``). An artefact no session
  produced carries a written account instead, which is copied as it is.
- ``worktree/``: the attempt's commit, exported. Not the implementing session's
  worktree: an export holds exactly what was committed, and no ``.git`` that points
  back into the target repository. A symbolic link in the commit is written as a
  note naming its target, never as a link, so nothing in the export reaches outside.
- ``diff.patch``: the attempt's change against where it left the run branch.
- ``spec_as_issued.md``: the module specification exactly as the decomposition
  issued it, read from the commit that issued it. The attempt can edit its own
  specification, and the worktree's copy then says what the attempt made it say;
  only the issued one counts, and the diff shows any edit.
- ``rubric.md``: the role's rubric, its digest checked again against the one it
  was loaded with.
- ``knowledge/``: the role's curated library files, copied from the harness.

What a review must read in full before it may answer is listed in
:attr:`Packet.required_reading`, and the hook layer refuses the verdict until it
has: the transcript, the rubric, the issued specification and the library files.

The packet's own record (``packet.json``) sits beside ``read/``, outside it: it
holds every digest above and the observable indicators the trajectory shows
(``scan.scan``), and the reviewer reads none of it but the indicators, which go
into its prompt.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.knowledge import loader
from physgate.knowledge.library import LibraryError, read_library
from physgate.orchestrator.exceptions import TrajectoryTamperedError
from physgate.orchestrator.git import diff_text
from physgate.orchestrator.protocols import Artefact
from physgate.orchestrator.trajectory import Seal, read_sealed
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import READ_DIRNAME
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.scan import ScanHit, scan
from physgate.reviewers.transcript import render

TRANSCRIPT_NAME = "transcript.md"
WORKTREE_NAME = "worktree"
DIFF_NAME = "diff.patch"
SPEC_AS_ISSUED_NAME = "spec_as_issued.md"
RUBRIC_NAME = "rubric.md"
KNOWLEDGE_NAME = "knowledge"
RECORD_NAME = "packet.json"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class PacketError(ReviewError):
    """A review cannot be prepared as specified, so it does not run."""


class Packet(BaseModel):
    """What one review was shown, by path and digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    read_root: Annotated[str, StringConstraints(min_length=1)]
    #: The trajectory as the packet read it: held to the session's seal first.
    trajectory_seal: Seal
    transcript_sha256: Sha256
    diff_sha256: Sha256
    #: ``None`` for an artefact no decomposition issued a specification for.
    spec_as_issued_sha256: Sha256 | None
    rubric_sha256: Sha256
    knowledge_sha256: dict[str, Sha256]
    #: How many files the attempt's commit holds, as exported.
    worktree_files: Annotated[int, Field(ge=0)]
    indicators: tuple[ScanHit, ...]
    required_reading: Annotated[tuple[str, ...], Field(min_length=2)]

    def sha256(self) -> str:
        """The digest of this record: what a review line carries to name its packet."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(cwd: Path, *args: str) -> bytes:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin"}
    )
    if done.returncode != 0:
        msg = "git could not produce what the review is shown"
        raise PacketError(msg, command=" ".join(args[:2]), stderr=done.stderr.decode()[-300:])
    return done.stdout


def _sealed(artefact: Artefact) -> tuple[bytes, Seal]:
    if artefact.trajectory_sha256 is None or artefact.trajectory_length is None:
        msg = "a review reads a trajectory held to its seal, and this attempt carries none"
        raise PacketError(msg, subtask=artefact.subtask_id, trajectory=artefact.trajectory)
    expected = Seal(sha256=artefact.trajectory_sha256, length=artefact.trajectory_length)
    try:
        data = read_sealed(Path(artefact.trajectory), expected)
    except TrajectoryTamperedError as exc:
        raise PacketError(str(exc), **exc.context) from None
    if not data.strip():
        msg = "a review reads the whole trajectory, and this one is empty"
        raise PacketError(msg, trajectory=artefact.trajectory)
    return data, expected


def _export(worktree: Path, commit: str, into: Path) -> int:
    """Write ``commit``'s files under ``into``; a link becomes a note naming its target."""
    archive = _git_bytes(worktree, "archive", "--format=tar", commit)
    into.mkdir()
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                kind = "symbolic" if member.issym() else "hard"
                note = f"[a {kind} link to: {member.linkname}]\n"
                target = (into / member.name).resolve()
                if not target.is_relative_to(into.resolve()):
                    msg = "a path in the commit leaves the export"
                    raise PacketError(msg, path=member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(note)
                count += 1
            elif member.isdir() or member.isfile():
                tar.extract(member, into, filter="data")
                count += member.isfile()
    return count


def build_packet(
    review: Path,
    artefact: Artefact,
    *,
    base_commit: str,
    rubric: Rubric,
    library: Path,
    spec: tuple[str, str] | None,
) -> Packet:
    """Write everything ``artefact``'s review is shown under ``review``/``read``.

    Args:
        review: the review's own directory, beneath a checked review root.
        artefact: the attempt; its trajectory must carry its session's seal.
        base_commit: where the attempt left the run branch; the diff starts here.
        rubric: the role's rubric, as loaded and checked.
        library: the harness checkout, whose ``knowledge/`` holds the role's curated files.
        spec: the issuing commit and the specification's path in it, or ``None``
            for an artefact no decomposition issued a specification for.

    Raises:
        PacketError: the attempt carries no seal, its trajectory is not the sealed
            one or is empty, ``read/`` exists already, or git cannot produce the
            export, the diff or the issued specification.
    """
    data, sealed = _sealed(artefact)
    read = Path(review) / READ_DIRNAME
    if read.exists():
        msg = "a review is prepared into a directory of its own, new"
        raise PacketError(msg, read=str(read))
    read.mkdir(parents=True)
    worktree = Path(artefact.worktree)
    stream = data.decode("utf-8", errors="replace")
    if artefact.trajectory_form == "session_stream":
        transcript = render(stream).encode("utf-8")
        indicators = scan(stream)
    else:
        transcript, indicators = data, ()
    (read / TRANSCRIPT_NAME).write_bytes(transcript)
    files = _export(worktree, artefact.attempt_commit, read / WORKTREE_NAME)
    diff = diff_text(worktree, base_commit, artefact.attempt_commit).encode("utf-8")
    (read / DIFF_NAME).write_bytes(diff)
    reading = [read / TRANSCRIPT_NAME, read / RUBRIC_NAME]
    issued_digest = None
    if spec is not None:
        spec_commit, spec_path = spec
        issued = _git_bytes(worktree, "show", f"{spec_commit}:{spec_path}")
        (read / SPEC_AS_ISSUED_NAME).write_bytes(issued)
        issued_digest = _digest(issued)
        reading.append(read / SPEC_AS_ISSUED_NAME)
    text = rubric.text.encode("utf-8")
    if _digest(text) != rubric.sha256:
        msg = "the rubric is not the one that was loaded"
        raise PacketError(msg, role=rubric.role)
    (read / RUBRIC_NAME).write_bytes(text)
    knowledge: dict[str, str] = {}
    try:
        curated = read_library(Path(library), [rubric.role])
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
        trajectory_seal=sealed,
        transcript_sha256=_digest(transcript),
        diff_sha256=_digest(diff),
        spec_as_issued_sha256=issued_digest,
        rubric_sha256=rubric.sha256,
        knowledge_sha256=knowledge,
        worktree_files=files,
        indicators=indicators,
        required_reading=tuple(str(p) for p in reading),
    )
    (Path(review) / RECORD_NAME).write_text(packet.model_dump_json(indent=1) + "\n")
    return packet
