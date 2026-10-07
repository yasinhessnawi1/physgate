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
import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.knowledge import loader
from physgate.knowledge.library import LibraryError, read_library
from physgate.orchestrator.exceptions import TrajectoryTamperedError
from physgate.orchestrator.protocols import Artefact
from physgate.orchestrator.trajectory import Seal, read_sealed
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import READ_DIRNAME
from physgate.reviewers.rubric import Rubric
from physgate.reviewers.scan import ScanHit, ScanUnreadableError, scan
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


class IssuedSpec(BaseModel):
    """The module specification as the decomposition issued it, and its digest then."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    commit: Commit
    path: Annotated[str, StringConstraints(min_length=1)]
    #: Recorded before the attempt was dispatched; the bytes read now must match it.
    sha256: Sha256


def _git_bytes(repo: Path, *args: str) -> bytes:
    done = subprocess.run(
        ["git", *_GIT_FLAGS, *args], cwd=repo, capture_output=True, check=False, env=_GIT_ENV
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
    data, sealed = _sealed(artefact)
    read = Path(review) / READ_DIRNAME
    if read.exists():
        msg = "a review is prepared into a directory of its own, new"
        raise PacketError(msg, read=str(read))
    read.mkdir(parents=True)
    try:
        # The bytes the seal covers, decoded once and strictly: a stream that is not
        # UTF-8 is not one the runtime wrote, and replacing what does not decode
        # would show the reviewer something the seal does not cover.
        stream = data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "the trajectory is not UTF-8, so it is not a stream the runtime wrote"
        raise PacketError(msg, trajectory=artefact.trajectory) from None
    nonce = None
    if artefact.trajectory_form == "session_stream":
        try:
            indicators = scan(stream)
        except ScanUnreadableError as exc:
            raise PacketError(str(exc), trajectory=artefact.trajectory) from None
        rendered, nonce = render(stream)
        transcript = rendered.encode("utf-8")
    else:
        transcript, indicators = data, ()
    (read / TRANSCRIPT_NAME).write_bytes(transcript)
    files = _export(Path(repo), artefact.attempt_commit, read / WORKTREE_NAME)
    diff = _diff(Path(repo), base_commit, artefact.attempt_commit)
    (read / DIFF_NAME).write_bytes(diff)
    reading = [read / TRANSCRIPT_NAME, read / RUBRIC_NAME]
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
        transcript_nonce=nonce,
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
