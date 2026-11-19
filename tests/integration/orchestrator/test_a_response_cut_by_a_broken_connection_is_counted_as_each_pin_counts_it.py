"""Against every pinned binary: a response cut off by a broken connection, and the totals after it.

Diagnostic round: what each pin does, recorded, before any row is held to it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import pytest
from cut_endpoint import Served, serving_cut
from plain_session import run_session
from scripted_endpoint import FakeMessagesApi, Script, text, tool

from physgate.orchestrator.decompose import read_stream

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


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _compact(event: dict[str, Any]) -> list[Any]:
    kind = event.get("type")
    if kind == "stream_event":
        inner = event.get("event") or {}
        mid = (inner.get("message") or {}).get("id") or event.get("api_message_id")
        return [kind, inner.get("type"), mid, event.get("abandoned_blocks")]
    if kind == "assistant":
        message = event.get("message") or {}
        return [kind, message.get("id"), message.get("model"), message.get("usage")]
    if kind == "system":
        return [kind, event.get("subtype"), {k: event.get(k) for k in ("error", "attempt")}]
    if kind == "result":
        return [kind, event.get("subtype"), event.get("terminal_reason"), event.get("is_error")]
    return [kind]


@pytest.mark.parametrize("retries", [0, 2])
@pytest.mark.parametrize("after", ["answered", "refused"])
def test_record_what_the_pin_does(
    binary: str, tmp_path: Path, after: Literal["answered", "refused"], retries: int
) -> None:
    holder: dict[str, Served] = {}

    @contextmanager
    def serve(script: Script) -> Iterator[tuple[FakeMessagesApi, str]]:
        with serving_cut(script, after=after) as (api, served, url):
            holder["served"] = served
            yield api, url

    ended = run_session(
        binary,
        tmp_path,
        [READ, text("done")],
        env={"CLAUDE_CODE_MAX_RETRIES": str(retries)},
        serve=serve,
    )
    result, usages, _ = read_stream(ended.stdout)
    per_model = (result or {}).get("modelUsage") or {}
    totals = {
        f: sum(int(m.get(k) or 0) for m in per_model.values() if isinstance(m, dict))
        for f, k in FIELDS.items()
    }
    counted = {f: sum(int(getattr(u.usage, f)) for u in usages if not u.abandoned) for f in FIELDS}
    cut = {f: sum(int(getattr(u.usage, f)) for u in usages if u.abandoned) for f in FIELDS}
    facts = {
        "version": ended.version,
        "after": after,
        "retries": retries,
        "exit": ended.exit_code,
        "served": holder["served"].kinds,
        "streamed": holder["served"].streamed,
        "result": None
        if result is None
        else {k: result.get(k) for k in ("subtype", "terminal_reason", "is_error", "num_turns")},
        "result_usage": None if result is None else result.get("usage"),
        "lines": [[u.message_id, u.abandoned, u.usage.model_dump()] for u in usages],
        "totals": totals,
        "counted": counted,
        "cut": cut,
        "events": [_compact(e) for e in ended.events],
        "stderr_tail": ended.stderr[-1500:],
    }
    report = os.environ.get("PHYSGATE_OSLAYER_REPORT")
    if report:
        Path(report).mkdir(parents=True, exist_ok=True)
        name = f"cut-response-{ended.version}-{after}-{retries}.json"
        (Path(report) / name).write_text(json.dumps(facts, indent=1, default=str))
    print(json.dumps(facts, default=str))  # noqa: T201 - a diagnostic round
    assert result is not None, json.dumps(facts, default=str)
