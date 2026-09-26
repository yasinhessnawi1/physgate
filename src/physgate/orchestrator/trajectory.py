"""A session's captured stream: sealed when the session ends, and held to the seal after.

The stream is the trajectory the reviewer reads and the record the token account
and the model check are read from. It lives in the sessions directory, which no
session tool may write and the hook layer refuses writes to before they happen;
but it cannot be put back, because the runtime writes it while the session
runs, and a write the hook layer cannot see coming is not refused.

Two checks close what can be closed without changing how the stream is captured:

- **The tail.** The runtime writes the stream through a handle that does not
  append, at its own offset, so a longer foreign write survives past the
  runtime's last byte. A completed session's stream therefore must hold exactly
  one ``result`` event and nothing after it; a second result, or anything after
  the one, is a forgery left behind by the session.
- **The seal.** When the session ends, before anything reads the stream, its
  sha256 and length are recorded in the event log. Every later reader checks the
  file against the seal, so a change after the session is refused.

What neither can see: the same user overwriting earlier lines during the session
through a write the hook layer cannot see. The account is still held against the
runtime's own ``result`` totals, and a tail is caught; the text of earlier lines
is not protected.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.exceptions import TrajectoryTamperedError


class Seal(BaseModel):
    """A stream's digest and length, taken when its session ended."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    length: int = Field(ge=0)


def seal(data: bytes) -> Seal:
    """The seal of a stream's bytes."""
    return Seal(sha256=hashlib.sha256(data).hexdigest(), length=len(data))


def read_sealed(path: Path, expected: Seal) -> bytes:
    """A stream's bytes, if they are still the ones sealed when its session ended.

    Raises:
        TrajectoryTamperedError: the file is missing, or not the sealed bytes.
    """
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        msg = "a sealed trajectory is gone"
        raise TrajectoryTamperedError(msg, trajectory=str(path)) from None
    found = seal(data)
    if found != expected:
        msg = "a trajectory is not what it was when its session ended"
        raise TrajectoryTamperedError(
            msg,
            trajectory=str(path),
            sealed=f"{expected.sha256}:{expected.length}",
            found=f"{found.sha256}:{found.length}",
        )
    return data


def result_lines(text: str) -> list[int]:
    """The indices of the lines that are ``result`` events."""
    found = []
    for index, line in enumerate(text.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            found.append(index)
    return found


def forged_tail(text: str) -> str | None:
    """Why a stream with a result is not one the runtime alone wrote, or ``None``.

    A stream with no result (a session stopped or killed) is not judged here.
    """
    results = result_lines(text)
    if not results:
        return None
    if len(results) > 1:
        return f"the stream holds {len(results)} result events; the runtime writes one"
    after = text.splitlines()[results[0] + 1 :]
    if any(line.strip() for line in after):
        return "the stream goes on after its result event; the runtime writes nothing after it"
    return None


def through_first_result(text: str) -> str:
    """The stream up to and including its first result: what the runtime wrote, if forged after."""
    results = result_lines(text)
    if not results:
        return text
    return "\n".join(text.splitlines()[: results[0] + 1]) + "\n"
