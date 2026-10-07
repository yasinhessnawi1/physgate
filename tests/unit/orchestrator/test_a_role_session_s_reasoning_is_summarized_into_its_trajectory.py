"""Whether a role session's reasoning is summarized into its trajectory is a recorded run input.

Left to the binary, a session's reasoning is omitted from its stream, and the
reviewer that reads the trajectory reads tool calls and observations only. The
run therefore names the display it wants, records it, and passes it to every
role session. A run recorded before the field existed ran with the binary's
default and reads as ``omitted``, with its recorded digest unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from orch_helpers import make_config

from physgate.orchestrator.run_config import load_run_config, write_run_config


def test_a_run_records_the_display_it_ran_with(tmp_path: Path) -> None:
    config = make_config(thinking_display="summarized")
    write_run_config(tmp_path / "run.json", config)
    recorded = json.loads((tmp_path / "run.json").read_text())
    assert recorded["thinking_display"] == "summarized"
    assert load_run_config(tmp_path / "run.json") == config


def test_a_run_recorded_before_the_field_reads_as_omitted_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    older = make_config(thinking_display="omitted")
    legacy = json.loads(older.model_dump_json())
    del legacy["thinking_display"]
    legacy_bytes = json.dumps(legacy, separators=(",", ":")).encode() + b"\n"
    assert older.canonical_bytes() == legacy_bytes
    (tmp_path / "run.json").write_bytes(legacy_bytes)
    loaded = load_run_config(tmp_path / "run.json")
    assert loaded.thinking_display == "omitted"
    assert loaded.sha256() == older.sha256()


def test_the_two_displays_are_two_runs() -> None:
    summarized = make_config(thinking_display="summarized")
    omitted = make_config(thinking_display="omitted")
    assert summarized.sha256() != omitted.sha256()
