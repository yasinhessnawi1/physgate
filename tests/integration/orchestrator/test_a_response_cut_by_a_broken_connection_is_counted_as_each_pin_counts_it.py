"""Against every pinned binary: a response cut off by a broken connection, and the totals after it.

A session's first response is cut off mid-body (:mod:`cut_endpoint`): its ``message_start``, its
first block's start and its first delta arrive, and the connection breaks. What the binary then
does, and what its result's totals count, is held to what was measured on each pin at the
scripted endpoint (Linux, 19.11.2026), with the binary's own retries at 0 (every run's setting)
and at 2, and with the network answering again (``answered``) or still down (``refused``):

- The stream marks the cut response as the binary's own closing of it: a ``message_stop`` whose
  stream event carries ``api_message_id`` and ``abandoned_blocks`` naming the response, from
  block 0, with no ``message_delta`` and no assistant message for it.
- With the network answering, the session completes: at 0 retries through one request without
  streaming, at 2 through a streaming retry the stream announces (``api_retry``). With it down,
  the session ends in an API error with the binary's own error message.
- In every case the result's per-model totals (``modelUsage``) count the cut response's starting
  usage, as its top-level ``usage`` does. So the account holds the totals to every line, the cut
  one counted and marked as such, and refuses none of these sessions.

A real run's review on 2.1.301 ended in an API error with totals that left the cut response
out, a shape not produced here; the unit rows hold the account to both.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from cut_endpoint import Served, serving_cut
from plain_session import Ended, run_session
from scripted_endpoint import FakeMessagesApi, Script, text, tool

from physgate.orchestrator.accounting import require_matching_totals
from physgate.orchestrator.decompose import read_stream
from physgate.orchestrator.protocols import Usage

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

READ = tool("Read", file_path="a.txt")
FIELDS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}


@dataclass(frozen=True)
class Cut:
    """One shape as measured: what the endpoint served, and how the session ended."""

    served: tuple[str, ...]
    terminal_reason: str
    is_error: bool
    #: Whether the result's per-model totals count the cut response's starting usage.
    totals_count_the_cut: bool


_MEASURED: dict[tuple[str, int], Cut] = {
    ("answered", 0): Cut(("cut", "answered_whole_json", "answered"), "completed", False, True),
    ("answered", 2): Cut(("cut", "answered", "answered"), "completed", False, True),
    ("refused", 0): Cut(("cut", "refused"), "api_error", True, True),
    ("refused", 2): Cut(("cut", "refused", "refused"), "api_error", True, True),
}
#: The two pins did the same in every shape.
CUTS: dict[str, dict[tuple[str, int], Cut]] = {"2.1.301": _MEASURED, "2.1.322": _MEASURED}


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _run(
    binary: str, work: Path, after: Literal["answered", "refused"], retries: int
) -> tuple[Ended, Served]:
    holder: dict[str, Served] = {}

    @contextmanager
    def serve(script: Script) -> Iterator[tuple[FakeMessagesApi, str]]:
        with serving_cut(script, after=after) as (api, served, url):
            holder["served"] = served
            yield api, url

    ended = run_session(
        binary,
        work,
        [READ, text("done")],
        env={"CLAUDE_CODE_MAX_RETRIES": str(retries)},
        serve=serve,
    )
    return ended, holder["served"]


def _sum(usages: list[Usage]) -> dict[str, int]:
    return {f: sum(int(getattr(u, f)) for u in usages) for f in FIELDS}


@pytest.mark.parametrize("retries", [0, 2])
@pytest.mark.parametrize("after", ["answered", "refused"])
def test_a_cut_response_is_counted_as_this_pin_s_totals_count_it(
    binary: str, tmp_path: Path, after: Literal["answered", "refused"], retries: int
) -> None:
    ended, served = _run(binary, tmp_path, after, retries)
    assert ended.version in CUTS, f"no cut response was measured on {ended.version}"
    expected = CUTS[ended.version][(after, retries)]
    assert tuple(served.kinds) == expected.served
    result, usages, _ = read_stream(ended.stdout)
    assert result is not None, ended.stderr
    assert (result.get("terminal_reason"), result.get("is_error")) == (
        expected.terminal_reason,
        expected.is_error,
    )
    # The binary's own mark, in the shape the stream reader takes.
    (closed,) = [
        e for e in ended.events if e.get("type") == "stream_event" and "abandoned_blocks" in e
    ]
    assert closed["event"]["type"] == "message_stop"
    cut_id = closed["api_message_id"]
    assert closed["abandoned_blocks"] == {"api_message_id": cut_id, "from_block_index": 0}
    assert [u.message_id for u in usages if u.abandoned] == [cut_id]
    # What the totals count, measured: every line, or every line but the cut one.
    per_model = result.get("modelUsage") or {}
    totals = {
        f: sum(int(m.get(k) or 0) for m in per_model.values() if isinstance(m, dict))
        for f, k in FIELDS.items()
    }
    every = _sum([u.usage for u in usages])
    but_the_cut = _sum([u.usage for u in usages if not u.abandoned])
    assert every != but_the_cut, "the cut response started with no usage; nothing is measured"
    assert totals == (every if expected.totals_count_the_cut else but_the_cut)
    # And the account holds them, the cut response counted as they count it.
    settled = require_matching_totals(result, usages)
    (cut,) = [u for u in settled if u.abandoned]
    assert cut.in_binary_totals is expected.totals_count_the_cut
