"""The exports the commit-time rule admits are read as bytes, and carried to the attempt's review.

The review packet shows an export as one line with its size, sha256 and summary only for a path
the commit-time rule admitted with exactly those bytes (``reviewers.packet``). This holds the
producer of that admission and the way to the packet:

- the rule reads each export as git holds it, byte for byte: a carriage return before a line
  feed is two bytes of a binary STL, never one line ending, so a valid file is not refused and a
  file one byte too long is not admitted;
- a submodule entry in the exports folder is named as no regular file, and the count of the
  module's bytes is not broken by it;
- ``admitted_exports`` names each side of each export change the rule admits, as its path and
  the sha256 of its bytes: an export added or changed, and what a changed or removed one was;
  nothing that is no export of this module's folder, too big, malformed, a link, or in a module
  whose exports pass the cap together;
- the change check hands that admission to its own long-line check and to the attempt, and the
  loop hands it to the reviewer, so an admitted binary export no longer stops an attempt.
"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
from observe_rig import Reviewer, fake_run, target_repo  # noqa: E402

from physgate.orchestrator import merge  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.events import AttemptRejected, Merged, read_events  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt, write_scope_violations  # noqa: E402
from physgate.reviewers.packet import PART_MAX_BYTES  # noqa: E402

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
MODULE = "modules/chassis"
EXPORTS = f"{MODULE}/exports"
INVALID = getattr(merge, "EXPORT_INVALID", "(the reason for an invalid export is not written)")
#: A triangle's two attribute bytes, little-endian: a carriage return, then a line feed.
CR_LF = 0x0A0D
#: One attribute holding a lone line feed.
LF = 0x000A


def _stl(triangles: int = 2, attributes: Mapping[int, int] | None = None) -> bytes:
    body = b"part".ljust(80, b" ") + struct.pack("<I", triangles)
    for n in range(triangles):
        corner = float(n % 3)
        attribute = (attributes or {}).get(n, 0)
        body += struct.pack("<12fH", 0, 0, 1, 0, 0, corner, 1, 0, corner, 0, 1, corner, attribute)
    return body


def _step(newline: bytes = b"\n") -> bytes:
    lines = [
        b"ISO-10303-21;",
        b"HEADER;",
        b"FILE_DESCRIPTION((''),'2;1');",
        b"FILE_NAME('plate','',(''),(''),'','','');",
        b"FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));",
        b"ENDSEC;",
        b"DATA;",
        b"#1=CARTESIAN_POINT('',(0.,0.,1.));",
        b"ENDSEC;",
        b"END-ISO-10303-21;",
    ]
    return newline.join(lines) + newline


def _padded_step(size: int) -> bytes:
    body = _step()
    return body + b"/*" + b"x" * (size - len(body) - 5) + b"*/\n"


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write(repo: Path, files: Mapping[str, bytes | None]) -> None:
    for name, body in files.items():
        path = repo / name
        if body is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def _commits(
    tmp_path: Path,
    after: Mapping[str, bytes | None],
    before: Mapping[str, bytes | None] | None = None,
    links: Mapping[str, str] | None = None,
    gitlinks: tuple[str, ...] = (),
) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "run")
    _write(repo, {f"{MODULE}/chassis.py": b"length = 110\n", **(before or {})})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, after)
    for name, target in (links or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).symlink_to(target)
    _git(repo, "add", "-A")
    for name in gitlinks:
        _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{base},{name}")
    _git(repo, "commit", "-q", "-m", "attempt")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _found(tmp_path: Path, after: Mapping[str, bytes | None], **kwargs: Any) -> object:  # noqa: ANN401
    """What the rule says, or whatever it raised: a crash is a wrong answer, not a pass."""
    repo, base, commit = _commits(tmp_path, after, **kwargs)
    try:
        return write_scope_violations(repo, base, commit, MODULE)
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}: {exc}"


def _admitted(
    tmp_path: Path,
    after: Mapping[str, bytes | None],
    before: Mapping[str, bytes | None] | None = None,
    **kwargs: Any,  # noqa: ANN401
) -> object:
    """The pairs the rule admits, as (path, sha256), or why there are none to read."""
    produce = getattr(merge, "admitted_exports", None)
    if produce is None:
        return "merge.admitted_exports does not exist"
    repo, base, commit = _commits(tmp_path, after, before, **kwargs)
    try:
        return sorted((entry.path, entry.sha256) for entry in produce(repo, base, commit, MODULE))
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}: {exc}"


# ---- the bytes as git holds them --------------------------------------------------------------


def test_a_binary_stl_whose_bytes_hold_a_carriage_return_and_line_feed_is_in_scope(
    tmp_path: Path,
) -> None:
    body = _stl(4, {1: CR_LF, 3: CR_LF})
    assert b"\r\n" in body
    assert _found(tmp_path, {f"{EXPORTS}/plate.stl": body}) == []


def test_a_binary_stl_one_byte_too_long_is_refused_even_where_the_extra_byte_is_a_return(
    tmp_path: Path,
) -> None:
    valid = _stl(3, {1: LF})
    at = valid.index(struct.pack("<H", LF))
    # A carriage return before that line feed: one byte more than the count says.
    body = valid[:at] + b"\r" + valid[at:]
    assert len(body) == len(valid) + 1
    assert _found(tmp_path, {f"{EXPORTS}/plate.stl": body}) == [f"{EXPORTS}/plate.stl ({INVALID})"]


def test_a_submodule_entry_in_the_exports_folder_is_named_and_the_count_still_holds(
    tmp_path: Path,
) -> None:
    found = _found(tmp_path, {f"{EXPORTS}/plate.step": _step()}, gitlinks=(f"{EXPORTS}/sub",))
    assert found == [f"{EXPORTS}/sub (not a regular file)"]


# ---- what the rule admits ---------------------------------------------------------------------


def test_each_added_export_is_admitted_by_its_path_and_the_sha256_of_its_bytes(
    tmp_path: Path,
) -> None:
    step, stl = _step(b"\r\n"), _stl(4, {2: CR_LF})
    after = {f"{EXPORTS}/plate.step": step, f"{EXPORTS}/plate.stl": stl}
    assert _admitted(tmp_path, after) == sorted(
        [(f"{EXPORTS}/plate.step", _sha(step)), (f"{EXPORTS}/plate.stl", _sha(stl))]
    )


def test_a_changed_export_is_admitted_on_both_sides_and_a_removed_one_as_it_was(
    tmp_path: Path,
) -> None:
    old, new, gone = _stl(2), _stl(3), _step()
    before = {f"{EXPORTS}/plate.stl": old, f"{EXPORTS}/deck.step": gone}
    after: dict[str, bytes | None] = {f"{EXPORTS}/plate.stl": new, f"{EXPORTS}/deck.step": None}
    assert _admitted(tmp_path, after, before) == sorted(
        [
            (f"{EXPORTS}/deck.step", _sha(gone)),
            (f"{EXPORTS}/plate.stl", _sha(old)),
            (f"{EXPORTS}/plate.stl", _sha(new)),
        ]
    )


def test_an_export_the_attempt_did_not_touch_is_not_named(tmp_path: Path) -> None:
    before = {f"{EXPORTS}/deck.step": _step()}
    after = {f"{EXPORTS}/plate.stl": _stl()}
    assert _admitted(tmp_path, after, before) == [(f"{EXPORTS}/plate.stl", _sha(_stl()))]


def test_nothing_is_admitted_that_is_no_valid_export_of_this_module_s_folder(
    tmp_path: Path,
) -> None:
    after = {
        f"{MODULE}/plate.step": _step(),
        f"{EXPORTS}/sub/plate.step": _step(),
        f"{EXPORTS}/notes.txt": _step(),
        "modules/other/exports/plate.step": _step(),
        "exports/plate.step": _step(),
        f"{EXPORTS}/bad.stl": _stl()[:-1],
        f"{EXPORTS}/bad.step": _step()[:-4],
        f"{EXPORTS}/big.step": _padded_step(2_000_001),
    }
    links = {f"{EXPORTS}/link.stl": "../chassis.py"}
    assert _admitted(tmp_path, after, links=links) == []


def test_an_export_at_the_cap_is_admitted(tmp_path: Path) -> None:
    body = _padded_step(2_000_000)
    assert len(body) == 2_000_000
    assert _admitted(tmp_path, {f"{EXPORTS}/plate.step": body}) == [
        (f"{EXPORTS}/plate.step", _sha(body))
    ]


def test_nothing_is_admitted_in_a_module_whose_exports_pass_the_cap_together(
    tmp_path: Path,
) -> None:
    before = {f"{EXPORTS}/part{n}.step": _padded_step(1_900_000) for n in range(8)}
    after = {f"{EXPORTS}/part8.step": _padded_step(1_900_000)}
    assert _admitted(tmp_path, after, before) == []


# ---- the way to the review --------------------------------------------------------------------


def _long_stl() -> bytes:
    """A binary STL no part of a review can hold as a line: no line feed in 25 kB."""
    body = _stl(500)
    assert b"\n" not in body and len(body) > PART_MAX_BYTES
    return body


def test_the_change_check_admits_a_binary_export_and_says_so_on_its_verdict(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "target"
    (repo / MODULE).mkdir(parents=True)
    (repo / MODULE / "keep.txt").write_text("0\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("chassis-1")
    body = _long_stl()
    _write(worktree, {f"{EXPORTS}/plate.stl": body})
    commit = commit_attempt(worktree, "chassis-1", 1, "sess-1", repo=run.repo)
    store = tmp_path / "store"
    store.mkdir()
    checker = GitChangeChecker(run, store, {"chassis-1": MODULE})
    check = checker.check("chassis-1", commit, "control")
    assert (check.refused_by, check.reason) == (None, None)
    told = getattr(check, "exports", None)
    assert told is not None, "the change check's verdict carries no exports"
    assert [(e.path, e.sha256) for e in told] == [(f"{EXPORTS}/plate.stl", _sha(body))]


def test_the_loop_hands_the_admitted_export_to_the_reviewer_and_the_attempt_merges(
    tmp_path: Path,
) -> None:
    repo = target_repo(tmp_path)
    reviewer = Reviewer()
    body = _long_stl()
    run_dir = fake_run(
        tmp_path,
        "r-exports",
        repo,
        reviewers={"electrical": reviewer},
        session={"files": {"exports/plate.stl": body}},
    )
    events = read_events(run_dir / "events.jsonl")
    rejected = [(e.attempt, e.finding.source) for e in events if isinstance(e, AttemptRejected)]
    assert rejected == []
    assert reviewer.seen, "no attempt reached its review"
    for artefact in reviewer.seen:
        told = getattr(artefact, "exports", None)
        assert told is not None, "the attempt the reviewer is handed carries no exports"
        assert [(e.path.rsplit("/", 1)[-1], e.sha256) for e in told] == [("plate.stl", _sha(body))]
        assert all(e.path.endswith("/exports/plate.stl") for e in told)
    assert len([e for e in events if isinstance(e, Merged)]) == len(reviewer.seen)
