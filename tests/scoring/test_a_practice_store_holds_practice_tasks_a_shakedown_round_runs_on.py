"""A practice store holds one version of practice tasks, and a baseline round runs on it whole.

The store is built by ``physgate tiers practice`` into a new directory of the row's own: six
control tasks written for practice, each labelled so in its brief and held to the split's entry
checks with the real scorer, split two to a tier by the store's own writer, and a stand-in check
record in the imported form that flags none. A baseline round on its two held-out tasks then runs
end to end on the stand-in raw arm and the real scorer, and the record audit finds nothing to
differ. No real tier, store or register is read: everything lies beneath the row's directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASELINE_TESTS = Path(__file__).resolve().parents[1] / "unit" / "evaluation" / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import (  # noqa: E402
    PRICES,
    StandInArm,
    StandInStore,
    harness_run,
    run_set,
    setup_for,
)

from physgate.cli import main  # noqa: E402
from physgate.evaluation.baseline.audit import audit_raw  # noqa: E402
from physgate.evaluation.baseline.runner import run_baseline  # noqa: E402
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.scorers.control import score  # noqa: E402
from physgate.evaluation.tiers.checks import read_check  # noqa: E402
from physgate.evaluation.tiers.manifest import read_version  # noqa: E402
from physgate.evaluation.tiers.practice import (  # noqa: E402
    ANSWER_SAID,
    NO_SESSION,
    PracticeError,
    build_practice_store,
)
from physgate.evaluation.tiers.store import version_dir, withheld_root, work_root  # noqa: E402
from physgate.evaluation.tiers.task import parse_task  # noqa: E402

TIERS = ("visible", "validation", "held_out")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    store = tmp_path_factory.mktemp("practice") / "store"
    manifest = build_practice_store(store, implementer_model="claude-opus-5-5")
    return store, manifest.version


def test_the_version_holds_two_practice_tasks_to_a_tier_and_nothing_else(
    built: tuple[Path, str],
) -> None:
    store, version = built
    manifest = read_version(version_dir(store, "control", version))
    assert [getattr(manifest, tier).count for tier in TIERS] == [2, 2, 2]
    # The version says it is practice where readers hold it; no brief says so to a session.
    assert manifest.practice is True
    for tier in TIERS:
        for task_file in (version_dir(store, "control", version) / tier).glob("*/task.json"):
            task = parse_task(task_file.read_bytes())
            assert "practice" not in task.brief.lower() and "measured" not in task.brief
            assert ANSWER_SAID in task.brief
            assert task.id.startswith("control.practice_")
            assert (task.canary is None) == (tier == "visible")
    assert sorted(p.name for p in (store / "control").iterdir() if len(p.name) == 64) == [version]


def test_its_check_record_is_a_stand_in_in_the_imported_form_that_flags_none(
    built: tuple[Path, str],
) -> None:
    store, version = built
    record = read_check(store, "control", version)
    assert record is not None
    assert record.source == "imported" and record.flagged == ()
    assert (record.tasks, record.all_yes) == (2, 2)
    assert record.kept.session_id == NO_SESSION and record.kept.stream_sha256 is None


def test_a_practice_store_is_built_only_into_a_new_directory(tmp_path: Path) -> None:
    (tmp_path / "store").mkdir()
    with pytest.raises(PracticeError) as refused:
        build_practice_store(tmp_path / "store", implementer_model="claude-opus-5-5")
    assert refused.value.context["refused_because"] == "store_exists"
    assert list((tmp_path / "store").iterdir()) == []


def test_the_command_builds_one_and_prints_counts_and_digests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["tiers", "practice", "--store", str(tmp_path / "s"), "--implementer-model", "m"]
    assert main(argv) == 0
    line = json.loads(capsys.readouterr().out)
    assert line["practice"] is True and line["held_out"]["count"] == 2
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().out)["refused_because"] == "store_exists"


def test_a_baseline_round_runs_on_its_held_out_pair_end_to_end_and_its_audit_is_clean(
    built: tuple[Path, str], tmp_path: Path
) -> None:
    import shutil

    store = tmp_path / "store"
    shutil.copytree(built[0], store, symlinks=True)
    version = built[1]
    directory = version_dir(store, "control", version)
    tasks = {
        tier: [parse_task(p.read_bytes()) for p in sorted((directory / tier).glob("*/task.json"))]
        for tier in TIERS
    }
    canaries = tuple(
        c
        for tier in TIERS[1:]
        for c in json.loads((directory / tier / "canaries.json").read_text())
    )
    held_out = (
        str(withheld_root(store, "control")),
        str(work_root(store, "control")),
        *(str(directory / tier) for tier in TIERS[1:]),
    )
    made = StandInStore(store, version, tasks, canaries, held_out)
    runs = run_set(*((harness_run(tmp_path / "runs", t, made), 0) for t in tasks["held_out"]))
    out = tmp_path / "round"
    prices = load_price_sheet(PRICES)
    record = run_baseline(
        store=store,
        role="control",
        version=version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=score,
        prices=prices,
        arm=StandInArm(),
        sleep=lambda _s: None,
        shakedown=True,
    )
    assert record.practice is True
    counts = record.counts["held_out"]
    assert (counts.trials, counts.covered, counts.of, counts.whole) == (2, 2, 2, True)
    assert counts.passed + counts.failed == 2
    found = audit_raw(
        store=store,
        role="control",
        version=version,
        runs=runs,
        out=out,
        prices=prices,
        score=score,
        shakedown=True,
    )
    assert found == []
