"""A module whose role owes a person's sign-off is complete only once a person signed (ARCH-130).

A control module owes a sign-off on its stability margin, a mechanical module one on its sizing.
Which roles owe one is a typed table in code, each row with its sources; the run's first line
names the table's version by its digest, written by code and never by a parameter, and replay
reads that version's rows back. A run whose first line names none, as every run recorded before
the table, owes nothing. The fifth precondition of completion holds for an owing module only
where the latest approve that acts on its sign-off items was given on the values its latest
item shows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sign_off_rig import CONTROL, ELECTRICAL, INTEG, finished

from physgate import roles
from physgate.gate.catalogue import kind_of
from physgate.orchestrator import completion, record
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.events import (
    CompletionDeclared,
    DiffChecked,
    Event,
    ModuleCompleted,
    RunStarted,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.replay import RunState, replay
from physgate.orchestrator.run_config import RunConfig
from physgate.orchestrator.sign_off import (
    CURRENT,
    CURRENT_SHA256,
    VERSIONS,
    RaisedSignOff,
    SignOffRule,
    SignOffRules,
    known_rules,
    rules_sha256,
)


def completions(events: list[Event]) -> list[str]:
    return [e.subtask_id for e in events if isinstance(e, ModuleCompleted)]


def completed(events: list[Event], module: str) -> ModuleCompleted:
    last = events[-1]
    return ModuleCompleted(
        seq=len(events),
        ts=last.ts,
        run_id=last.run_id,
        gate_mode=last.gate_mode,
        subtask_id=module,
        declared_by=INTEG,
        attempt=replay(events).subtasks[INTEG].attempts[-1].number,
    )


def with_first_line(events: list[Event], **fields: object) -> list[Event]:
    """``events`` with their first line's fields replaced, read back as the writer's bytes."""
    first = json.loads(events[0].model_dump_json())
    first.update(fields)
    lines = [json.dumps(first), *(e.model_dump_json() for e in events[1:])]
    return parse_events("\n".join(lines).encode() + b"\n", log="events.jsonl")


# --- the table -------------------------------------------------------------------------------


def test_control_owes_its_stability_margin_and_mechanical_its_sizing_and_no_other_role_owes() -> (
    None
):
    owed = {rule.role: rule.owes for rule in CURRENT.rules}
    assert owed == {"control": "stability_margin", "mechanical": "sizing"}
    # Each row is a role the register holds, and every other registered role owes nothing.
    assert set(owed) <= set(roles.ROLES)
    for name in set(roles.ROLES) - set(owed):
        assert CURRENT.rule_of(name) is None


def test_every_row_shows_catalogued_names_and_rests_on_sources_it_names() -> None:
    for rule in CURRENT.rules:
        # The names an item shows first are ones the gate's catalogue gives a kind, so a shown
        # quantity is one the gate reads; a module still owes whatever names it wrote.
        assert all(kind_of(name) is not None for name in rule.shown), rule.role
        assert any(source.startswith("ARCH-130") for source in rule.sources), rule.role
        assert any(f"knowledge/{rule.role}/standards.md" in s for s in rule.sources), rule.role
        assert all(check.strip() for check in rule.checks)
    with pytest.raises(ValueError, match="each name it shows once"):
        SignOffRule(
            role="control",
            owes="stability_margin",
            signs="stability margin",
            shown=("phase_margin", "phase_margin"),
            checks=("check",),
            sources=("ARCH-130",),
        )
    with pytest.raises(ValueError, match="one row at most"):
        SignOffRules(version=2, rules=(CURRENT.rules[0], CURRENT.rules[0]))


def test_a_version_is_named_by_the_digest_of_its_canonical_json_and_kept_by_it() -> None:
    canonical = json.dumps(
        CURRENT.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert CURRENT_SHA256 == rules_sha256(CURRENT) == hashlib.sha256(canonical.encode()).hexdigest()
    assert known_rules(CURRENT_SHA256) is CURRENT
    assert VERSIONS[CURRENT_SHA256] is CURRENT
    # Any change to a row is another version, named by another digest that no run has recorded.
    moved = CURRENT.model_copy(update={"rules": CURRENT.rules[:1]})
    assert rules_sha256(moved) != CURRENT_SHA256
    assert known_rules(rules_sha256(moved)) is None


# --- the record ------------------------------------------------------------------------------


@pytest.mark.parametrize("acts", [False, True])
def test_every_run_started_now_names_the_table_on_its_first_line(
    tmp_path: Path, acts: bool
) -> None:
    events = finished(tmp_path, acts=acts)
    first = events[0]
    assert isinstance(first, RunStarted)
    assert first.sign_offs == CURRENT_SHA256
    assert replay(events).sign_off_rules is CURRENT
    # No field of the run's configuration says whether a sign-off is owed: none can turn it off.
    assert not [name for name in RunConfig.model_fields if "sign_off" in name]


def test_a_first_line_naming_no_table_owes_nothing_and_keeps_its_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A run as one recorded before the table existed: its first line names none.
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)
    events = finished(tmp_path)
    first = events[0]
    assert isinstance(first, RunStarted)
    assert first.sign_offs is None
    assert "sign_offs" not in json.loads(first.model_dump_json())
    state = replay(events)
    assert state.sign_off_rules is None
    assert completions(events) == [CONTROL, ELECTRICAL]
    assert dict(open_preconditions(state, CONTROL)) == {}


def test_replay_refuses_a_first_line_naming_a_version_no_code_here_holds(tmp_path: Path) -> None:
    events = finished(tmp_path)
    with pytest.raises(CorruptEventLogError) as caught:
        replay(with_first_line(events, sign_offs="e" * 64))
    assert "a version of the sign-off rule table this code does not hold" in str(
        caught.value.context["reason"]
    )


# --- the precondition ------------------------------------------------------------------------


def test_the_registry_asks_the_sign_off_last() -> None:
    names = [p.name for p in completion.PRECONDITIONS]
    assert names == ["merged", "system_scope", "contract", "open_item", "sign_off"]


def test_a_control_module_that_merged_is_withheld_while_no_person_signed(tmp_path: Path) -> None:
    events = finished(tmp_path)
    state = replay(events)
    # Both merged; the electrical one owes no sign-off and is complete.
    assert {s: state.subtasks[s].status for s in (CONTROL, ELECTRICAL)} == {
        CONTROL: "done",
        ELECTRICAL: "done",
    }
    assert completions(events) == [ELECTRICAL]
    why = dict(open_preconditions(state, CONTROL))
    assert list(why) == ["sign_off"]
    assert "stability margin owes a person's sign-off" in why["sign_off"]
    assert open_preconditions(state, ELECTRICAL) == ()
    # Integration's first declaration named both, and the change check refused it for the control
    # module; the one that merged names the electrical module alone.
    (declared,) = [e for e in events if isinstance(e, CompletionDeclared)]
    assert declared.modules == (ELECTRICAL,)
    # A completion line written past it is refused.
    with pytest.raises(CorruptEventLogError) as caught:
        replay([*events, completed(events, CONTROL)])
    assert "is not a module the merged attempt declared complete" in str(
        caught.value.context["reason"]
    )


def test_a_module_that_merged_nothing_owes_no_sign_off_yet(tmp_path: Path) -> None:
    events = finished(tmp_path)
    # Before the control module's clean diff it has merged nothing: only ``merged`` is open.
    at = next(
        i for i, e in enumerate(events) if isinstance(e, DiffChecked) and e.subtask_id == CONTROL
    )
    before = replay(events[:at])
    assert "sign_off" not in dict(open_preconditions(before, CONTROL))
    after = replay(events[: at + 1])
    assert "sign_off" in dict(open_preconditions(after, CONTROL))


def raised(state: RunState, item_id: str, digest: str, module: str = CONTROL) -> None:
    """Put a sign-off item on ``state`` as the raise records one."""
    state.sign_offs[item_id] = RaisedSignOff(item_id=item_id, module=module, values_sha256=digest)


def test_it_holds_only_where_the_latest_approve_was_given_on_the_values_shown_now(
    tmp_path: Path,
) -> None:
    state = replay(finished(tmp_path))

    def why() -> str | None:
        return dict(open_preconditions(state, CONTROL)).get("sign_off")

    raised(state, "a", "1" * 64)
    assert "no approve that acts was given on the values queue item a shows" in str(why())
    state.signed.append("a")
    assert why() is None
    # The values moved: a new item shows them, and the approve of the old values stops counting.
    raised(state, "b", "2" * 64)
    assert "queue item b shows" in str(why())
    # Another module's sign-off is not this module's.
    raised(state, "x", "2" * 64, module=ELECTRICAL)
    state.signed.append("x")
    assert "queue item b shows" in str(why())
    state.signed.append("b")
    assert why() is None
    # The values came back to what was signed first, and the latest approve is of others.
    raised(state, "c", "1" * 64)
    assert "queue item c shows" in str(why())


def test_a_role_that_owes_none_is_never_held_by_it(tmp_path: Path) -> None:
    state = replay(finished(tmp_path))
    raised(state, "x", "3" * 64, module=ELECTRICAL)
    assert "sign_off" not in dict(open_preconditions(state, ELECTRICAL))
