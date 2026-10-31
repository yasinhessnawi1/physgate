"""The one call's stream is sealed where the call writes it, as the bytes it wrote.

The plan's review reads the call's stream only once its bytes are held to a seal. The seal is
taken by the call itself, over exactly the bytes it put on disk (the credential already taken
out), so no later reader can choose what the stream was: a seal taken afterwards would seal
whatever the file held by then.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from orch_helpers import make_config

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.credentials import REDACTED_TEXT, Credential
from physgate.orchestrator.trajectory import seal

SECRET = "sk-ant-test-dummy-not-a-credential"


@pytest.mark.parametrize("ending", ["completed", "timed_out"])
def test_the_call_seals_the_bytes_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    message = {
        "id": "m1",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": SECRET}],
    }
    stream = json.dumps({"type": "assistant", "message": message}) + "\n"

    def ran(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if ending == "timed_out":
            raise subprocess.TimeoutExpired(argv, 1.0, output=stream.encode())
        return subprocess.CompletedProcess(argv, 1, stdout=stream, stderr="")

    monkeypatch.setattr(decompose, "claude_binary", lambda: "/nonexistent/claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.272")
    monkeypatch.setattr(subprocess, "run", ran)
    outcome = decompose.call(
        "Build a robot.\n",
        config=make_config(),
        workdir=tmp_path / "decomposition",
        base_url=None,
        credential=Credential(mode="api_key", secret=SECRET),
    )
    written = (tmp_path / "decomposition" / "stdout.jsonl").read_bytes()
    assert SECRET.encode() not in written and REDACTED_TEXT.encode() in written
    assert getattr(outcome, "stream_seal", None) == seal(written)
