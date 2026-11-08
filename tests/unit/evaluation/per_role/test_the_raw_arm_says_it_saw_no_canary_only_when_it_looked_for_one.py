"""The raw session's record says it saw no held-out canary only when it had one to look for.

With no canary to look for, nothing in the stream can show one, and "not seen" would be a
claim the record cannot make: it records ``None``, unknown, and whatever reads the record
treats unknown as it must (the task author's runner refuses it where canaries exist).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from task_fixtures import own_task
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _script, _setup

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task

CANARY = "5f0c3a9e1b7d4c2a8e6f0b1d3c5a7e9f"


@pytest.mark.parametrize(
    ("canaries", "shown", "seen"),
    [((), CANARY, None), ((CANARY,), "nothing held out", False), ((CANARY,), CANARY, True)],
)
def test_the_record_says_whether_a_canary_showed_only_when_it_looked_for_one(
    tmp_path: Path, canaries: tuple[str, ...], shown: str, seen: bool | None
) -> None:
    message = {"id": "msg_1", "model": "m", "usage": {"input_tokens": 1, "output_tokens": 0}}
    lines = [
        json.dumps({"type": "assistant", "message": message}),
        json.dumps({"type": "user", "message": {"content": shown}}),
    ]
    binary = _script(tmp_path / "claude", "".join(f"echo '{line}'\n" for line in lines))
    setup = dataclasses.replace(_setup(tmp_path, binary), held_out_canaries=canaries)
    task = parse_task(json.dumps(own_task()).encode())
    record = raw.run_raw(task, setup, tmp_path / "work", cap=10**6)
    assert record["held_out_seen"] is seen
