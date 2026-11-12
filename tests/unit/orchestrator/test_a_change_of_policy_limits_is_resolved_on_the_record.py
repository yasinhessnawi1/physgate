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
from design_review_rig import outcome_of
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.cli import main
from physgate.orchestrator.events import (
    RULE,
    RULE_REASON,
    Halted,
    Incident,
    IncidentResolved,
    Resumed,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, RunStateError
from physgate.orchestrator.managed import (
    PolicyEntry,
    UnshowableKeyError,
    limits_with,
    policy_diff,
    stricter_only,
)
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


def test_a_second_stricter_change_is_judged_from_the_first_s_limits(tmp_path: Path) -> None:
    stricter = json.dumps(
        {"restrictions": {**json.loads(AFTER)["restrictions"], "later": {"allowed": False}}},
        sort_keys=True,
    ).encode()
    rig = _rig(tmp_path, {1: AFTER, 2: stricter})
    assert _drive(rig) == "done"
    resolved = _lines(tmp_path, "incident_resolved")
    assert [(r["old_sha256"], r["new_sha256"]) for r in resolved] == [
        (_digest(BEFORE), _digest(AFTER)),
        (_digest(AFTER), _digest(stricter)),
    ]
    assert resolved[1]["changes"] == [
        {"path": ["restrictions", "later", "allowed"], "before": None, "after": "false"}
    ]
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
    "a restriction's flag nested a level deeper": json.dumps(
        {"restrictions": {**json.loads(BEFORE)["restrictions"], "new": {"allowed": {"x": False}}}},
        sort_keys=True,
    ).encode(),
    "a flag set false under another key than the restrictions": json.dumps(
        {**json.loads(BEFORE), "limits": {"new": {"allowed": False}}}, sort_keys=True
    ).encode(),
    "another flag of an added restriction set false": json.dumps(
        {"restrictions": {**json.loads(BEFORE)["restrictions"], "new": {"enforced": False}}},
        sort_keys=True,
    ).encode(),
    "more restrictions added than one line lists": json.dumps(
        {
            "restrictions": {
                **json.loads(BEFORE)["restrictions"],
                **{f"new_{n:03}": {"allowed": False} for n in range(201)},
            }
        },
        sort_keys=True,
    ).encode(),
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


#: Each file the rule reads, as a run directory names it, and what it holds.
RULED_FILES = {
    "the session's": (Path("sessions") / "sess-1" / "config" / "policy-limits.json", AFTER),
    "the decomposition call's": (Path("decomposition") / "config" / "policy-limits.json", BEFORE),
}


@pytest.mark.parametrize("which", RULED_FILES)
def test_the_rule_does_not_resolve_a_change_whose_files_are_not_the_ones_recorded(
    tmp_path: Path, which: str
) -> None:
    _new("physgate.orchestrator.events", "IncidentResolved")
    rig = _rig(tmp_path, {1: AFTER})
    # The file is rewritten after its digest was taken: no evidence of what it held. Read as no
    # file, the decomposition call's would make every key of the session's an added one.
    where, data = RULED_FILES[which]
    _write(tmp_path / where, data + b" ")
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
        {"restrictions": {}, "note": "old", "n": [1], "f": 1},
        {"restrictions": {}, "note": secret, "n": [1, 2], "on": True, "k": None, "f": True},
    )
    shown = diff_lines(changes, omitted)
    assert shown == [
        '~ "f": 1 -> true',
        '+ "k": null',
        '~ "n": a list of 1 entries -> a list of 2 entries',
        '~ "note": a string of 3 characters -> a string of 26 characters',
        '+ "on": true',
    ]
    assert not any(secret in line for line in shown)
    assert not stricter_only(changes, omitted)
    added, none_omitted = policy_diff(json.loads(BEFORE), json.loads(AFTER))
    assert stricter_only(added, none_omitted)
    assert [tuple(e.path) for e in added] == [ADDED]


def _entry(path: tuple[str, ...], before: str | None = None, after: str = "false") -> PolicyEntry:
    return PolicyEntry(path=path, before=before, after=after)


#: Changes the rule never takes, each one step from a restriction added as ``allowed: false``.
NOT_THE_RULE_S_ENTRIES = {
    "a restriction there before, set false now": ((_entry(ADDED, before="true"),), 0),
    "a key a level below a restriction's flag": ((_entry((*ADDED, "inner")),), 0),
    "a restriction's flag under another key": ((_entry(("limits", *ADDED[1:])),), 0),
    "another key of a restriction set false": ((_entry((*ADDED[:2], "enforced")),), 0),
    "added restrictions, and more keys than listed": ((_entry(ADDED),), 1),
    "no change at all": ((), 0),
}


@pytest.mark.parametrize("case", NOT_THE_RULE_S_ENTRIES)
def test_the_rule_takes_only_restrictions_added_each_set_to_allowed_false(case: str) -> None:
    assert stricter_only((_entry(ADDED),), 0)
    entries, omitted = NOT_THE_RULE_S_ENTRIES[case]
    assert not stricter_only(entries, omitted)


def test_the_rule_s_name_and_the_rule_s_flag_go_together_on_a_resolution(tmp_path: Path) -> None:
    rig = _rig(tmp_path, {1: AFTER, 2: AFTER})
    assert _drive(rig) == "done"
    (line,) = _lines(tmp_path, "incident_resolved")
    assert IncidentResolved.model_validate_json(json.dumps(line)).rule
    # A person's name on the rule's line, or the rule's name on a person's.
    for given in ({"by": "yasin"}, {"rule": False}):
        with pytest.raises(ValueError, match="the rule, and only the rule"):
            IncidentResolved.model_validate_json(json.dumps(line | given))


def test_a_key_that_does_not_print_as_itself_refuses_the_whole_diff_changed_or_not() -> None:
    spoofed = json.loads(SPOOFED)
    more: dict[str, object] = {
        "restrictions": {**spoofed["restrictions"], "new": {"allowed": False}}
    }
    # The key is the same on both sides, and only another restriction is added: still refused.
    with pytest.raises(UnshowableKeyError):
        policy_diff(spoofed, more)
    with pytest.raises(UnshowableKeyError):
        policy_diff(more, spoofed)


@pytest.mark.parametrize(
    "where",
    [
        Path("decomposition") / "config",
        Path("decomposition") / "round-2" / "retry" / "config",
        Path("sessions") / "sess-3" / "config",
    ],
    ids=["the decomposition call's", "a later call's", "a session's"],
)
def test_the_baseline_s_limits_are_read_wherever_a_call_or_a_session_of_the_run_left_them(
    tmp_path: Path, where: Path
) -> None:
    # Another call's limits at the decomposition's own place, unless ``where`` is that place.
    _write(tmp_path / "decomposition" / "config" / "policy-limits.json", AFTER)
    _write(tmp_path / where / "policy-limits.json", BEFORE)
    assert limits_with(tmp_path, _digest(BEFORE)) == json.loads(BEFORE)
    assert limits_with(tmp_path, _digest(b"{}")) is None


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


def _refused(tmp_path: Path, words: str, answer: str = "yes", **given: str) -> None:
    """The resolution is refused as a run-state error in ``words``, and nothing is written."""
    log = tmp_path / "events.jsonl"
    before = log.read_bytes()
    got = outcome_of(lambda: _resolve(tmp_path, answer, **given))
    assert isinstance(got, RunStateError), (answer, given, got)
    assert words in str(got), got
    assert log.read_bytes() == before, (answer, given)


def test_a_person_s_resolution_is_recorded_and_the_resume_accepts_the_run(tmp_path: Path) -> None:
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed, 2: removed})
    assert _drive(rig) == "halted"
    early = outcome_of(lambda: _drive(rig, resume=True))
    assert isinstance(early, RunStateError), early
    assert "a person resolves that before any resume" in str(early)
    resolved, shown = _resolve(tmp_path)
    assert '- "restrictions"."enforce_web_search_mcp_isolation"."allowed": false' in shown
    changed = f"the policy limits changed from {_digest(BEFORE)} to {_digest(removed)}"
    assert f"incident: {changed}" in shown
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
    assert outcome_of(lambda: _drive(rig, resume=True)) == "done"
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
    for answer, given, words in (
        ("no", {}, "not confirmed"),
        ("", {}, "not confirmed"),
        ("yes", {"by": RULE}, "is the rule's"),
        ("yes", {"by": " "}, "by name and with a reason"),
        ("yes", {"reason": " "}, "by name and with a reason"),
    ):
        _refused(tmp_path, words, answer, **given)


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


def test_a_change_beside_other_managed_settings_is_not_resolved_here(tmp_path: Path) -> None:
    _new("physgate.orchestrator.incident", "record_resolution")
    # Remote settings delivered and other limits, in one session: the incident is the drift's.
    rig = _rig(tmp_path, {1: AFTER}, drift={1: "remote managed settings were delivered"})
    assert _drive(rig) == "halted"
    _refused(tmp_path, "other managed settings changed")
    # And a resolution written beside it anyway is refused by the replay.
    events = read_events(tmp_path / "events.jsonl")
    resolved_type = _new("physgate.orchestrator.events", "IncidentResolved")
    last = events[-1]
    forged = resolved_type(
        seq=last.seq + 1,
        ts=last.ts,
        run_id=last.run_id,
        gate_mode=last.gate_mode,
        subtask_id="s1",
        session_id="sess-1",
        by="yasin",
        reason="forged",
        rule=False,
        old_sha256=_digest(BEFORE),
        new_sha256=_digest(AFTER),
        changes=(),
    )
    with pytest.raises(CorruptEventLogError):
        replay([*events, forged])


def test_a_change_beside_another_incident_of_the_session_is_not_resolved_here(
    tmp_path: Path,
) -> None:
    # The session's end shows held-out material too: two incidents, the change's the last.
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed}, held_out={1: "CANARY-held-out-0000"})
    assert _drive(rig) == "halted"
    causes = [i["cause"] for i in _lines(tmp_path, "incident")]
    assert causes == ["held_out_read", "managed_settings_changed"]
    _refused(tmp_path, "only a run halted on one managed-settings incident")


@pytest.mark.parametrize("which", RULED_FILES)
def test_a_resolution_is_refused_where_a_file_the_record_names_is_not_on_disk_as_named(
    tmp_path: Path, which: str
) -> None:
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed})
    assert _drive(rig) == "halted"
    where, _ = RULED_FILES[which]
    _write(tmp_path / where, (tmp_path / where).read_bytes() + b" ")
    _refused(tmp_path, "not on disk as it names them")


#: A restriction added as the rule allows, under a key that rewrites the terminal's line.
SPOOFED = json.dumps(
    {
        "restrictions": {
            **json.loads(BEFORE)["restrictions"],
            "allow_x\u001b[2K\rnothing changed": {"allowed": False},
        }
    }
).encode()


def test_a_key_that_does_not_print_as_itself_is_neither_ruled_on_nor_shown(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, {1: SPOOFED})
    assert outcome_of(lambda: _drive(rig)) == "halted"
    assert _lines(tmp_path, "incident_resolved") == []
    _refused(tmp_path, "cannot be shown as written")
    entry = _new("physgate.orchestrator.managed", "PolicyEntry")
    for key in ("a\x1bb", "rtl\u202eoverride", "line\nbreak"):
        with pytest.raises(ValueError, match="does not print as itself"):
            entry.model_validate_json(
                json.dumps(
                    {"path": ["restrictions", key, "allowed"], "before": None, "after": "false"}
                )
            )
    # A key past ASCII prints escaped, so the line is what the file holds.
    diff_lines = _new("physgate.orchestrator.managed", "diff_lines")
    policy_diff = _new("physgate.orchestrator.managed", "policy_diff")
    assert diff_lines(*policy_diff({}, {"caf\u00e9": True})) == ['+ "caf\\u00e9": true']


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
    # The incident's words rewritten to name other limits, and a resolution naming those: the
    # session's end is what the change is held to. The record up to the true resolution replays.
    replay(events[: at + 1])
    other = _digest(b"{}")
    words = events[found].model_copy(
        update={"detail": f"the policy limits changed from {_digest(BEFORE)} to {other}"}
    )
    named = resolved.model_copy(update={"new_sha256": other})
    with pytest.raises(CorruptEventLogError):
        replay([*events[:found], words, *events[found + 1 : at], named])


def test_a_second_decomposition_line_never_moves_the_baseline_back(tmp_path: Path) -> None:
    removed = NOT_THE_RULE["a restriction removed"]
    rig = _rig(tmp_path, {1: removed, 2: removed})
    assert _drive(rig) == "halted"
    _resolve(tmp_path)
    assert _drive(rig, resume=True) == "done"
    events = read_events(tmp_path / "events.jsonl")
    decomposed = next(e for e in events if e.kind == "decomposed")
    resumed = next(i for i, e in enumerate(events) if isinstance(e, Resumed))
    # The loop writes one decomposition line. One more, after the resolution moved the baseline,
    # is refused, or leaves the baseline the resolution's: never the decomposition call's again.
    got = outcome_of(lambda: replay([*events[: resumed + 1], decomposed]))
    assert isinstance(got, CorruptEventLogError) or got.policy_baseline == _digest(removed), got


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
    # Naming other limits than the session's end, or another session than the one that ends.
    for forged in (
        events[at].model_copy(update={"new_sha256": _digest(b"{}")}),
        events[at].model_copy(update={"session_id": "sess-2"}),
    ):
        with pytest.raises(CorruptEventLogError):
            replay([*events[:at], forged, *events[at + 1 :]])
    # The rule's line cannot name a change that is not its rule's.
    resolved_type = _new("physgate.orchestrator.events", "IncidentResolved")
    loosened = events[at].model_dump(mode="json") | {
        "changes": [{"path": list(ADDED), "before": None, "after": "true"}]
    }
    with pytest.raises(ValueError, match="only a change that adds restrictions"):
        resolved_type.model_validate_json(json.dumps(loosened))


def test_the_replay_refuses_the_rule_s_line_once_the_session_s_end_showed_an_incident(
    tmp_path: Path,
) -> None:
    # The session that received the rule's change had remote settings delivered too: its
    # incident is on the record before its end line, and the rule takes no running session's.
    rig = _rig(tmp_path, {1: AFTER}, drift={1: "remote managed settings were delivered"})
    assert _drive(rig) == "halted"
    events = read_events(tmp_path / "events.jsonl")
    found = next(i for i, e in enumerate(events) if isinstance(e, Incident))
    ended = next(i for i, e in enumerate(events) if isinstance(e, SessionEnded))
    assert found < ended
    last = events[found]
    ruled = IncidentResolved(
        seq=last.seq,
        ts=last.ts,
        run_id=last.run_id,
        gate_mode=last.gate_mode,
        subtask_id="s1",
        session_id="sess-1",
        by=RULE,
        reason=RULE_REASON,
        rule=True,
        old_sha256=_digest(BEFORE),
        new_sha256=_digest(AFTER),
        changes=(PolicyEntry(path=ADDED, before=None, after="false"),),
    )
    replay(events)
    with pytest.raises(CorruptEventLogError):
        replay([*events[:ended], ruled, *events[ended:]])
