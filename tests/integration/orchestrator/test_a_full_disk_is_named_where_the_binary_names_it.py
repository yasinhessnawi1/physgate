"""Against every pinned binary: a session whose transcript directory sits on a full volume.

The binary keeps a transcript of each session in its configuration directory. Here that
directory's transcripts are put on a small volume with no space left, and one session is
run on the scripted endpoint in the stream format every harness session uses.

Measured (macOS, 12.11.2026):

- 2.1.301 ends as a finished session, exit status 0, and says nothing anywhere: not in
  the stream, not on stderr. There is nothing a reader could go by.
- 2.1.322 ends the same way, exit status 0, and then writes one more event after its
  result, naming what it could not save and why, and a line on stderr. (Only with plain
  or single-object output does it exit 1; no harness session uses either.)

Where the binary says it, no reader takes the session for a completed one: a review is
infrastructure, the decomposition call gives no plan under a cause of its own, and a role
session is infrastructure under a cause of its own. A role session's stream is held to
ending at its result; the one event this pin writes after it is the binary's own word and
is read as that, and nothing else after a result is.

The full volume is one this test is given (``PHYSGATE_FULL_VOLUME``: a directory on a
volume of at most 16 MiB, which the test fills and empties again) or, on macOS, a 4 MiB
disk image it makes, mounts under its own directory and removes. Elsewhere there is no
way to make one without privileges, and the row says so instead of running.
"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from plain_session import run_session
from scripted_endpoint import text, tool

from physgate.orchestrator.budget import DISK_FULL_BELOW_BYTES, writes_lost
from physgate.orchestrator.dispatch import captured_from, free_bytes
from physgate.orchestrator.trajectory import forged_tail

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

FULL_VOLUME_VARIABLE = "PHYSGATE_FULL_VOLUME"
#: The largest volume this test will fill: a named directory on anything larger is refused.
LARGEST_VOLUME_BYTES = 16 * 1024 * 1024

#: What each pin says it could not save when its transcripts' volume is full.
SAYS: dict[str, str | None] = {"2.1.301": None, "2.1.322": "transcript (ENOSPC)"}


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _fill(path: Path) -> None:
    """Write zeros to ``path`` until its volume takes no more."""
    with path.open("wb", buffering=0) as out:
        for size in (4096, 512, 1):
            while True:
                try:
                    out.write(bytes(size))
                except OSError as exc:
                    if exc.errno not in (errno.ENOSPC, errno.EDQUOT):
                        raise
                    break


@pytest.fixture
def full_directory(tmp_path: Path) -> Iterator[Path]:
    """An empty directory on a volume with no space left; the volume is left as it was found."""
    named = os.environ.get(FULL_VOLUME_VARIABLE)
    image = tmp_path / "small.dmg"
    mounted = False
    if named:
        volume = Path(named)
    elif sys.platform == "darwin":
        volume = tmp_path / "volume"
        volume.mkdir()
        made = ["hdiutil", "create", "-size", "4m", "-fs", "HFS+", "-volname", "pgsmall", "-quiet"]
        subprocess.run([*made, str(image)], check=True, capture_output=True)
        attach = ["hdiutil", "attach", str(image), "-mountpoint", str(volume), "-nobrowse"]
        subprocess.run([*attach, "-quiet"], check=True, capture_output=True)
        mounted = True
    else:
        pytest.skip(
            f"no small volume is named in {FULL_VOLUME_VARIABLE}, and this platform has no "
            "way to make one without privileges"
        )
    tag = uuid.uuid4().hex
    records, filler = volume / f"records-{tag}", volume / f"filler-{tag}"
    try:
        size = os.statvfs(volume)
        assert size.f_blocks * size.f_frsize <= LARGEST_VOLUME_BYTES, "not a small volume"
        records.mkdir()
        _fill(filler)
        yield records
    finally:
        filler.unlink(missing_ok=True)
        shutil.rmtree(records, ignore_errors=True)
        if mounted:
            detach = ["hdiutil", "detach", str(volume), "-quiet"]
            if subprocess.run(detach, check=False, capture_output=True).returncode != 0:
                subprocess.run([*detach, "-force"], check=False, capture_output=True)
            image.unlink(missing_ok=True)


def test_a_full_volume_under_the_transcript_is_read_as_each_pin_says_it(
    binary: str, tmp_path: Path, full_directory: Path
) -> None:
    def on_the_full_volume(work: Path) -> None:
        (work / "config" / "projects").symlink_to(full_directory)

    ended = run_session(
        binary,
        tmp_path / "session",
        [tool("Read", file_path="a.txt"), text("done")],
        prepare=on_the_full_volume,
    )
    # No line of the transcript was saved, and the session ended as a finished one.
    assert not any(p.is_file() for p in full_directory.rglob("*"))
    result = ended.result
    assert result is not None, ended.stderr
    assert (result.get("terminal_reason"), result.get("is_error")) == ("completed", False)
    assert ended.exit_code == 0 and len(ended.requests) == 2
    assert ended.version in SAYS, f"nothing was measured on {ended.version}"
    said = SAYS[ended.version]
    assert writes_lost(ended.stdout) == said
    if said is None:
        # This pin says nothing: the loss cannot be seen, and each reader takes the end.
        assert ended.after_result == [] and ended.stderr == ""
        assert ended.as_a_role_session().outcome == "completed"
        assert ended.forged is None
        assert ended.as_a_review() is None
        assert ended.as_the_decomposition() == "no_structured_output"
        assert forged_tail(ended.stdout) is None
        return
    (event,) = ended.after_result
    assert event == {
        "type": "system",
        "subtype": "session_writes_lost",
        "error_code": "ENOSPC",
        "lost": ["transcript"],
        "transcript_session_ids": [ended.session_id],
        "session_id": ended.session_id,
        "uuid": event.get("uuid"),
    }
    assert "could not save" in ended.stderr and "(ENOSPC)" in ended.stderr
    assert ended.as_a_review() == "infrastructure"
    assert ended.as_the_decomposition() == "writes_lost"
    # A role session's stream may hold nothing after its result but this, the binary's own
    # word of this session: the session is infrastructure for a full disk, and no forgery.
    assert forged_tail(ended.stdout) is not None
    role = ended.as_a_role_session()
    assert (role.outcome, role.cause) == ("infrastructure", "disk_full")
    assert ended.forged is None
    # It is taken because the harness itself measured the records' volume as full, not on
    # the stream's word: the same stream with space to spare there is a forged tail.
    assert ended.free is not None and ended.free < DISK_FULL_BELOW_BYTES
    spare = replace(ended, free=free_bytes(tmp_path))
    assert spare.free is not None and spare.free > DISK_FULL_BELOW_BYTES
    assert spare.forged is not None
    assert spare.as_a_role_session().outcome == "completed"  # and never taken: it is forged
    unmeasured = replace(ended, free=None)
    assert unmeasured.forged is not None
    # The same stream with one more line after the binary's word is a forged tail still.
    longer = captured_from((ended.stdout + ended.stdout).encode(), own_tail_of=ended.session_id)
    assert longer.tampered is not None and longer.lost is None
