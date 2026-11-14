"""What a pin sends depends on whether the sessions' settings deny the binary's search tool.

On 2.1.322 a role session whose search tool is offered carries the tool-search beta flag
(``advanced-tool-use-2025-11-20``); one whose settings deny it does not (measured on CI, linux-x64,
14.11.2026: nothing else in the request moved). So a run records which it was, and its manifest
carries the defaults measured for that setting. A run recorded before the setting existed had the
search tool offered: it reads so, its recorded bytes are unchanged, and its manifest carries the
list it was measured with, never relabelled.
"""

from __future__ import annotations

import json
from pathlib import Path

from observe_rig import config, fake_run, target_repo

from physgate.evaluation.observe.manifest import BINARY_DEFAULTS, read_manifest
from physgate.orchestrator.run_config import ModelStrings, load_run_config, write_run_config

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5"
SEARCH_BETA = "advanced-tool-use-2025-11-20"


def _models() -> ModelStrings:
    return ModelStrings(
        decomposition=OPUS, roles={"electrical": OPUS}, reviewers={"electrical": SONNET}
    )


def test_a_new_run_records_that_its_sessions_were_denied_the_search_tool(tmp_path: Path) -> None:
    made = config("run-a", target_repo(tmp_path), "electrical", claude_version="2.1.322")
    assert getattr(made, "tool_search", None) == "denied"
    path = tmp_path / "run.json"
    write_run_config(path, made)
    assert json.loads(path.read_text()).get("tool_search") == "denied"


def test_a_2_1_322_run_whose_sessions_were_denied_it_carries_no_search_beta(tmp_path: Path) -> None:
    overrides = {"claude_version": "2.1.322", "models": _models()}
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides=overrides)
    manifest = read_manifest(run)
    assert getattr(manifest.config, "tool_search", None) == "denied"
    (entry,) = manifest.binary_defaults
    offered = BINARY_DEFAULTS[("2.1.322", OPUS)]
    assert SEARCH_BETA not in entry.anthropic_beta, entry.anthropic_beta
    assert set(entry.anthropic_beta) == set(offered.anthropic_beta) - {SEARCH_BETA}
    assert (entry.thinking, entry.context_management) == (
        offered.thinking,
        offered.context_management,
    )
    assert entry.decomposition == offered.decomposition


def test_a_run_recorded_before_the_setting_reads_as_it_was_written(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    write_run_config(path, config("run-a", target_repo(tmp_path), "electrical"))
    older = json.loads(path.read_text())
    older.pop("tool_search", None)
    path.write_text(json.dumps(older, separators=(",", ":")) + "\n")
    written = path.read_bytes()
    loaded = load_run_config(path)
    assert getattr(loaded, "tool_search", None) == "offered"
    # Recorded again, it is the same bytes, so its digest still names it.
    assert loaded.canonical_bytes() == written


def test_an_older_2_1_322_run_keeps_the_search_beta_it_was_measured_with(tmp_path: Path) -> None:
    overrides = {"claude_version": "2.1.322", "models": _models(), "tool_search": "offered"}
    try:
        run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides=overrides)
    except Exception as exc:  # noqa: BLE001 - before the setting exists the field is refused
        raise AssertionError(f"a run with the search tool offered is not recorded: {exc}") from None
    manifest = read_manifest(run)
    assert "tool_search" not in json.loads((run / "run.json").read_text())
    assert manifest.binary_defaults == (BINARY_DEFAULTS[("2.1.322", OPUS)],)
