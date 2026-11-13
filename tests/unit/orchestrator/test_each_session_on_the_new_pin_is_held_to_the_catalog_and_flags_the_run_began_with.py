"""On 2.1.322 the catalog and flags each session saw are recorded, and a change halts the run.

By the owner's choice, sessions on 2.1.322 carry the feature-flag and non-essential traffic the
advisor needs, so the served model catalog and the remote flags are no longer switched off. What
they were is recorded instead: the decomposition call reads its own debug log as before, every
role session on that pin writes one too, and a session that saw another state than the run's
first observation halts the run before anything it did is taken, as changed policy limits do.

Runs on the earlier pins are untouched: their role sessions write no debug log, their argv is
what it was, and they carry no such check. The run records which switches its sessions carried,
per pin, so a record says what the environment was rather than what the code says today.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.events import Halted, Incident, SessionEnded, read_events
from physgate.orchestrator.invocation import role_argv, session_env_settings, traffic_settings
from physgate.orchestrator.managed import ObservedTraffic, traffic_change
from physgate.orchestrator.record import DecompositionSummary

#: What 2.1.322's decomposition call read at the scripted endpoint (CI, 11.11.2026).
SEEN = ObservedTraffic(
    served_catalog="off", served_catalog_reason="not_first_party", feature_flags="not reported off"
)
SERVED = SEEN.model_copy(
    update={"served_catalog": "not reported off", "served_catalog_reason": None}
)
FLAGS_OFF = SEEN.model_copy(update={"feature_flags": "off"})


@pytest.mark.parametrize("version", ["2.1.301", "2.1.322"])
def test_a_run_records_every_switch_its_pin_s_sessions_carried(version: str) -> None:
    recorded = traffic_settings(version)
    assert recorded.switches == tuple(session_env_settings(version).items())


def test_on_the_new_pin_the_record_says_the_traffic_is_on() -> None:
    recorded = traffic_settings("2.1.322")
    assert (recorded.nonessential_traffic, recorded.telemetry) == ("enabled", "enabled")
    assert "2.1.272" not in recorded.measured  # not the earlier pins' measurement of "off"


def test_on_2_1_301_the_record_says_what_it_said_before() -> None:
    recorded = traffic_settings("2.1.301")
    assert (recorded.nonessential_traffic, recorded.telemetry) == ("disabled", "disabled")
    assert "2.1.272" in recorded.measured


def _argv(debug_file: Path | None = None) -> list[str]:
    return role_argv(
        "/opt/claude",
        prompt="p",
        spawn_args=("--setting-sources", "", "--settings", "/s.json"),
        model="claude-opus-5-5",
        session_id="sid",
        max_turns=40,
        effort="high",
        thinking_display="summarized",
        **({} if debug_file is None else {"debug_file": debug_file}),
    )


#: A role session's argv as every pin received it before the second pin, word for word.
ARGV_BEFORE = [
    "/opt/claude",
    "-p",
    "p",
    "--setting-sources",
    "",
    "--settings",
    "/s.json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--include-hook-events",
    "--include-partial-messages",
    "--model",
    "claude-opus-5-5",
    "--effort",
    "high",
    "--thinking-display",
    "summarized",
    "--session-id",
    "sid",
    "--max-turns",
    "40",
    "--permission-mode",
    "bypassPermissions",
]


def test_a_role_session_without_a_debug_file_gets_the_argv_it_always_had() -> None:
    assert _argv() == ARGV_BEFORE


def test_a_role_session_given_a_debug_file_writes_its_log_there_and_nothing_else_moves() -> None:
    argv = _argv(Path("/s/config/debug.log"))
    assert argv == [*ARGV_BEFORE, "--debug-file", "/s/config/debug.log"]


def test_the_same_state_is_no_change_and_a_session_with_no_log_is_never_held() -> None:
    assert traffic_change(SEEN, SEEN) is None
    assert traffic_change(SEEN, None) is None  # an earlier pin's session reads no log
    assert traffic_change(None, None) is None


@pytest.mark.parametrize("now", [SERVED, FLAGS_OFF], ids=["catalog", "flags"])
def test_another_catalog_or_flags_state_is_named_with_both_states(now: ObservedTraffic) -> None:
    changed = traffic_change(SEEN, now)
    assert changed is not None
    assert "catalog" in changed and "flags" in changed
    assert now.feature_flags in changed and now.served_catalog in changed


def _start(rig: Rig, seen: ObservedTraffic | None, *subtasks: str) -> None:
    loop = rig.open()
    loop.record.start(
        plan(*(subtasks or ("s1",))),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(subtasks or ("s1",)),
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            observed_traffic=seen,
        ),
    )
    loop.close()


def test_a_session_that_saw_what_the_decomposition_saw_is_taken_and_records_it(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN}))
    _start(rig, SEEN)
    loop = rig.open()
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert ended.observed_traffic == SEEN
    assert not any(isinstance(e, Incident) for e in events)


@pytest.mark.parametrize("now", [SERVED, FLAGS_OFF], ids=["catalog", "flags"])
def test_a_session_that_saw_another_state_halts_the_run_before_anything_is_taken(
    tmp_path: Path, now: ObservedTraffic
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: now}))
    _start(rig, SEEN)
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s1"
    assert "catalog" in incident.detail
    assert any(isinstance(e, Halted) for e in events)
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert ended.observed_traffic == now  # what the session saw is on the record
    assert not any(e.kind in ("gate_ran", "merged") for e in events)


def test_where_the_decomposition_saw_nothing_the_first_session_s_state_is_the_baseline(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(traffic={1: SEEN, 2: SERVED}))
    _start(rig, None, "s1", "s2")
    loop = rig.open()
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e.observed_traffic for e in events if isinstance(e, SessionEnded)] == [SEEN, SERVED]
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "managed_settings_changed" and incident.subtask_id == "s2"
