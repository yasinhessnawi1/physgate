"""The record audit re-derives every record of a cell from its own files and names each difference.

A round's records are derived again from what its trials left (the raw arm's record, the stream,
the copied answer, the harness run's account) by the functions that wrote them, and compared. A
record doctored in any way the audit names is caught, by its kind and the trial's place; a round
left as it ran shows none. Of a protected tier only the kinds are said, counted.

The rounds here run on the stand-in store and the stand-in raw arm the baseline's other rows use;
the harness half runs on a run the real loop made over the orchestrator's stand-ins.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    RESET_EPOCH,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.audit import (
    KINDS,
    Difference,
    audit_raw,
    compare,
    detail_bytes,
    printed,
    rederive_harness_trial,
    said,
    write_detail,
)
from physgate.evaluation.baseline.record import BASELINE_RECORD
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    LEDGER,
    TRIALS,
    WORK,
    RoundWaits,
    RunSet,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.assemble import ExcludedTrial
from physgate.evaluation.per_role.report import TrialRecord
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import Task, parse_task

PER_ROLE_TESTS = Path(__file__).resolve().parents[1] / "per_role"
if str(PER_ROLE_TESTS) not in sys.path:
    sys.path.insert(0, str(PER_ROLE_TESTS))

from harness_rig import loop_run  # noqa: E402
from task_fixtures import own_task  # noqa: E402

API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
BEFORE = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
AFTER = datetime(2026, 11, 13, 12, 21, tzinfo=UTC)


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _start(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any) -> None:  # noqa: ANN401
    at = how.pop("at", BEFORE)
    run_baseline(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
        now=lambda: at,
        **how,
    )


def _audit(made: StandInStore, runs: RunSet, out: Path) -> list[Difference]:
    return audit_raw(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        prices=load_price_sheet(PRICES),
        score=_score,
    )


def _cell(tmp_path: Path, made: StandInStore) -> tuple[RunSet, Path]:
    """A round of four visible trials and two held-out ones, each kind of end among them.

    Entry 0 passes; 1 is ended by the machine once and run once more; 2 twice, so unscored; 3
    is refused by the check after its end, so excluded; 4 (held out) meets the usage limit,
    waits, and passes on its next start; 5 (held out) passes.
    """
    runs_dir = tmp_path / "runs"
    tasks = [*made.tasks["visible"][:4], *made.tasks["held_out"][:2]]
    runs = run_set(*((harness_run(runs_dir, task, made), 0) for task in tasks))
    out = tmp_path / "round"
    arm = StandInArm(
        ended={2: API_ERROR, 4: API_ERROR, 5: API_ERROR},
        end_refused={6},
        limited={7: RESET_EPOCH},
    )
    with pytest.raises(RoundWaits):
        _start(made, runs, out, arm)
    _start(made, runs, out, arm, resume=True, at=AFTER)
    return runs, out


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _rewrite(path: Path, lines: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


# Each doctoring of the visible records: what it does to the round in ``out``.
def _drop_line(out: Path, _store: StandInStore) -> None:
    _rewrite(out / TRIALS, _lines(out / TRIALS)[1:])


def _add_line(out: Path, _store: StandInStore) -> None:
    lines = _lines(out / TRIALS)
    _rewrite(out / TRIALS, [*lines, {**lines[0], "trial": 7}])


def _exclude(out: Path, _store: StandInStore) -> None:
    lines = _lines(out / TRIALS)
    first = lines[0]
    excluded = {k: first[k] for k in ("suite", "task", "arm", "trial")} | {"reason": "end: x"}
    _rewrite(out / TRIALS, [excluded, *lines[1:]])


def _field(name: str, value: Any) -> Callable[[Path, StandInStore], None]:  # noqa: ANN401
    def doctor(out: Path, _store: StandInStore) -> None:
        lines = _lines(out / TRIALS)
        _rewrite(out / TRIALS, [{**lines[0], name: value}, *lines[1:]])

    return doctor


def _protected(out: Path, store: StandInStore) -> Path:
    round_id = _lines(out / LEDGER)[0]["round"]
    return withheld_root(store.store, "control") / BASELINE_DIR / round_id / TRIALS


def _reason(out: Path, _store: StandInStore) -> None:
    lines = _lines(out / TRIALS)
    at = next(i for i, line in enumerate(lines) if "reason" in line)
    lines[at] = {**lines[at], "reason": "end: something else"}
    _rewrite(out / TRIALS, lines)


def _cost(out: Path, _store: StandInStore) -> None:
    lines = _lines(out / TRIALS)
    cost = dict(lines[0]["cost"])
    key = next(k for k, v in cost.items() if isinstance(v, int) and not isinstance(v, bool))
    cost[key] += 1
    _rewrite(out / TRIALS, [{**lines[0], "cost": cost}, *lines[1:]])


def _flags(out: Path, _store: StandInStore) -> None:
    lines = _lines(out / TRIALS)
    control = dict(lines[0]["control"])
    control["no_gain_crossover"] = not control["no_gain_crossover"]
    _rewrite(out / TRIALS, [{**lines[0], "control": control}, *lines[1:]])


def _count(out: Path, _store: StandInStore) -> None:
    record = json.loads((out / BASELINE_RECORD).read_text())
    record["counts"]["visible"]["passed"] += 1
    record["counts"]["visible"]["unscored"] -= 1
    (out / BASELINE_RECORD).write_text(json.dumps(record))


def _session_after(out: Path, _store: StandInStore) -> None:
    shutil.copytree(out / WORK / "0000-1", out / WORK / "0000-2")


def _unreadable(out: Path, _store: StandInStore) -> None:
    (out / WORK / "0000-1" / "harness" / "raw.json").write_text("{not json")


#: Each doctoring, the kind it is caught by, the tier and the trial's place it is said at.
DOCTORED: dict[str, tuple[Callable[[Path, StandInStore], None], str, str, int | None]] = {
    "a record deleted": (_drop_line, "missing", "visible", 0),
    "a record added": (_add_line, "extra", "visible", None),
    "a scored trial written excluded": (_exclude, "excluded", "visible", 0),
    "an outcome changed": (_field("outcome", "fail"), "outcome", "visible", 0),
    "an exclusion's reason changed": (_reason, "reason", "visible", 3),
    "a cost changed": (_cost, "cost", "visible", 0),
    "a wall clock changed": (_field("wall_clock_s", 1.0), "wall_clock", "visible", 0),
    "a control flag changed": (_flags, "control", "visible", 0),
    "a tier's count changed": (_count, "count", "visible", None),
    "a session kept after the one recorded": (_session_after, "sessions", "visible", 0),
    "a session's record unreadable": (_unreadable, "unrederivable", "visible", 0),
}


def test_a_round_left_as_it_ran_shows_no_difference(tmp_path: Path, store: StandInStore) -> None:
    runs, out = _cell(tmp_path, store)
    assert _audit(store, runs, out) == []


@pytest.mark.parametrize("doctoring", list(DOCTORED))
def test_a_doctored_record_is_caught_by_its_kind_and_the_trial_s_place(
    tmp_path: Path, store: StandInStore, doctoring: str
) -> None:
    runs, out = _cell(tmp_path, store)
    doctor, kind, tier, index = DOCTORED[doctoring]
    doctor(out, store)
    found = _audit(store, runs, out)
    assert any(d.kind == kind and d.index == index and d.tier == tier for d in found), found


def test_a_doctored_protected_record_is_said_by_kind_and_count_alone(
    tmp_path: Path, store: StandInStore
) -> None:
    runs, out = _cell(tmp_path, store)
    protected = _protected(out, store)
    lines = _lines(protected)
    _rewrite(protected, [{**lines[0], "outcome": "fail"}, *lines[1:]])
    found = _audit(store, runs, out)
    assert [(d.tier, d.kind, d.index) for d in found] == [("held_out", "outcome", 4)]
    digest = write_detail(store.store, "control", found)
    line = printed(found, digest)
    assert json.loads(line)["differences"] == {"raw.held_out": {"outcome": 1}}
    for secret in (*(t.id for t in store.tasks["held_out"]), str(store.store), '"index"'):
        assert secret not in line
    # The whole detail, the place included, lies beneath the withheld root under its digest.
    kept = withheld_root(store.store, "control") / BASELINE_DIR / "audits" / f"{digest}.json"
    assert kept.read_bytes() == detail_bytes(found)
    assert json.loads(kept.read_text())["differences"][0]["index"] == 4


def test_every_kind_the_audit_names_is_caught_by_some_row() -> None:
    caught = {kind for _, kind, _, _ in DOCTORED.values()} | set(HARNESS_ONLY)
    assert caught == set(KINDS)


# -- the harness half --------------------------------------------------------------------------

#: The kinds only a harness record carries.
HARNESS_ONLY = ("gate", "review")


@pytest.fixture(autouse=True)
def _no_target_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop's stand-in run has no target repository for its manifest's commit.

    So its manifest id and its priced cost are stand-ins, as the trial layer's own rows give
    them; every other input of its record is the run's own.
    """
    import physgate.evaluation.baseline.audit as audit
    from physgate.evaluation.observe.cost import CostLine

    line = {
        "manifest_id": "e" * 64,
        "run_id": "r",
        "started": "2026-10-19T10:00:00.000000Z",
        "auth": "subscription",
        "endpoint": "default",
        "basis": "list_price_estimate",
        "prices_date": "2026-10-16",
        "prices_sha256": "a" * 64,
        "usd_to_nok": "9.5",
        "usd_to_nok_date": "2026-10-16",
        "rows": [],
        "usd": "0",
        "nok": "0",
        "partial": False,
    }
    cost = CostLine.model_validate_json(json.dumps(line))
    monkeypatch.setattr(audit, "manifest_id_of", lambda _run, _events: "e" * 64)
    monkeypatch.setattr(audit, "price_run", lambda *_a, **_k: cost)


def _harness_record(tmp_path: Path) -> tuple[Path, Task, TrialRecord | ExcludedTrial]:
    run = loop_run(tmp_path / "run", verdicts=("fail",))
    task = parse_task(json.dumps(own_task()).encode())
    record = rederive_harness_trial(
        run,
        task,
        suite="control_visible",
        trial=0,
        prices=load_price_sheet(PRICES),
        score=_score,
        answer=None,
    )
    return run, task, record


def test_a_harness_record_is_derived_again_the_same_from_its_run(tmp_path: Path) -> None:
    run, task, record = _harness_record(tmp_path)
    again = rederive_harness_trial(
        run,
        task,
        suite="control_visible",
        trial=0,
        prices=load_price_sheet(PRICES),
        score=_score,
        answer=None,
    )
    assert compare("harness", "visible", {0: again}, [record]) == []


@pytest.mark.parametrize("kind", HARNESS_ONLY)
def test_a_harness_record_doctored_in_its_gate_or_reviews_is_caught(
    tmp_path: Path, kind: str
) -> None:
    _, _, record = _harness_record(tmp_path)
    assert isinstance(record, TrialRecord)
    raw = record.model_dump(mode="json")
    if kind == "gate":
        gate = raw["gate"] or {"checks_run": 0, "artefacts_caught": 0}
        raw["gate"] = {
            **gate,
            "checks_run": gate["checks_run"] + 1,
            "caught_after_reviewer_passed": 0,
        }
    else:
        review = raw["review"] or {"reviews": 0, "failed": 0, "blocked": 0}
        raw["review"] = {**review, "reviews": review["reviews"] + 1}
    doctored = TrialRecord.model_validate_json(json.dumps(raw))
    found = compare("harness", "visible", {0: record}, [doctored])
    assert [(d.kind, d.index) for d in found] == [(kind, 0)]


def test_a_visible_difference_is_said_by_kind_and_place(tmp_path: Path) -> None:
    found = [
        Difference("raw", "visible", "outcome", 2),
        Difference("raw", "visible", "count", None, "passed"),
    ]
    assert said(found) == {
        "raw.visible": [
            {"kind": "count", "index": None, "field": "passed"},
            {"kind": "outcome", "index": 2, "field": None},
        ]
    }
