"""A run's manifest is assembled from its own records and refuses one that is incomplete.

ARCH-145 asks that per-step traces, per-check results, tokens and wall clock per
session, pinned model strings, seeds, resolved configurations and artefact
hashes be recorded. The manifest is where the configuration and the artefacts
come together, and it is read, never written: a missing field fails its schema,
a configuration that is not the one the run started under is refused, and a
commit the record names that git cannot find is an error rather than a blank.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from observe_rig import fake_run, git, target_repo

from physgate.evaluation.observe.exceptions import ManifestError
from physgate.evaluation.observe.manifest import BINARY_DEFAULTS, RunManifest, read_manifest
from physgate.orchestrator.invocation import PINNED_VERSIONS
from physgate.orchestrator.managed import FlagDrift
from physgate.orchestrator.run_config import ModelStrings


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("runs")
    return fake_run(root, "run-a", target_repo(root))


def test_the_manifest_holds_every_input_and_artefact_the_run_recorded(run: Path) -> None:
    manifest = read_manifest(run)
    assert manifest.manifest_id == hashlib.sha256((run / "run.json").read_bytes()).hexdigest()
    config = manifest.config
    assert (config.seed, config.effort, config.max_output_tokens) == (1, "high", 64000)
    assert config.models.roles == {"electrical": "claude-sonnet-5"}
    assert config.harness.commit is None or len(config.harness.commit) == 40
    assert manifest.binary_defaults == (BINARY_DEFAULTS[("2.1.272", "claude-sonnet-5")],)
    assert manifest.binary_defaults[0].thinking == {"type": "adaptive"}
    art = manifest.artefacts
    assert len(art.merged) == 2 and art.spec_commit and art.spec_tree
    integration = run / "worktrees" / "_integration"
    for merged in art.merged:  # every tree is the one git holds for that commit
        assert git(integration, "rev-parse", f"{merged.merge_commit}^{{tree}}").strip() == (
            merged.merge_tree
        )
    assert art.run_branch_head == art.merged[-1].merge_commit
    assert (
        art.journal_sha256
        == hashlib.sha256((run / "store" / "journal.jsonl").read_bytes()).hexdigest()
    )
    assert art.journal_head_revision == 3  # the interface node, then one node per subtask
    assert art.store_tree and len(art.trajectories) == 2


def test_read_manifest_resolves_binary_defaults_for_every_pinned_version(
    tmp_path: Path,
) -> None:
    assert {version for version, _ in BINARY_DEFAULTS} == PINNED_VERSIONS
    for (version, model), entry in sorted(BINARY_DEFAULTS.items()):
        reviewer = "claude-opus-5-5" if model != "claude-opus-5-5" else "claude-sonnet-5"
        models = ModelStrings(
            decomposition=model, roles={"electrical": model}, reviewers={"electrical": reviewer}
        )
        run = fake_run(
            tmp_path / version,
            "run-a",
            target_repo(tmp_path / version),
            # Each entry was measured with the search tool offered.
            overrides={"claude_version": version, "models": models, "tool_search": "offered"},
        )
        manifest = read_manifest(run)
        assert manifest.config.claude_version == version
        assert manifest.binary_defaults == (entry,)
        assert (entry.claude_version, entry.model) == (version, model)
    # The decomposition request was measured to differ from the sessions' on 2.1.301 and 2.1.322.
    assert [v for (v, _), d in sorted(BINARY_DEFAULTS.items()) if d.decomposition] == [
        "2.1.301",
        "2.1.322",
    ]


@pytest.mark.parametrize(
    "missing",
    sorted(RunManifest.model_fields),
)
def test_a_manifest_missing_any_field_fails_its_schema(run: Path, missing: str) -> None:
    whole = json.loads(read_manifest(run).model_dump_json())
    del whole[missing]
    with pytest.raises(ValueError, match="Field required"):
        RunManifest.model_validate_json(json.dumps(whole))


def test_a_configuration_that_is_not_the_one_the_run_started_under_is_refused(
    tmp_path: Path,
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    recorded = json.loads((run / "run.json").read_text())
    recorded["seed"] = 2  # a valid configuration, but not the one the first line names
    (run / "run.json").write_text(json.dumps(recorded, separators=(",", ":")) + "\n")
    with pytest.raises(ManifestError, match="does not name the configuration"):
        read_manifest(run)


def test_a_commit_the_record_names_that_git_does_not_hold_is_an_error(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = (run / "events.jsonl").read_text().splitlines()
    merged = next(i for i, line in enumerate(events) if '"kind":"merged"' in line)
    record = json.loads(events[merged])
    record["merge_commit"] = "0" * 40
    events[merged] = json.dumps(record, separators=(",", ":"))
    (run / "events.jsonl").write_text("\n".join(events) + "\n")
    with pytest.raises(ManifestError, match="does not hold"):
        read_manifest(run)


def test_a_directory_with_no_run_is_a_domain_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        read_manifest(tmp_path)


def test_a_run_whose_sessions_left_no_flag_cache_has_no_count_in_its_manifest(run: Path) -> None:
    assert read_manifest(run).flag_cache is None


def test_the_manifest_counts_the_flag_caches_the_run_s_sessions_left(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    log = run / "events.jsonl"
    digests = iter(("8c" * 32, "ca" * 32))
    lines = []
    for line in log.read_text().split("\n"):
        event = json.loads(line) if line else None
        if event is not None and event["kind"] == "session_ended":
            # As a session on a pin that fetches the flags is recorded: what its binary held.
            event["flag_cache"] = {"entries": 1256, "sha256": next(digests)}
            line = json.dumps(event)
        lines.append(line)
    log.write_text("\n".join(lines))
    assert read_manifest(run).flag_cache == FlagDrift(readings=2, changes=1)
