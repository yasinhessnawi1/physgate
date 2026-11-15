"""Whether a paired reviewer may compact its conversation is a flag, required and recorded.

``review_compaction`` is ``on`` or ``off`` (ARCH-060). A new run names it; it is never read from
the environment and has no default. A run recorded before the flag existed ran every reviewer
with compaction switched off, and reads as ``off``, with exactly the digest its first line
carries; so does every ``off`` run, whose recorded form and first line leave it out. An ``on``
run records it in both. A resumed run is held to the value it was recorded with.

Every name the flag adds is looked up when a row asks for it, so a row fails on its assertion,
not at collection, in a tree without the flag.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

from design_review_rig import outcome_of
from orch_helpers import make_config, ticking_clock

import physgate.flags as flags
from physgate.orchestrator.events import EventLog, RunStarted, read_events
from physgate.orchestrator.run_config import RunConfig, load_run_config, write_run_config


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**fields))


def test_the_register_names_the_flag_with_on_and_off() -> None:
    flag = getattr(flags, "REVIEW_COMPACTION", None)
    assert flag is not None, "the register has no review_compaction flag"
    assert flag.name == "review_compaction"
    assert flag.values == ("on", "off")
    assert flag.architecture == "ARCH-060"
    position = flags.REGISTER.index(flag)
    assert flags.REGISTER[position - 1] is flags.PARTS_ON_HAND
    assert typing.get_args(getattr(flags, "ReviewCompaction", None)) == flag.values
    assert "before the switch existed" in flag.meanings["off"]


def test_the_flag_is_a_required_field_recorded_only_when_on(tmp_path: Path) -> None:
    field = RunConfig.model_fields.get("review_compaction")
    assert field is not None, "the run's configuration has no review_compaction"
    assert field.is_required()
    on = _config(review_compaction="on")
    off = _config(review_compaction="off")
    assert isinstance(on, RunConfig), on
    assert isinstance(off, RunConfig), off
    assert b'"review_compaction":"on"' in on.canonical_bytes()
    assert b"review_compaction" not in off.canonical_bytes()
    path = tmp_path / "on.json"
    write_run_config(path, on)
    assert load_run_config(path).review_compaction == "on"


def test_a_run_recorded_before_the_flag_reads_as_off(tmp_path: Path) -> None:
    config = _config(review_compaction="off")
    assert isinstance(config, RunConfig), config
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert "review_compaction" not in json.loads(path.read_bytes())  # as a run before the flag
    loaded = load_run_config(path)
    assert loaded.review_compaction == "off"
    assert loaded.sha256() == config.sha256()


def test_any_other_value_is_refused() -> None:
    assert "review_compaction" in RunConfig.model_fields
    for value in ("auto", True, "", None):
        refused = _config(review_compaction=value)
        assert not isinstance(refused, RunConfig), value
        assert "review_compaction" in str(refused), refused


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
    on = _first_line(tmp_path / "on", review_compaction="on")
    assert isinstance(on, RunStarted), on
    assert getattr(on, "review_compaction", None) == "on"
    assert b'"review_compaction":"on"' in (tmp_path / "on" / "events.jsonl").read_bytes()
    off = _first_line(tmp_path / "off")
    assert isinstance(off, RunStarted), off
    assert b"review_compaction" not in (tmp_path / "off" / "events.jsonl").read_bytes()
    for n, value in enumerate(("off", True, "auto")):
        refused = _first_line(tmp_path / str(n), review_compaction=value)
        assert not isinstance(refused, RunStarted), value
        assert "review_compaction" in str(refused), refused


def test_a_run_s_record_writes_the_flag_on_its_first_line(tmp_path: Path) -> None:
    from loop_fakes import Rig, plan

    for name, value, said in (("on", "on", "on"), ("off", "off", None)):
        run_dir = tmp_path / name
        run_dir.mkdir()
        loop = outcome_of(
            lambda run_dir=run_dir, value=value: Rig(
                run_dir, config_overrides={"review_compaction": value}
            ).open()
        )
        assert not isinstance(loop, Exception), loop
        loop.record.start(plan("s1"))
        loop.close()
        first = read_events(run_dir / "events.jsonl")[0]
        assert isinstance(first, RunStarted)
        assert getattr(first, "review_compaction", "absent") == said


def test_a_resumed_run_is_held_to_the_value_it_was_recorded_with(tmp_path: Path) -> None:
    from loop_fakes import Rig, plan

    assert isinstance(_config(review_compaction="on"), RunConfig)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    loop = Rig(run_dir, config_overrides={"review_compaction": "off"}).open()
    loop.record.start(plan("s1"))
    loop.close()
    reopened = outcome_of(
        lambda: Rig(run_dir, config_overrides={"review_compaction": "on"}).open()
    )
    assert isinstance(reopened, Exception), "a run resumed under another review_compaction"


def test_the_reviewers_are_set_up_with_the_run_s_value() -> None:
    from dataclasses import fields

    from physgate.reviewers.claude import ReviewerSetup

    assert "review_compaction" in {f.name for f in fields(ReviewerSetup)}
    for value in ("on", "off"):
        config = _config(review_compaction=value)
        assert isinstance(config, RunConfig), config
        setup = ReviewerSetup.of_run(
            config,
            review_root=Path("/r"),
            repo=Path("/repo"),
            install_bin=Path("/i/bin/physgate"),
            binary="claude",
            base_url=None,
            credential=None,  # type: ignore[arg-type]
            library=Path("/lib"),
        )
        assert getattr(setup, "review_compaction", None) == value


def test_both_example_parameters_name_the_flag_on() -> None:
    from physgate.orchestrator.cli import EXAMPLES

    paths = sorted(EXAMPLES.glob("params.*.json"))
    assert len(paths) == 2
    for path in paths:
        assert json.loads(path.read_text()).get("review_compaction") == "on", path.name


def test_the_comparisons_know_the_flag() -> None:
    from physgate.evaluation.observe.compare import REPORTED
    from physgate.evaluation.per_role.arms.compare import RUN_FIELDS

    assert "review_compaction" in REPORTED
    assert RUN_FIELDS.get("review_compaction") == "harness"
