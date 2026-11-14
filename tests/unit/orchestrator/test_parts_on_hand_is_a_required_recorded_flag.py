"""Whether a run asks which parts a person has or can make is a flag, required and recorded.

``parts_on_hand`` is ``on`` or ``off`` (ARCH-122). A new run names it; it is never read from the
environment and has no default. A run recorded before the flag existed reads as ``off``, with
exactly the digest its first line carries, and so does every ``off`` run, whose recorded form
and first line leave it out; an ``on`` run records it in both.

A run that asks holds its dispatch until a person has decided every part, so it is a run that
acts on decisions: ``on`` is refused with ``queue_decisions: record``, and with it, by the rule
every acting run is held to, where the OS layer is absent. A reportable run records decisions
and acts on none, so no measured run asks.

Every name the flag adds is looked up when a row asks for it, so a row fails on its assertion,
not at collection, in a tree without the flag.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, make_config, ticking_clock

import physgate.flags as flags
from physgate.evaluation.requirements import REQUIREMENTS
from physgate.orchestrator.events import EventLog, RunStarted, read_events
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import RunConfig, load_run_config, write_run_config
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
#: A run that acts, where the OS layer runs: the only run that may ask.
ACTING: dict[str, Any] = {"queue_decisions": "act", "os_layer": PRESENT}
#: What the refusal of ``on`` beside ``record`` says.
NEEDS_ACT = "parts_on_hand: on"


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**fields))


def test_the_register_names_the_flag_with_on_and_off() -> None:
    flag = getattr(flags, "PARTS_ON_HAND", None)
    assert flag is not None, "the register has no parts_on_hand flag"
    assert flag.name == "parts_on_hand"
    assert flag.values == ("on", "off")
    assert flag.architecture == "ARCH-122"
    position = flags.REGISTER.index(flag)
    assert flags.REGISTER[position - 1] is flags.DESIGN_REVIEW
    assert typing.get_args(getattr(flags, "PartsOnHand", None)) == flag.values
    # Each meaning says what a reader of a run's record needs: what is asked, and of whom.
    assert "have" in flag.meanings["on"] and "queue_decisions: act" in flag.meanings["on"]
    assert "before the switch existed" in flag.meanings["off"]


def test_the_flag_is_a_required_field_recorded_only_when_on(tmp_path: Path) -> None:
    field = RunConfig.model_fields.get("parts_on_hand")
    assert field is not None, "the run's configuration has no parts_on_hand"
    assert field.is_required()
    on = _config(parts_on_hand="on", **ACTING)
    off = _config(parts_on_hand="off", **ACTING)
    assert isinstance(on, RunConfig), on
    assert isinstance(off, RunConfig), off
    assert b'"parts_on_hand":"on"' in on.canonical_bytes()
    assert b"parts_on_hand" not in off.canonical_bytes()
    assert on.sha256() != off.sha256()
    path = tmp_path / "on.json"
    write_run_config(path, on)
    assert load_run_config(path).parts_on_hand == "on"


def test_a_run_recorded_before_the_flag_reads_as_off_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    config = _config(parts_on_hand="off")
    assert isinstance(config, RunConfig), config
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert "parts_on_hand" not in json.loads(path.read_bytes())  # as a run before the flag wrote
    loaded = outcome_of(lambda: load_run_config(path))
    assert isinstance(loaded, RunConfig), loaded
    assert loaded.parts_on_hand == "off"
    assert loaded.sha256() == config.sha256()
    # The digest of this configuration as recorded before the flag existed.
    plain = make_config(harness=CLEAN_HARNESS)
    assert plain.sha256() == "c1f3ab6192f60f8c1a81549b0386a23895b0e3984fe596557e3d7583befdb6d3"


def test_a_value_the_register_does_not_name_is_refused() -> None:
    assert isinstance(_config(parts_on_hand="off"), RunConfig)
    for value in ("ask", True, None, "ON"):
        refused = _config(parts_on_hand=value, **ACTING)
        assert not isinstance(refused, RunConfig), value
        assert "parts_on_hand" in str(refused), refused


# --- asking needs a run that acts ------------------------------------------------------------


def test_on_is_refused_in_a_run_that_only_records_decisions() -> None:
    refused = _config(parts_on_hand="on", queue_decisions="record", os_layer=PRESENT)
    assert not isinstance(refused, RunConfig), "a run that records only may not ask"
    assert NEEDS_ACT in str(refused) and "queue_decisions: act" in str(refused), refused
    # The same run asks nothing, or acts: each is a configuration.
    assert isinstance(_config(parts_on_hand="off", queue_decisions="record"), RunConfig)
    assert isinstance(_config(parts_on_hand="on", **ACTING), RunConfig)


def test_on_is_refused_where_the_os_layer_is_absent_whatever_the_run_allows() -> None:
    absent = Absent(reason="no sandbox on this platform")
    for layer in (absent, None):
        for allowance in ("refuse", "allow"):
            refused = _config(
                parts_on_hand="on",
                queue_decisions="act",
                os_layer=layer,
                os_layer_absent=allowance,
            )
            assert not isinstance(refused, RunConfig), (layer, allowance)
            assert "only inside the OS layer" in str(refused), refused
    # With two faults at once the refusal names the one a person fixes first: the run must act.
    both = _config(parts_on_hand="on", queue_decisions="record", os_layer=absent)
    assert NEEDS_ACT in str(both), both
    # Off, the same development run without the layer is as it was.
    assert isinstance(
        _config(parts_on_hand="off", os_layer=absent, os_layer_absent="allow"), RunConfig
    )


def _refusals(config: RunConfig) -> list[str]:
    facts = RunFacts(config=config, os_layer=PRESENT, shell_sessions=True, new_run=True)
    return [why for requirement in REQUIREMENTS if (why := requirement(facts)) is not None]


def test_no_reportable_run_asks() -> None:
    pinned = make_config().models.model_copy(
        update={"reviewers": {"electrical": "claude-opus-5-5", "design": "claude-opus-5-5"}}
    )
    measured = {"reportable": True, "harness": CLEAN_HARNESS, "design_review": "observe"}
    asking = _config(parts_on_hand="on", models=pinned, **measured, **ACTING)
    assert isinstance(asking, RunConfig), asking
    assert any("queue_decisions: record" in why for why in _refusals(asking))
    quiet = _config(parts_on_hand="off", models=pinned, **measured)
    assert isinstance(quiet, RunConfig), quiet
    assert _refusals(quiet) == []


# --- the run's first line --------------------------------------------------------------------


def _first_line(tmp_path: Path, **said: Any) -> Any:  # noqa: ANN401 - the line, or the refusal
    path = tmp_path / "events.jsonl"

    def write() -> RunStarted:
        log = EventLog(path, run_id="run-1", gate_mode="on", clock=ticking_clock())
        try:
            log.emit(RunStarted, config_sha256="c" * 64, **said)
        finally:
            log.close()
        first = read_events(path)[0]
        assert isinstance(first, RunStarted)
        return first

    return outcome_of(write)


def test_the_first_line_names_the_flag_only_when_on(tmp_path: Path) -> None:
    on = _first_line(tmp_path / "on", parts_on_hand="on", queue_decisions="act")
    assert isinstance(on, RunStarted), on
    assert getattr(on, "parts_on_hand", None) == "on"
    assert b'"parts_on_hand":"on"' in (tmp_path / "on" / "events.jsonl").read_bytes()
    off = _first_line(tmp_path / "off")
    assert isinstance(off, RunStarted), off
    raw = (tmp_path / "off" / "events.jsonl").read_bytes()
    assert b"parts_on_hand" not in raw
    # The line of a run before the flag, byte for byte.
    assert raw == (
        b'{"seq":0,"ts":"2026-09-26T12:00:00.000000Z","run_id":"run-1","gate_mode":"on",'
        b'"kind":"run_started","config_sha256":"' + b"c" * 64 + b'","escalation_backend":null}\n'
    )


def test_the_first_line_says_on_or_nothing(tmp_path: Path) -> None:
    for n, value in enumerate(("off", True, "ask")):
        refused = _first_line(tmp_path / str(n), parts_on_hand=value)
        assert not isinstance(refused, RunStarted), value
        assert "parts_on_hand" in str(refused), refused


def test_a_run_s_record_writes_the_flag_on_its_first_line(tmp_path: Path) -> None:
    from loop_fakes import Rig, plan

    def opened(run_dir: Path, overrides: dict[str, Any]) -> Any:  # noqa: ANN401 - or why not
        return outcome_of(lambda: Rig(run_dir, config_overrides=overrides).open())

    for name, overrides, said in (
        ("on", {"parts_on_hand": "on", **ACTING}, "on"),
        ("off", {"parts_on_hand": "off", **ACTING}, None),
    ):
        run_dir = tmp_path / name
        run_dir.mkdir()
        loop = opened(run_dir, overrides)
        assert not isinstance(loop, Exception), loop
        loop.record.start(plan("s1"))
        loop.close()
        first = read_events(run_dir / "events.jsonl")[0]
        assert isinstance(first, RunStarted)
        assert getattr(first, "parts_on_hand", "absent") == said


def test_a_first_line_that_says_other_than_the_configuration_is_refused(tmp_path: Path) -> None:
    from loop_fakes import Rig, plan

    # Started as a run that asks nothing, then opened under a configuration that asks: replay
    # reads the switch from the first line alone, so the two must agree.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    loop = Rig(run_dir, config_overrides=ACTING).open()
    loop.record.start(plan("s1"))
    loop.close()
    recorded = json.loads((run_dir / "run.json").read_bytes())
    (run_dir / "run.json").write_text(
        json.dumps({**recorded, "parts_on_hand": "on"}, separators=(",", ":")) + "\n"
    )
    reopened = outcome_of(
        lambda: Rig(run_dir, config_overrides={"parts_on_hand": "on", **ACTING}).open()
    )
    assert isinstance(reopened, Exception), "a first line that names no parts list was taken"
    assert "first line" in str(reopened), reopened
    assert "parts_on_hand" in str(getattr(reopened, "context", {})), reopened


# --- what ships, and what a comparison reads -------------------------------------------------


def test_both_example_parameters_name_the_flag_and_are_configurations() -> None:
    from physgate.orchestrator.cli import EXAMPLES

    paths = sorted(EXAMPLES.glob("params.*.json"))
    assert len(paths) == 2
    for path in paths:
        params = json.loads(path.read_text())
        assert params.get("parts_on_hand") in ("on", "off"), path.name
        # An example that asks is an example that acts.
        assert params.get("parts_on_hand") == "off" or params["queue_decisions"] == "act"


def test_the_comparisons_know_the_flag() -> None:
    from physgate.evaluation.observe.compare import REPORTED
    from physgate.evaluation.per_role.arms.compare import RUN_FIELDS

    assert "parts_on_hand" in REPORTED
    assert RUN_FIELDS.get("parts_on_hand") == "harness"
