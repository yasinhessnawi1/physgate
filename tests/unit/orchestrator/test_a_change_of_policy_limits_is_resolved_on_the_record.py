"""A change of a run's policy limits is resolved on the record: by a person, or by the owner's rule.

Every session is held to the policy limits the run's decomposition call received, and other
limits halt the run as a ``managed_settings_changed`` incident. A provider's overnight rollout
did that to a live run: one restriction added, set to ``allowed: false``, and the run was lost,
since an incident halt had no resume. Now:

- a change that only adds restrictions set to ``allowed: false``, with nothing removed and
  nothing else changed, is resolved by the owner's rule as the session ends: one line with
  ``by: "rule"``, both digests and the change, and the run goes on under the new limits. The
  live run's own two files, copied with their restriction keys alone, are such a change;
- any other change still halts as an incident, and so does that change beside another finding;
- a person resolves the halt with ``physgate incident resolve``, which refuses unless run at a
  terminal. Shown the change by key and value (a value not a flag, a number or null by its kind
  and size only), the person types ``yes``, and the line records who, why, both digests and the
  change. The resume then accepts the run, and later sessions are held to the new limits;
- the replay moves the baseline by that line alone: a log without it, or with one the record does
  not support, is refused.

The terminal check is never faked here: its refusal is tested, and what it guards is tested by
the function it calls, as promotion's is.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.cli import main
from physgate.orchestrator.events import Halted, Incident, Resumed, SessionEnded, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError, RunStateError
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import replay

FIXTURES = Path(__file__).resolve().parent / "policy_limits"
#: The live run's two files, their restriction keys and values alone: one restriction added.
BEFORE = (FIXTURES / "run7_before.json").read_bytes()
AFTER = (FIXTURES / "run7_after.json").read_bytes()
ADDED = ("restrictions", "allow_cobalt_plinth_alkanet", "allowed")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new(module: str, name: str) -> Any:  # noqa: ANN401 - whatever the module defines
    """``module.name``, or the row fails: what it names does not exist yet."""
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        pytest.fail(f"{module}.{name} does not exist: an incident has no recorded resolution")


def _limits(**restrictions: bool) -> bytes:
    body = {"restrictions": {k: {"allowed": v} for k, v in restrictions.items()}}
    return json.dumps(body, sort_keys=True).encode()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _rig(tmp_path: Path, files: dict[int, bytes], **dispatcher: Any) -> Rig:  # noqa: ANN401
    """A run whose decomposition received ``BEFORE``, and whose ``n``-th session ``files[n]``."""
    _write(tmp_path / "decomposition" / "config" / "policy-limits.json", BEFORE)
    for call, data in files.items():
        _write(tmp_path / "sessions" / f"sess-{call}" / "config" / "policy-limits.json", data)
    policy = {call: _digest(data) for call, data in files.items()}
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(policy=policy, **dispatcher))
    loop = rig.open()
    loop.record.start(
        plan("s1", "s2"),
        decomposed=DecompositionSummary(
            session_id="d1",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=2,
            interface_nodes=("iface.bus",),
            spec_commit="a" * 40,
            head_revision=1,
            policy_limits_sha256=_digest(BEFORE),
        ),
    )
    loop.close()
    return rig


def _drive(rig: Rig, *, resume: bool = False) -> str:
    loop = rig.open()
    try:
        return (loop.resume() if resume else loop.run()).kind
    finally:
        loop.close()


def _lines(tmp_path: Path, kind: str) -> list[dict[str, Any]]:
    raw = (tmp_path / "events.jsonl").read_text().splitlines()
    return [line for line in map(json.loads, raw) if line["kind"] == kind]


# ── the owner's rule ─────────────────────────────────────────────────────────


def test_the_live_run_s_change_is_the_rule_s_and_the_run_goes_on_under_the_new_limits(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, {1: AFTER, 2: AFTER})
    assert _drive(rig) == "done"
    assert _lines(tmp_path, "incident") == []
    assert _lines(tmp_path, "halted") == []
    resolved = _lines(tmp_path, "incident_resolved")
    assert len(resolved) == 1, "the change was not resolved on the record"
    (line,) = resolved
    assert (line["by"], line["rule"], line["session_id"], line["subtask_id"]) == (
        "rule",
        True,
        "sess-1",
        "s1",
    )
    assert (line["old_sha256"], line["new_sha256"]) == (_digest(BEFORE), _digest(AFTER))
    assert line["changes"] == [{"path": list(ADDED), "before": None, "after": "false"}]
    assert line["omitted"] == 0
    # Recorded before the session's end line, and the second session is held to the new limits.
    ended = _lines(tmp_path, "session_ended")
    assert [e["session_id"] for e in ended] == ["sess-1", "sess-2"]
    assert line["seq"] < ended[0]["seq"]
    replay(read_events(tmp_path / "events.jsonl"))


#: Changes that are not only added restrictions set to ``allowed: false``.
NOT_THE_RULE = {
    "a restriction removed": _limits(allow_connector_file_downloads=False),
    "a restriction loosened": _limits(
        allow_connector_file_downloads=True, enforce_web_search_mcp_isolation=False
    ),
    "a restriction added as allowed": _limits(
        allow_connector_file_downloads=False, enforce_web_search_mcp_isolation=False, new=True
    ),
    "a key beside the restrictions": json.dumps(
        {**json.loads(BEFORE), "defaults": {"remote_control_at_startup": False}}, sort_keys=True
    ).encode(),
    "an added restriction with more than its flag": json.dumps(
        {
            "restrictions": {
                **json.loads(BEFORE)["restrictions"],
                "new": {"allowed": False, "until": "later"},
            }
        },
        sort_keys=True,
    ).encode(),
    "the same keys, written otherwise": BEFORE.replace(b"\n", b" \n"),
}


@pytest.mark.parametrize("case", NOT_THE_RULE)
def test_any_other_change_still_halts_as_an_incident_for_a_person(
    tmp_path: Path, case: str
) -> None:
    _new("physgate.orchestrator.events", "IncidentResolved")
    rig = _rig(tmp_path, {1: NOT_THE_RULE[case]})
    assert _drive(rig) == "halted"
    assert [i["cause"] for i in _lines(tmp_path, "incident")] == ["managed_settings_changed"]
    assert _lines(tmp_path, "incident_resolved") == []


def test_the_rule_does_not_resolve_a_change_whose_files_are_not_the_ones_recorded(
    tmp_path: Path,
) -> None:
    _new("physgate.orchestrator.events", "IncidentResolved")
    rig = _rig(tmp_path, {1: AFTER})
    # The session's file is rewritten after its digest was taken: no evidence of the change.
    _write(tmp_path / "sessions" / "sess-1" / "config" / "policy-limits.json", AFTER + b" ")
    assert _drive(rig) == "halted"
    assert _lines(tmp_path, "incident_resolved") == []


def test_the_rule_does_not_resolve_the_change_beside_another_finding(tmp_path: Path) -> None:
    _new("physgate.orchestrator.events", "IncidentResolved")
    rig = _rig(tmp_path, {1: AFTER}, drift={1: "remote managed settings were delivered"})
    assert _drive(rig) == "halted"
    assert _lines(tmp_path, "incident_resolved") == []


def test_a_value_that_is_not_a_flag_is_shown_by_kind_and_size_only() -> None:
    policy_diff = _new("physgate.orchestrator.managed", "policy_diff")
    diff_lines = _new("physgate.orchestrator.managed", "diff_lines")
    stricter_only = _new("physgate.orchestrator.managed", "stricter_only")
    secret = "s3cr3t-value-never-printed"
    changes, omitted = policy_diff(
        {"restrictions": {}, "note": "old", "n": [1]},
        {"restrictions": {}, "note": secret, "n": [1, 2], "on": True, "k": None},
    )
    shown = diff_lines(changes, omitted)
    assert shown == [
        "+ k: null",
        "~ n: a list of 1 entries -> a list of 2 entries",
        "~ note: a string of 3 characters -> a string of 26 characters",
        "+ on: true",
    ]
    assert not any(secret in line for line in shown)
    assert not stricter_only(changes, omitted)
    added, none_omitted = policy_diff(json.loads(BEFORE), json.loads(AFTER))
    assert stricter_only(added, none_omitted)
    assert [tuple(e.path) for e in added] == [ADDED]


# ── a person, at a terminal ──────────────────────────────────────────────────


class _Stdin(io.StringIO):
    def isatty(self) -> bool:
        return False


def _command(*argv: str) -> int:
    try:
        return main(list(argv))
    except SystemExit as exc:  # a command the parser does not know
        return int(exc.code or 0)


def test_the_command_refuses_unless_a_person_is_at_a_terminal_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = _rig(tmp_path, {1: NOT_THE_RULE["a restriction removed"]})
    assert _drive(rig) == "halted"
    before = (tmp_path / "events.jsonl").read_bytes()
    monkeypatch.setattr(sys, "stdin", _Stdin("yes\n"))
    rc = _command(
        "incident", "resolve", "--run-dir", str(tmp_path), "--by", "yasin", "--reason", "rollout"
    )
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "only by a person at a terminal" in err
    assert (tmp_path / "events.jsonl").read_bytes() == before


def _resolve(tmp_path: Path, answer: str = "yes", **given: str) -> tuple[Any, list[str]]:
    record_resolution = _new("physgate.orchestrator.incident", "record_resolution")
    shown: list[str] = []
    resolved = record_resolution(
        tmp_path,
        by=given.get("by", "yasin"),
        reason=given.get("reason", "a provider's rollout; the run may go on"),
        confirm=lambda _: answer,
        notice=shown.append,
    )
    return resolved, shown


def test_a_person_s_resolution_is_recorded_and_the_resume_accepts_the_run(tmp_path: Path) -> None:
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed, 2: removed})
    assert _drive(rig) == "halted"
    with pytest.raises(RunStateError, match="a person resolves that before any resume"):
        _drive(rig, resume=True)
    resolved, shown = _resolve(tmp_path)
    assert "- restrictions.enforce_web_search_mcp_isolation.allowed: false" in shown
    assert f"before: {_digest(BEFORE)}" in shown
    assert f"after:  {_digest(removed)}" in shown
    (line,) = _lines(tmp_path, "incident_resolved")
    assert (line["by"], line["rule"], line["reason"]) == (
        "yasin",
        False,
        "a provider's rollout; the run may go on",
    )
    assert (line["old_sha256"], line["new_sha256"], line["session_id"]) == (
        _digest(BEFORE),
        _digest(removed),
        "sess-1",
    )
    assert resolved.new_sha256 == _digest(removed)
    # The resume takes the run on: the halted attempt's session is judged, and the next
    # session, under the same new limits, is no incident.
    assert _drive(rig, resume=True) == "done"
    events = read_events(tmp_path / "events.jsonl")
    assert [e.point for e in events if isinstance(e, Resumed)] == ["verify_reading"]
    assert len([e for e in events if isinstance(e, Incident)]) == 1
    assert [e.session_id for e in events if isinstance(e, SessionEnded)] == ["sess-1", "sess-2"]
    replay(events)


def test_a_resolution_not_confirmed_or_without_a_name_or_a_reason_records_nothing(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, {1: NOT_THE_RULE["a restriction removed"]})
    assert _drive(rig) == "halted"
    before = (tmp_path / "events.jsonl").read_bytes()
    for answer, given in (
        ("no", {}),
        ("", {}),
        ("yes", {"by": "rule"}),
        ("yes", {"by": " "}),
        ("yes", {"reason": " "}),
    ):
        with pytest.raises(RunStateError):
            _resolve(tmp_path, answer, **given)
        assert (tmp_path / "events.jsonl").read_bytes() == before, (answer, given)


def test_only_a_halt_on_a_change_of_policy_limits_is_resolved_and_only_once(
    tmp_path: Path,
) -> None:
    _new("physgate.orchestrator.incident", "record_resolution")
    # Remote managed settings delivered, with the run's own limits: not this command's to resolve.
    rig = _rig(tmp_path, {1: BEFORE}, drift={1: "remote managed settings were delivered"})
    assert _drive(rig) == "halted"
    with pytest.raises(RunStateError, match="other managed settings changed"):
        _resolve(tmp_path)
    assert _lines(tmp_path, "incident_resolved") == []
    # A halt on a change of limits, resolved once: a second is refused.
    again = tmp_path / "again"
    rig = _rig(again, {1: NOT_THE_RULE["a restriction removed"]})
    assert _drive(rig) == "halted"
    _resolve(again)
    with pytest.raises(RunStateError, match="resolved already"):
        _resolve(again)
    assert len(_lines(again, "incident_resolved")) == 1


# ── the replay ───────────────────────────────────────────────────────────────


def test_the_replay_moves_the_baseline_by_the_resolution_alone(tmp_path: Path) -> None:
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed, 2: removed})
    assert _drive(rig) == "halted"
    _resolve(tmp_path)
    assert _drive(rig, resume=True) == "done"
    events = read_events(tmp_path / "events.jsonl")
    state = replay(events)
    assert state.policy_baseline == _digest(removed)
    (at,) = [i for i, e in enumerate(events) if e.kind == "incident_resolved"]
    resolved = events[at]
    # No resolution: the resume of an incident's halt is refused.
    with pytest.raises(CorruptEventLogError):
        replay(events[:at] + events[at + 1 :])
    # One the record does not support: another session's limits, or from another baseline.
    for forged in (
        resolved.model_copy(update={"new_sha256": _digest(b"{}")}),
        resolved.model_copy(update={"session_id": "sess-2"}),
        resolved.model_copy(update={"old_sha256": _digest(b"{}")}),
    ):
        with pytest.raises(CorruptEventLogError):
            replay([*events[:at], forged, *events[at + 1 :]])
    # A resolution where no incident halted the run.
    found = next(i for i, e in enumerate(events) if isinstance(e, Incident))
    with pytest.raises(CorruptEventLogError):
        replay([*events[:found], resolved])
    assert any(isinstance(e, Halted) for e in events)


def test_the_replay_refuses_the_rule_s_change_with_its_line_taken_out_or_forged(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, {1: AFTER, 2: AFTER})
    assert _drive(rig) == "done"
    events = read_events(tmp_path / "events.jsonl")
    ruled = [i for i, e in enumerate(events) if e.kind == "incident_resolved"]
    assert len(ruled) == 1, "the rule resolved nothing"
    (at,) = ruled
    # Taken out: the session ended under other limits, and nothing says so.
    with pytest.raises(CorruptEventLogError):
        replay(events[:at] + events[at + 1 :])
    # Naming other limits than the session's end.
    forged = events[at].model_copy(update={"new_sha256": _digest(b"{}")})
    with pytest.raises(CorruptEventLogError):
        replay([*events[:at], forged, *events[at + 1 :]])
    # The rule's line cannot name a change that is not its rule's.
    resolved_type = _new("physgate.orchestrator.events", "IncidentResolved")
    loosened = events[at].model_dump(mode="json") | {
        "changes": [{"path": list(ADDED), "before": None, "after": "true"}]
    }
    with pytest.raises(ValueError, match="only a change that adds restrictions"):
        resolved_type.model_validate_json(json.dumps(loosened))
