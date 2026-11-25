"""``physgate tiers practice`` refuses in words outside the evaluation environment.

Each practice task is held to its scorer before the split, and the scorer's libraries live only
in the evaluation environment. In the harness's own environment the command says so on one line
and leaves no directory behind.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from physgate.cli import main


@pytest.mark.skipif(
    importlib.util.find_spec("numpy") is not None, reason="the evaluation environment is here"
)
def test_the_command_refuses_in_words_and_makes_no_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    argv = ["tiers", "practice", "--store", str(store), "--implementer-model", "m"]
    assert main(argv) == 1
    line = json.loads(capsys.readouterr().out)
    assert line["refused_because"] == "evaluation_environment_missing"
    assert not store.exists()
