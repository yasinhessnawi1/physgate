"""The managed-settings tier, which ``--setting-sources ""`` does not govern, is watched.

The agent under test does not write it, every session starts from a fresh
configuration directory, and after every invocation anything the tier held or
changed is drift: remote settings delivered into the configuration directory,
or a system managed path that changed. Drift halts the run. System paths are
only ever read. Detection, not prevention: the one prevention the binary seemed
to offer (``CLAUDE_CODE_REMOTE_SETTINGS_PATH``) was measured to do nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import Decomposed, Halted, Incident, SessionEnded, read_events
from physgate.orchestrator.managed import (
    drift,
    policy_limits_change,
    policy_limits_digest,
    system_managed_facts,
    system_managed_paths,
)
from physgate.orchestrator.record import DecompositionSummary


def test_drift_names_every_change_in_the_tier_and_nothing_else(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    system = tmp_path / "etc" / "managed-settings.json"
    before = system_managed_facts((system,))
    assert drift(config, before) is None
    (config / "remote-settings.json").write_text("{}")  # the fetch's empty answer
    assert drift(config, before) is None

    (config / "remote-settings.json").write_text(json.dumps({"disableAllHooks": True}))
    found = drift(config, before)
    assert found is not None and "remote managed settings were delivered" in found
    (config / "remote-settings.json").unlink()

    system.parent.mkdir()
    system.write_text('{"disableAllHooks": true}')
    found = drift(config, before)
    assert found is not None and f"system managed path {system} changed" in found


def test_the_system_paths_are_the_binary_s_own_and_only_read(tmp_path: Path) -> None:
    mac = [str(p) for p in system_managed_paths("darwin", user="someone")]
    assert "/Library/Application Support/ClaudeCode/managed-settings.json" in mac
    assert "/Library/Application Support/ClaudeCode/managed-settings.d" in mac
    assert "/Library/Managed Preferences/someone/com.anthropic.claudecode.plist" in mac
    assert "/Library/Managed Preferences/com.anthropic.claudecode.plist" in mac
    linux = [str(p) for p in system_managed_paths("linux")]
    assert linux == [
        "/etc/claude-code/managed-settings.json",
        "/etc/claude-code/managed-settings.d",
        "/etc/claude-code/managed-mcp.json",
    ]
    absent, present, folder = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "d"
    present.write_text("{}")
    folder.mkdir()
    (folder / "10.json").write_text("{}")
    facts = system_managed_facts((absent, present, folder))
    assert [f.exists for f in facts] == [False, True, True]
    assert facts[1].sha256 == hashlib.sha256(b"{}").hexdigest() and facts[1].mode is not None
    assert facts[2].sha256 is not None
    assert not absent.exists()  # recorded, never created


def test_drift_during_a_session_is_an_incident_that_halts_before_anything_is_taken(
    tmp_path: Path,
) -> None:
    rig = Rig(
        tmp_path, dispatcher=FakeDispatcher(drift={1: "remote managed settings were delivered"})
    )
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s1"
    assert [e.reason for e in events if isinstance(e, Halted)] == ["incident"]
    assert not any(e.kind in ("gate_ran", "merged") for e in events)


LIMITS = hashlib.sha256(b'{"restrictions": {}}').hexdigest()
OTHER = hashlib.sha256(b'{"restrictions": {"x": {"allowed": false}}}').hexdigest()


def test_the_policy_limits_file_is_digested_and_its_absence_is_none(tmp_path: Path) -> None:
    assert policy_limits_digest(tmp_path) is None
    (tmp_path / "policy-limits.json").write_bytes(b'{"restrictions": {}}')
    assert policy_limits_digest(tmp_path) == LIMITS
    (tmp_path / "policy-limits.json.stamp.json").write_text('{"confirmed_at": 1}')
    assert policy_limits_digest(tmp_path) == LIMITS  # the stamp's timestamp is not the limits


def test_a_change_appearance_or_disappearance_of_the_limits_is_named() -> None:
    assert policy_limits_change(LIMITS, LIMITS) is None
    assert policy_limits_change(None, None) is None
    assert "changed" in str(policy_limits_change(LIMITS, OTHER))
    assert "appeared" in str(policy_limits_change(None, LIMITS))
    assert "no policy limits arrived" in str(policy_limits_change(LIMITS, None))


def _start_with_limits(rig: Rig, limits: str | None) -> None:
    loop = rig.open()
    loop.record.start(
        plan("s1"),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=1,
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            policy_limits_sha256=limits,
        ),
    )
    loop.close()


def test_a_session_under_the_decomposition_s_limits_is_taken_and_records_them(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(policy={1: LIMITS}))
    _start_with_limits(rig, LIMITS)
    loop = rig.open()
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")  # a fresh read of the durable record
    (decomposed,) = [e for e in events if isinstance(e, Decomposed)]
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert decomposed.policy_limits_sha256 == ended.policy_limits_sha256 == LIMITS
    assert not any(isinstance(e, Incident) for e in events)


@pytest.mark.parametrize(
    ("baseline", "session"),
    [(LIMITS, OTHER), (LIMITS, None), (None, LIMITS)],
    ids=["changed", "disappeared", "appeared"],
)
def test_a_session_under_other_policy_limits_is_an_incident_before_anything_is_taken(
    tmp_path: Path, baseline: str | None, session: str | None
) -> None:
    policy = {1: session} if session is not None else {}
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(policy=policy))
    _start_with_limits(rig, baseline)
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s1"
    assert "policy limits" in incident.detail
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert ended.policy_limits_sha256 == session  # what the session received is on the record
    assert not any(e.kind in ("gate_ran", "merged") for e in events)
