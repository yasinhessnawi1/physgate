"""The managed-settings tier, which ``--setting-sources ""`` does not govern, is pinned and watched.

Every invocation names the run's own override file (so an eligible account's
remote managed settings are not fetched), the override is checked before every
spawn, and after every invocation anything that changed in the tier is drift:
remote settings delivered into the configuration directory, the override
changed, or a system managed path changed. System paths are only ever read.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import Halted, Incident, read_events
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.managed import (
    EMPTY_OVERRIDE,
    EMPTY_OVERRIDE_SHA256,
    drift,
    require_override,
    system_managed_facts,
    system_managed_paths,
    write_override,
)


def test_the_override_is_written_read_only_once_and_never_replaced(tmp_path: Path) -> None:
    path = write_override(tmp_path)
    assert path.read_bytes() == EMPTY_OVERRIDE == b"{}\n"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EMPTY_OVERRIDE_SHA256
    assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert write_override(tmp_path) == path  # the same one is kept
    with pytest.raises(InvocationError, match="different managed-settings override"):
        write_override(tmp_path, b'{"disableAllHooks": true}\n')


def test_a_spawn_is_refused_unless_the_override_is_the_recorded_one(tmp_path: Path) -> None:
    path = write_override(tmp_path)
    require_override(path, EMPTY_OVERRIDE_SHA256)
    with pytest.raises(InvocationError) as caught:
        require_override(path, "0" * 64)
    assert caught.value.context["found"] == EMPTY_OVERRIDE_SHA256
    with pytest.raises(InvocationError) as missing:
        require_override(tmp_path / "absent.json", EMPTY_OVERRIDE_SHA256)
    assert missing.value.context["found"] == "missing"


def test_drift_names_every_change_in_the_tier_and_nothing_else(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    override = write_override(tmp_path)
    system = tmp_path / "etc" / "managed-settings.json"
    before = system_managed_facts((system,))
    assert drift(config, override, EMPTY_OVERRIDE_SHA256, before) is None
    (config / "remote-settings.json").write_text("{}")  # the fetch's empty answer
    assert drift(config, override, EMPTY_OVERRIDE_SHA256, before) is None

    (config / "remote-settings.json").write_text(json.dumps({"disableAllHooks": True}))
    found = drift(config, override, EMPTY_OVERRIDE_SHA256, before)
    assert found is not None and "remote managed settings were delivered" in found
    (config / "remote-settings.json").unlink()

    override.chmod(0o644)
    override.write_text('{"env": {}}')
    found = drift(config, override, EMPTY_OVERRIDE_SHA256, before)
    assert found is not None and "override" in found and "changed" in found
    override.write_bytes(EMPTY_OVERRIDE)

    system.parent.mkdir()
    system.write_text('{"disableAllHooks": true}')
    found = drift(config, override, EMPTY_OVERRIDE_SHA256, before)
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
