"""A measured run on a version the register marks exposed, or on no version it can tell, is refused.

A run's version is the one whose tasks hold its brief, found by its digest as a baseline round
finds a harness run's task. A run withholds every version's protected tiers, older ones too, so
a version it only withholds is not one it is on: an exposed version refuses a run on it, never
a run on a later version. The register is read as freshly scanned: a ``held_out_read`` incident
in a run under the role's run roots, a raw record that saw a canary, or a hand mark, recorded
or not. A check never writes.

For a reportable or ablation run that names held-out roots, in order: an entry in no tier-set
store; a protected tier no longer the bytes the run recorded; a tier in no version; a brief in
no version, or in several; the version exposed; a run directory beneath none of the run roots;
the pre-run scan of the version's two protected tiers. A run that is not measured is not held
to it. Each refusal says a digest's prefix at most, never a task.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from exposure_fixtures import (
    StandInStore,
    api,
    config,
    harness_run,
    incident_in,
    refusal,
    second_version,
    stand_in_store,
    with_run_root,
)

from physgate.evaluation.tiers.heldout import tier_digest
from physgate.evaluation.tiers.store import withheld_root

EXPOSURE = "physgate.evaluation.tiers.exposure"


def _refused_because(call: Callable[[], object]) -> str:
    """The counted reason ``call`` is refused with; any other error fails the row."""
    error = api(f"{EXPOSURE}.ExposureError")
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - which error it is, is what is asserted
        assert isinstance(exc, error), f"refused by {type(exc).__name__}, not with a reason"
        return str(exc.context.get("refused_because"))
    pytest.fail("it was not refused")


def _reason(why: str | None, reason: str) -> None:
    assert why is not None, f"the run was not refused; it should be ({reason})"
    assert f"({reason})" in why, f"refused for another reason than {reason}: {why}"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "s")


def test_a_run_on_a_version_nothing_has_seen_starts_and_goes_on(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    assert refusal(run, runs / "r1", new_run=True) is None
    assert refusal(run, runs / "r1", new_run=False) is None


@pytest.mark.parametrize("new_run", [True, False], ids=["at its start", "at a resume"])
def test_an_incident_in_a_run_on_the_version_refuses_every_later_run_on_it(
    tmp_path: Path, made: StandInStore, new_run: bool
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    earlier = harness_run(runs, made.tasks["visible"][1], made, ended=False)
    incident_in(earlier)
    run = config(made.tasks["visible"][0], made)
    why = refusal(run, runs / "r2", new_run=new_run)
    _reason(why, "version_exposed")
    assert made.version[:8] in str(why)
    assert made.version not in str(why), "the refusal says more than a digest's prefix"
    for tier in made.tasks.values():
        for task in tier:
            assert task.id not in str(why), "the refusal names a task"


def test_a_run_that_exposed_its_version_cannot_resume_as_measured(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    task = made.tasks["visible"][0]
    halted = harness_run(runs, task, made, ended=False)
    incident_in(halted)
    _reason(refusal(config(task, made), halted, new_run=False), "version_exposed")


@pytest.mark.parametrize("seen", [True, "unrecorded", None, False])
def test_a_raw_record_that_saw_a_canary_marks_the_version_and_one_that_did_not_does_not(
    tmp_path: Path, made: StandInStore, seen: object
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    trial = withheld_root(made.store, "control") / "baseline" / "round-1" / "t1" / "harness"
    trial.mkdir(parents=True)
    run = config(made.tasks["visible"][0], made)
    record = {"held_out_seen": seen, "held_out_sha256": list(run.held_out_sha256)}
    if seen == "unrecorded":
        record.pop("held_out_seen")
    if seen is None:
        # Nobody looked: nothing on a visible task, which has no canary to show (an unchecked
        # protected task is an exposure of unknown extent, held by its own row).
        brief = made.tasks["visible"][0].brief.encode()
        record["pins"] = {"brief_sha256": hashlib.sha256(brief).hexdigest()}
    (trial / "raw.json").write_text(json.dumps(record))
    why = refusal(run, runs / "r1")
    if seen is False or seen is None:
        assert why is None, f"a raw record that saw nothing marked the version: {why}"
    else:
        _reason(why, "version_exposed")


def test_a_raw_record_under_the_run_roots_marks_the_version_too(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    (runs / "round" / "t1").mkdir(parents=True)
    record = {"held_out_seen": True, "held_out_sha256": list(run.held_out_sha256)}
    (runs / "round" / "t1" / "raw.json").write_text(json.dumps(record))
    _reason(refusal(run, runs / "r1"), "version_exposed")


def test_a_hand_mark_refuses_a_run_on_the_version(tmp_path: Path, made: StandInStore) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    mark = api(f"{EXPOSURE}.mark_exposed")
    mark(made.store, "control", made.version, by="a person", reason="opened the tier by hand")
    run = config(made.tasks["held_out"][0], made)
    _reason(refusal(run, runs / "r1"), "version_exposed")


def test_an_exposed_version_does_not_refuse_a_run_on_a_later_one_that_withholds_it(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    later = second_version(made)
    mark = api(f"{EXPOSURE}.mark_exposed")
    mark(made.store, "control", made.version, by="a person", reason="opened the tier by hand")
    on_later = config(later.tasks["visible"][0], later)
    assert made.store.as_posix() + f"/control/{made.version}/held_out" in on_later.held_out
    assert refusal(on_later, runs / "r1") is None, "a run on the later version was refused"
    on_exposed = config(made.tasks["visible"][0], later)
    _reason(refusal(on_exposed, runs / "r2"), "version_exposed")


def test_an_incident_in_a_run_on_the_later_version_marks_every_version_its_digests_name(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    later = second_version(made)
    incident_in(harness_run(runs, later.tasks["visible"][1], later, ended=False))
    exposed = api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    assert exposed == frozenset({made.version, later.version})


def test_an_incident_marks_only_the_versions_its_run_s_digests_name(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    later = second_version(made)
    task = later.tasks["visible"][1]
    only_later = [h for h in later.held_out if made.version not in h]
    run = config(
        task,
        later,
        held_out=only_later,
        held_out_sha256=[tier_digest(Path(h)) for h in only_later],
    )
    assert len(run.held_out) == len(later.held_out) - 2
    run_dir = harness_run(runs, task, later, ended=False)
    (run_dir / "run.json").write_text(run.model_dump_json())
    incident_in(run_dir)
    exposed = api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    assert exposed == frozenset({later.version})


def test_an_authoring_line_marks_nothing_exposed(tmp_path: Path, made: StandInStore) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    append = api(f"{EXPOSURE}._append")
    line = {
        "kind": "authoring",
        "version": made.version,
        "held_out": run.held_out_sha256[-1],
        "validation": run.held_out_sha256[-2],
        "key": "1" * 64,
    }
    append(withheld_root(made.store, "control"), "register", [line])
    assert refusal(run, runs / "r1") is None, "an author's read was taken for an exposure"


def test_a_second_scan_records_nothing_new(tmp_path: Path, made: StandInStore) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    scan = api(f"{EXPOSURE}.record_scan")
    assert scan(made.store, "control") == (1, 0)
    assert scan(made.store, "control") == (0, 1)
    lines = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert [(line.kind, line.source, line.version) for line in lines] == [
        ("exposure", "incident", made.version)
    ]


def test_a_recorded_exposure_holds_once_the_run_that_made_it_is_gone(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    earlier = harness_run(runs, made.tasks["visible"][1], made, ended=False)
    incident_in(earlier)
    api(f"{EXPOSURE}.record_scan")(made.store, "control")
    shutil.rmtree(earlier)
    _reason(refusal(config(made.tasks["visible"][0], made), runs / "r2"), "version_exposed")


@pytest.mark.parametrize(
    ("by", "reason"),
    [("", "opened the tier by hand"), ("a person", "opened"), ("a person", "  ")],
    ids=["no one", "one word", "no reason"],
)
def test_a_hand_mark_without_a_person_or_a_reason_is_refused(
    made: StandInStore, by: str, reason: str
) -> None:
    mark = api(f"{EXPOSURE}.mark_exposed")
    why = _refused_because(lambda: mark(made.store, "control", made.version, by=by, reason=reason))
    wanted = "hand_mark_names_no_one" if not by else "hand_mark_without_a_reason"
    assert why == wanted
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []


def test_a_hand_mark_on_a_version_the_role_does_not_have_is_refused(made: StandInStore) -> None:
    mark = api(f"{EXPOSURE}.mark_exposed")
    why = _refused_because(
        lambda: mark(made.store, "control", "e" * 64, by="a person", reason="opened it by hand")
    )
    assert why == "version_unknown"


def _two_marks(made: StandInStore) -> Path:
    mark = api(f"{EXPOSURE}.mark_exposed")
    for why in ("opened the tier by hand", "copied a task by mistake"):
        mark(made.store, "control", made.version, by="a person", reason=why)
    return withheld_root(made.store, "control")


@pytest.mark.parametrize(
    "cut",
    [
        "the last line",
        "every line",
        "the register",
        "the head",
        "a line rewritten",
        "the last line rewritten",
    ],
)
def test_a_shortened_or_rewritten_register_refuses_rather_than_reads_as_nothing_exposed(
    tmp_path: Path, made: StandInStore, cut: str
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    withheld = _two_marks(made)
    register, head = withheld / "register.jsonl", withheld / "register.head"
    lines = register.read_bytes().splitlines(keepends=True)
    if cut == "the last line":
        register.write_bytes(lines[0])
    elif cut == "every line":
        register.write_bytes(b"")
    elif cut == "the register":
        register.unlink()
    elif cut == "the head":
        head.unlink()
    elif cut == "a line rewritten":
        first = json.loads(lines[0])
        first["reason"] = "nothing to see here"
        register.write_bytes(json.dumps(first).encode() + b"\n" + lines[1])
    else:
        last = json.loads(lines[1])
        last["reason"] = "nothing to see here"
        register.write_bytes(lines[0] + json.dumps(last).encode() + b"\n")
    _reason(refusal(config(made.tasks["visible"][0], made), runs / "r1"), "register_unreadable")


def test_marks_are_appended_in_their_order_and_read_back_whole(made: StandInStore) -> None:
    try:
        _two_marks(made)
        lines = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    except Exception as exc:  # noqa: BLE001 - two marks that do not read back are the failure
        pytest.fail(f"two marks do not read back whole: {exc!r}")
    assert [(line.n, line.reason) for line in lines] == [
        (0, "opened the tier by hand"),
        (1, "copied a task by mistake"),
    ]


@pytest.mark.parametrize("cut", ["the last line", "every line"])
def test_reading_a_shortened_register_is_refused_with_its_reason(
    made: StandInStore, cut: str
) -> None:
    register = _two_marks(made) / "register.jsonl"
    lines = register.read_bytes().splitlines(keepends=True)
    register.write_bytes(lines[0] if cut == "the last line" else b"")
    why = _refused_because(lambda: api(f"{EXPOSURE}.register_lines")(made.store, "control"))
    assert why == "register_unreadable"


def test_a_raw_record_that_names_no_digest_marks_every_version_of_the_role(
    made: StandInStore,
) -> None:
    later = second_version(made)
    trial = withheld_root(made.store, "control") / "baseline" / "round-1" / "t1" / "harness"
    trial.mkdir(parents=True)
    (trial / "raw.json").write_text(json.dumps({"held_out_seen": True}))
    exposed = api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    assert exposed == frozenset({made.version, later.version})


def test_a_brief_in_two_versions_is_refused_as_on_no_one_version(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    later = second_version(made, brief="Stabilise plant number {i}. Answer here.")
    on_both = config(made.tasks["visible"][0], later)
    _reason(refusal(on_both, runs / "r1"), "brief_in_several_versions")


def test_a_measured_run_with_no_held_out_roots_is_not_held_to_it(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    task = made.tasks["visible"][0]
    run = config(task, made, held_out=[], held_out_sha256=[], held_out_canaries=[])
    assert refusal(run, runs / "r1") is None


def test_a_run_that_is_not_measured_is_not_held_to_it(tmp_path: Path, made: StandInStore) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    _two_marks(made)
    outside = tmp_path / "elsewhere" / "held_out"
    outside.mkdir(parents=True)
    task = made.tasks["visible"][0]
    product = config(
        task,
        made,
        reportable=False,
        brief_sha256="f" * 64,
        held_out=[*config(task, made).held_out, str(outside)],
        held_out_sha256=[*config(task, made).held_out_sha256, "0" * 64],
    )
    assert refusal(product, runs / "r1") is None
    assert refusal(product, None) is None


def test_a_measured_run_with_a_held_out_root_in_no_store_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    outside = tmp_path / "elsewhere" / "held_out"
    outside.mkdir(parents=True)
    task = made.tasks["visible"][0]
    base = config(task, made)
    run = config(
        task,
        made,
        held_out=[*base.held_out, str(outside)],
        held_out_sha256=[*base.held_out_sha256, "0" * 64],
    )
    _reason(refusal(run, runs / "r1"), "held_out_outside_a_store")


def test_an_ablation_run_is_held_to_it_like_a_reportable_one(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    task = made.tasks["visible"][0]
    run = config(task, made, reportable=False, ablation=True, brief_sha256="f" * 64)
    _reason(refusal(run, runs / "r1"), "brief_in_no_version")


def test_a_measured_run_whose_brief_is_in_no_version_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made, brief_sha256="f" * 64)
    _reason(refusal(run, runs / "r1"), "brief_in_no_version")


@pytest.mark.parametrize("tier", ["visible", "held_out"])
def test_a_measured_run_given_a_task_s_brief_without_its_values_is_refused_by_its_own_name(
    tmp_path: Path, made: StandInStore, tier: str
) -> None:
    """A run given the brief alone was given less than the task, and is no run of it."""
    runs = with_run_root(made, tmp_path / "runs")
    task = made.tasks[tier][0]
    alone = hashlib.sha256(task.brief.encode()).hexdigest()
    run = config(task, made, brief_sha256=alone)
    _reason(refusal(run, runs / "r1", new_run=True), "given_the_brief_alone")


@pytest.mark.parametrize("new_run", [True, False], ids=["at its start", "at a resume"])
def test_a_protected_tier_changed_since_the_run_recorded_it_is_refused(
    tmp_path: Path, made: StandInStore, new_run: bool
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    tier = made.store / "control" / made.version / "held_out"
    task = sorted(p for p in tier.iterdir() if p.is_dir())[0] / "task.json"
    task.write_bytes(task.read_bytes() + b" ")
    why = refusal(run, runs / "r1", new_run=new_run)
    _reason(why, "tier_changed")
    assert run.held_out_sha256[-1][:8] in str(why)


def test_a_protected_tier_in_no_version_is_refused(tmp_path: Path, made: StandInStore) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    version = made.store / "control" / made.version
    other = made.store / "control" / ("e" * 64)
    for tier in ("visible", "validation", "held_out"):
        shutil.copytree(version / tier, other / tier)
    task = made.tasks["visible"][0]
    base = config(task, made)
    run = config(
        task,
        made,
        held_out=[*base.held_out, str(other / "held_out")],
        held_out_sha256=[*base.held_out_sha256, tier_digest(other / "held_out")],
    )
    _reason(refusal(run, runs / "r1"), "version_unknown")


@pytest.mark.parametrize("where", ["outside every run root", "not given"])
def test_a_measured_run_whose_directory_is_beneath_no_run_root_is_refused(
    tmp_path: Path, made: StandInStore, where: str
) -> None:
    with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made)
    run_dir = tmp_path / "elsewhere" / "r1" if where != "not given" else None
    _reason(refusal(run, run_dir), "run_outside_run_roots")


def test_a_store_with_no_run_roots_refuses_every_measured_run_on_it(
    tmp_path: Path, made: StandInStore
) -> None:
    run = config(made.tasks["visible"][0], made)
    _reason(refusal(run, tmp_path / "runs" / "r1"), "run_outside_run_roots")


def test_a_run_that_does_not_look_for_its_version_s_canaries_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run = config(made.tasks["visible"][0], made, held_out_canaries=list(made.canaries[1:]))
    _reason(refusal(run, runs / "r1"), "canary_not_looked_for")


def test_the_pre_run_scan_of_the_version_s_tiers_refuses_a_link_into_one(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    run_dir = runs / "r1"
    run_dir.mkdir()
    (run_dir / "peek").symlink_to(made.store / "control" / made.version / "validation")
    why = refusal(config(made.tasks["visible"][0], made), run_dir, new_run=False)
    _reason(why, "tier_scan_refused")
    for tier in made.tasks.values():
        for task in tier:
            assert task.id not in str(why), "the refusal names a task"
