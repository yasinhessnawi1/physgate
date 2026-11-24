"""The register holds when its files are removed, when an exposure comes late, and where runs hide.

- **Removed:** a version is never written without the role's two logs beside it, so once a role
  has a version, a register, a head or a withheld root that is gone refuses every reader and
  every writer; nothing reads it as a register with nothing exposed, and no writer starts a new
  one in its place. A log holding lines past its head (a write cut off between the two) is
  refused in words that say so. A reader holds the logs under the writers' lock, shared.
- **Late:** a baseline round re-reads the register at its start, so a version exposed after its
  harness runs started is refused; ``compare`` says in words when a run's version is exposed now.
- **Hidden:** nothing inside a run directory is entered or parsed, so a file a session planted in
  its worktree is never opened; a run made inside another run leaves the root not fully read,
  and so does a link to a directory, which is not followed: adding such a root is refused and
  the scan says so; a measured run made inside another run is refused; the bounds still hold.
- **Unchecked:** a raw record that looked for no canary on a validation or held-out task is an
  exposure of unknown extent, recorded and shown apart from a confirmed one.
- **Saved first:** a scan given roots reads them whatever the run-roots log holds; a registered
  root that is gone is said, never read as empty, and fails the scan.
- **Bounded:** a hand mark's name or reason past its bound is refused in words, not a traceback.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import io
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exposure_fixtures import (
    StandInStore,
    api,
    config,
    harness_run,
    incident_in,
    refusal,
    stand_in_store,
    with_run_root,
)

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root

EXPOSURE = "physgate.evaluation.tiers.exposure"
LOGS = {"register.jsonl", "register.head", "run-roots.jsonl", "run-roots.head"}


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "s")


def _refused(call: Callable[[], object]) -> tuple[str, str] | None:
    """``(reason, words)`` ``call`` is refused with, or ``None``; any other error fails the row."""
    error = api(f"{EXPOSURE}.ExposureError")
    try:
        call()
    except error as exc:
        return str(exc.context.get("refused_because", "refused")), str(exc)
    except Exception as exc:
        msg = f"refused by {type(exc).__name__}, not with a reason"
        raise AssertionError(msg) from exc
    return None


def _tiers(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    try:
        code = main(["tiers", *args])
    except SystemExit:
        pytest.fail(f"tiers has no command {args[0]} taking these arguments")
    except Exception as exc:  # noqa: BLE001 - a traceback is what the row refuses
        pytest.fail(f"the command ended in a traceback ({type(exc).__name__}), not in words")
    out = capsys.readouterr().out.strip().splitlines()
    assert out, "the command printed nothing"
    return code, json.loads(out[-1])


def _mark(made: StandInStore, reason: str = "opened the tier by hand") -> None:
    mark = api(f"{EXPOSURE}.mark_exposed")
    mark(made.store, "control", made.version, by="a person", reason=reason)


# ------------------------------------------------------------------------------------ removed


def test_a_version_is_written_with_both_logs_beside_it(made: StandInStore) -> None:
    there = {p.name for p in withheld_root(made.store, "control").iterdir()}
    assert there >= LOGS, f"a version was written without its logs: {sorted(there)}"


@pytest.mark.parametrize("removed", ["both files", "the withheld root", "the head alone"])
def test_a_removed_register_refuses_every_reader_and_writer(
    made: StandInStore, removed: str
) -> None:
    _mark(made)
    withheld = withheld_root(made.store, "control")
    if removed == "both files":
        (withheld / "register.jsonl").unlink()
        (withheld / "register.head").unlink()
    elif removed == "the withheld root":
        shutil.rmtree(withheld)
    else:
        (withheld / "register.head").unlink()
    exposed = api(f"{EXPOSURE}.exposed_versions")
    assert _refused(lambda: exposed(made.store, "control")) is not None, (
        f"with {removed} gone the register reads as one with nothing exposed"
    )
    scan = api(f"{EXPOSURE}.record_scan")
    assert _refused(lambda: scan(made.store, "control")) is not None, (
        f"with {removed} gone a writer starts a register in its place"
    )
    # A hand mark appends without reading the register first: it too refuses.
    assert _refused(lambda: _mark(made, "opened it again")) is not None, (
        f"with {removed} gone a hand mark starts a register in its place"
    )
    if removed == "both files":
        assert not (withheld / "register.jsonl").exists(), "a writer started a new register"


def test_a_log_holding_lines_past_its_head_is_refused_in_words(made: StandInStore) -> None:
    _mark(made)
    head = withheld_root(made.store, "control") / "register.head"
    before = head.read_bytes()
    _mark(made, "opened it once more")
    head.write_bytes(before)  # as a writer stopped between the log and its head leaves it
    found = _refused(lambda: api(f"{EXPOSURE}.register_lines")(made.store, "control"))
    assert found is not None, "a line past the head is read as recorded"
    assert "cut off" in found[1], f"the refusal does not say what happened: {found[1]}"


def test_a_reader_holds_the_logs_under_the_writers_lock_shared(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken: list[int] = []
    real = fcntl.flock

    def flock(fd: int, operation: int) -> None:
        taken.append(operation)
        real(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    api(f"{EXPOSURE}.register_lines")(made.store, "control")
    api(f"{EXPOSURE}.run_roots")(made.store, "control")
    assert taken.count(fcntl.LOCK_SH) >= 2, f"a reader read the logs unlocked: {taken}"


# --------------------------------------------------------------------------------------- late


def test_a_baseline_round_on_a_version_exposed_since_its_runs_started_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    from baseline_fixtures import run_set

    from physgate.evaluation.baseline.runner import BaselineError, plan

    runs = with_run_root(made, tmp_path / "runs")
    # As every measured run on the store: its run roots withheld whole.
    whole: dict[str, Any] = {"withheld_whole": [str(runs)]}
    measured = harness_run(runs, made.tasks["visible"][0], made, **whole)
    plan(made.store, "control", made.version, run_set((measured, 0)), base_url=None)
    # Another run on the version reads its held-out tier while the first is done and waiting.
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False, **whole))
    why: object = None
    try:
        plan(made.store, "control", made.version, run_set((measured, 0)), base_url=None)
    except BaselineError as exc:
        why = exc.context.get("refused_because")
    assert why == "version_exposed", f"a round started on a version seen since: {why}"


def test_compare_says_when_a_run_s_version_is_exposed_now(
    tmp_path: Path, made: StandInStore
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from observe_rig import fake_run, target_repo

    from physgate.evaluation.baseline.record import record_bytes, tiers_record
    from physgate.evaluation.observe.compare import compare
    from physgate.evaluation.tiers.heldout import tier_digest
    from physgate.evaluation.tiers.manifest import read_version

    repo = target_repo(tmp_path)
    overrides = {
        "held_out": made.held_out,
        "held_out_sha256": tuple(tier_digest(Path(r)) for r in made.held_out),
        "held_out_canaries": made.canaries,
    }
    record = record_bytes(tiers_record(read_version(made.store / "control" / made.version)))
    sides = []
    for name in ("base", "cand"):
        run = fake_run(tmp_path, name, repo, overrides=overrides)
        (run / "evaluation").mkdir()
        (run / "evaluation" / "tiers.json").write_bytes(record)
        sides.append(run)
    assert tuple(getattr(compare(*sides), "notes", ())) == ()
    runs = with_run_root(made, tmp_path / "runs")
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    notes = tuple(getattr(compare(*sides), "notes", ()))
    assert any("exposed" in note for note in notes), f"compare is silent on a seen version: {notes}"


# ------------------------------------------------------------------------------------- hidden


def test_a_run_made_inside_another_run_leaves_the_root_not_fully_read(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    outer = harness_run(runs, made.tasks["visible"][1], made)
    inner = harness_run(outer, made.tasks["visible"][2], made, ended=False)
    incident_in(inner)
    withheld = str(withheld_root(made.store, "control"))
    code, said = _tiers(capsys, "scan-exposures", "--withheld", withheld)
    assert code == 1, f"a run inside a run was taken as read: {said}"
    assert said.get("not_fully_read") == [str(runs)], said
    assert said.get("unread_places") == [f"{outer.name}/{inner.name}"], said
    assert said.get("added") == 0, "a run inside a run was parsed"
    fresh = tmp_path / "more-runs"
    harness_run(harness_run(fresh, made.tasks["visible"][1], made), made.tasks["visible"][2], made)
    found = _refused(lambda: api(f"{EXPOSURE}.add_run_root")(made.store, "control", fresh))
    assert found is not None and found[0] == "run_root_not_fully_read", found


def test_a_run_json_a_session_planted_in_its_worktree_is_never_opened(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    outer = harness_run(runs, made.tasks["visible"][1], made)
    for place in ("worktrees", "scratch"):
        planted = outer / place / "x"
        planted.mkdir(parents=True)
        (planted / "run.json").write_text("not a run")
        (planted / "raw.json").write_text('{"held_out_seen": true}')
    opened: list[str] = []
    real_os_open, real_io_open = os.open, io.open

    def os_open(path: Any, *args: Any, **kwargs: Any) -> int:  # noqa: ANN401
        opened.append(str(path))
        return real_os_open(path, *args, **kwargs)

    def io_open(path: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        opened.append(str(path))
        return real_io_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(io, "open", io_open)
    report = api(f"{EXPOSURE}.scan_exposures")(made.store, "control")
    inside = [p for p in opened if str(outer / "worktrees") in p or str(outer / "scratch") in p]
    assert inside == [], f"a file a session left in a run was opened: {inside}"
    assert (report.added, report.unread) == (0, ()), report
    exposed = api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    assert made.version not in exposed, "a file a session left in its worktree was read"


def test_the_walk_s_bounds_hold_outside_runs(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    deep = runs.joinpath(*["d"] * 4)
    deep.mkdir(parents=True)
    module = importlib.import_module(EXPOSURE)
    monkeypatch.setattr(module, "MOST_DEPTH", 3)
    found = _refused(lambda: module.exposed_versions(made.store, "control"))
    assert found is not None and "deeper" in found[1], found
    monkeypatch.setattr(module, "MOST_DEPTH", 8)
    monkeypatch.setattr(module, "MOST_ENTRIES", 3)
    found = _refused(lambda: module.exposed_versions(made.store, "control"))
    assert found is not None and "entries" in found[1], found


def test_a_measured_run_made_inside_another_run_s_own_places_is_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    outer = harness_run(runs, made.tasks["visible"][1], made)
    inside = outer / "worktrees" / "x"
    inside.mkdir(parents=True)
    why = refusal(config(made.tasks["visible"][0], made), inside / "r2")
    assert why is not None and "(run_inside_a_run)" in why, why


def test_a_link_in_a_run_root_leaves_it_not_fully_read(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = tmp_path / "elsewhere"
    incident_in(harness_run(elsewhere, made.tasks["visible"][1], made, ended=False))
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "to-elsewhere").symlink_to(elsewhere, target_is_directory=True)
    add = api(f"{EXPOSURE}.add_run_root")
    found = _refused(lambda: add(made.store, "control", linked))
    assert found is not None and found[0] == "run_root_not_fully_read", found
    clean = with_run_root(made, tmp_path / "runs")
    (clean / "to-elsewhere").symlink_to(elsewhere, target_is_directory=True)
    withheld = str(withheld_root(made.store, "control"))
    code, said = _tiers(capsys, "scan-exposures", "--withheld", withheld)
    assert code == 1, f"a scan that could not read a root whole passes: {said}"
    assert said.get("not_fully_read") == [str(clean)], said
    assert said.get("warning"), f"the scan does not say it in words: {said}"


# ---------------------------------------------------------------------------------- unchecked


def _raw_record(made: StandInStore, tier: str) -> None:
    task = made.tasks[tier][0]
    trial = withheld_root(made.store, "control") / "baseline" / "0123456789abcdef" / "t0"
    (trial / "harness").mkdir(parents=True)
    record: dict[str, Any] = {
        "session_id": "raw-1",
        "end": "ended",
        "held_out_seen": None,
        "task": task.id,
        "pins": {"brief_sha256": hashlib.sha256(task.brief.encode()).hexdigest()},
        "held_out_sha256": [],
    }
    (trial / "harness" / "raw.json").write_text(json.dumps(record))


@pytest.mark.parametrize("tier", ["held_out", "validation", "visible"])
def test_a_raw_record_that_looked_for_no_canary_on_a_protected_task_is_an_unchecked_exposure(
    made: StandInStore, capsys: pytest.CaptureFixture[str], tier: str
) -> None:
    _raw_record(made, tier)
    exposed = api(f"{EXPOSURE}.exposed_versions")(made.store, "control")
    if tier == "visible":
        assert made.version not in exposed, "a visible task, which has no canary, burnt a version"
        return
    assert made.version in exposed, f"nobody looked on a {tier} task, and it reads as clean"
    added, _ = api(f"{EXPOSURE}.record_scan")(made.store, "control")
    assert added == 1
    lines = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert [line.source for line in lines if line.kind == "exposure"] == ["raw_record_unchecked"]
    main(["tiers", "status", "--store", str(made.store)])
    (version,) = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["versions"]
    assert "exposed_unchecked" in version["because"], version
    assert "exposed" not in version["because"], "an unchecked exposure is shown as a confirmed one"


# -------------------------------------------------------------------------------- saved first


def test_a_scan_given_roots_reads_them_when_the_run_roots_log_is_broken(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    incident_in(harness_run(runs, made.tasks["visible"][1], made, ended=False))
    withheld = withheld_root(made.store, "control")
    (withheld / "run-roots.head").unlink()
    code, said = _tiers(capsys, "scan-exposures", "--withheld", str(withheld), "--roots", str(runs))
    assert code == 0 and said.get("added") == 1, said
    lines = api(f"{EXPOSURE}.register_lines")(made.store, "control")
    assert [line.source for line in lines if line.kind == "exposure"] == ["incident"]


def test_a_registered_root_that_is_gone_is_said_and_fails_the_scan(
    tmp_path: Path, made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = with_run_root(made, tmp_path / "runs")
    runs.rmdir()
    withheld = str(withheld_root(made.store, "control"))
    code, said = _tiers(capsys, "scan-exposures", "--withheld", withheld)
    assert code == 1, f"a root that is gone is read as empty: {said}"
    assert said.get("missing_roots") == [str(runs)], said
    assert said.get("warning"), f"the scan does not say it in words: {said}"


# ------------------------------------------------------------------------------------ bounded


@pytest.mark.parametrize("field", ["--by", "--reason"])
def test_a_hand_mark_past_its_bound_is_refused_in_words(
    made: StandInStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    given = {"--by": "a person", "--reason": "opened the tier by hand"}
    given[field] = "word " * 200
    withheld = str(withheld_root(made.store, "control"))
    argv = ["mark-exposed", "--withheld", withheld, "--version", made.version]
    code, said = _tiers(capsys, *argv, *[x for pair in given.items() for x in pair])
    assert code == 1 and said.get("refused_because") == "hand_mark_too_long", said
    assert "500" in said.get("error", ""), f"the bound is not stated: {said}"
    assert api(f"{EXPOSURE}.register_lines")(made.store, "control") == []
