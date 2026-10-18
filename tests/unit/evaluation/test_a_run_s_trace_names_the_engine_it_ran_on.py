"""``physgate trace`` names the engine each process ran the run's sessions on.

Read from the run's own log, in its order: one line per run and resume, with the harness and
its version, the provider, each model string with the model it is, and the layers held
around each profile's sessions. A run recorded before engines were names none.
"""

from __future__ import annotations

from pathlib import Path

from observe_rig import fake_run, target_repo

from physgate.engines.claude_code import ClaudeCodeEngine
from physgate.evaluation.observe.trace import read_traces
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import EngineChecked, EventLog
from physgate.orchestrator.run_config import load_run_config
from physgate.oslayer.probe import Absent


def test_the_trace_names_each_engine_line_and_a_run_before_them_names_none(
    tmp_path: Path,
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    assert read_traces(run).engines == ()
    config = load_run_config(run / "run.json")
    engine = ClaudeCodeEngine(base_url=None, credential=Credential("api_key", "not-a-key"))
    record = engine.record(
        version=config.claude_version,
        models=(config.models.decomposition, *config.models.roles.values()),
        os_layer=Absent(reason="stand-in: no sandbox here"),
    )
    log = EventLog(run / "events.jsonl", run_id=config.run_id, gate_mode=config.gate_mode)
    try:
        for _ in range(2):  # a run, then its resume
            log.append(EngineChecked(**log.envelope(), engine=record))
    finally:
        log.close()
    assert read_traces(run).engines == (record, record)
