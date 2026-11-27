"""A practice version says so in its manifest, and only a round told it is a shakedown counts it.

The mark is a field of the manifest every counting reader reads (``practice``), left out of a
manifest that is not a practice one, so a real version keeps its bytes and its id. A baseline
round, the counting rule's census and the per-role report refuse a practice version
(``practice_version``) unless told the round is a shakedown; told so, the round's record says it
ran on one. No word of a practice brief tells its session the task is practice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import BaselineError, RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.manifest import (
    MANIFEST_NAME,
    TierSet,
    practice_refusal,
    read_version,
    version_id,
)
from physgate.evaluation.tiers.practice import ANSWER_SAID, practice_task
from physgate.evaluation.tiers.store import version_dir


@pytest.fixture(scope="module")
def practice(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("practice"), practice=True)


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("real"))


def _manifest(made: StandInStore) -> TierSet:
    return read_version(version_dir(made.store, "control", made.version))


def test_a_version_that_is_not_a_practice_one_keeps_its_bytes_and_its_id(
    real: StandInStore,
) -> None:
    raw = (version_dir(real.store, "control", real.version) / MANIFEST_NAME).read_bytes()
    fields = json.loads(raw)
    assert "practice" not in fields
    assert version_id(fields) == real.version == _manifest(real).version
    assert _manifest(real).practice is None
    assert practice_refusal(_manifest(real), shakedown=False) is None


def test_a_practice_version_says_so_in_its_manifest_and_is_another_version(
    practice: StandInStore, real: StandInStore
) -> None:
    manifest = _manifest(practice)
    assert manifest.practice is True
    unmarked = {k: v for k, v in manifest.model_dump(mode="json").items() if k != "practice"}
    assert version_id(unmarked) != manifest.version
    refusal = practice_refusal(manifest, shakedown=False)
    assert refusal is not None and refusal[0] == "practice_version"
    assert practice_refusal(manifest, shakedown=True) is None


def _round(made: StandInStore, runs: RunSet, out: Path, **how: Any) -> BaselineRecord | Exception:  # noqa: ANN401
    try:
        return run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=lambda _t, _a: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=StandInArm(),
            sleep=lambda _s: None,
            **how,
        )
    except Exception as exc:  # noqa: BLE001 - asserted by the caller
        return exc


def test_a_baseline_round_on_a_practice_version_runs_only_as_a_shakedown_and_says_so(
    tmp_path: Path, practice: StandInStore, real: StandInStore
) -> None:
    store = copied(practice, tmp_path / "store")
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    refused = _round(store, runs, tmp_path / "round")
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "practice_version"
    assert not (tmp_path / "round").exists(), "nothing made before the refusal"
    record = _round(store, runs, tmp_path / "shakedown", shakedown=True)
    assert isinstance(record, BaselineRecord) and record.practice is True
    # On a real version the word changes nothing, and its record holds no such field.
    other = copied(real, tmp_path / "real")
    runs = run_set((harness_run(tmp_path / "r2", other.tasks["visible"][0], other), 0))
    plain = _round(other, runs, tmp_path / "plain")
    assert isinstance(plain, BaselineRecord) and plain.practice is None
    assert "practice" not in json.loads((tmp_path / "plain" / "baseline.json").read_text())


def test_the_census_refuses_a_practice_version_unless_told_it_is_a_shakedown(
    tmp_path: Path, practice: StandInStore
) -> None:
    from physgate.evaluation.tiers.measure import census

    (tmp_path / "runs.json").write_text(json.dumps({"format": 1, "trials": []}))
    (tmp_path / "trials.jsonl").write_text("")

    def reason(**how: Any) -> str | None:  # noqa: ANN401
        try:
            census(
                practice.store,
                "control",
                practice.version,
                "visible",
                tmp_path / "runs.json",
                tmp_path / "trials.jsonl",
                **how,
            )
        except PerRoleError as exc:
            return exc.context.get("refused_because")
        return None

    assert reason() == "practice_version"
    assert reason(shakedown=True) != "practice_version"


def test_no_practice_brief_says_it_is_practice_and_each_names_its_answer_as_real_briefs_do() -> (
    None
):
    for number in range(6):
        brief = str(practice_task(number)["brief"])
        assert "practice" not in brief.lower() and "measured" not in brief
        assert "shakedown" not in brief.lower()
        assert ANSWER_SAID in brief
