from __future__ import annotations

import json
from pathlib import Path

import pytest
from control_fixtures import control_task

from physgate.evaluation.per_role import synthesise
from physgate.evaluation.per_role.exceptions import SynthesisError
from physgate.evaluation.per_role.scorers.control import check_references, score
from physgate.evaluation.per_role.task import canonical_json, load_task


def test_the_search_finds_a_controller_the_scorer_passes(tmp_path: Path) -> None:
    task = control_task()
    good = synthesise.search(task)
    path = tmp_path / "answer.json"
    path.write_bytes(canonical_json(good.model_dump(mode="json")))
    assert score(task, path)["passed"]


def test_the_same_task_and_seed_give_the_same_reference() -> None:
    first = synthesise.search(control_task())
    second = synthesise.search(control_task())
    assert canonical_json(first.model_dump(mode="json")) == canonical_json(
        second.model_dump(mode="json")
    )


def test_each_bad_reference_fails_the_spec_it_names(tmp_path: Path) -> None:
    task = control_task()
    good = synthesise.search(task)
    bads = synthesise.bad_references(task, good)
    assert {name: spec for name, (_, spec) in bads.items()} == {
        "bad_unstable": "stable",
        "bad_margin": "margin",
        "bad_slow": "settling",
    }
    root = tmp_path / task.id
    root.mkdir()
    (root / "task.json").write_text(task.model_dump_json(), encoding="utf-8")
    synthesise.write_references(root, good, bads, task.answer.path)
    check_references(load_task(root))


def test_the_mismodelled_plants_are_the_published_checker_s_two_mistakes() -> None:
    delayed = control_task([1.0, 2.0], [1.0, 1.0, 1.0], delay=0.4)
    truncated = synthesise._mismodelled(delayed, truncate=True, drop_delay=False)
    delay_free = synthesise._mismodelled(delayed, truncate=False, drop_delay=True)
    assert truncated is not None and delay_free is not None
    numerator = [(m.name, m.value, m.unit) for m in truncated.inputs if "num" in m.name]
    assert numerator == [("plant_num_0", 1.0, "1")]
    assert not any(m.name == "plant_delay" for m in delay_free.inputs)
    assert synthesise._mismodelled(control_task(), truncate=True, drop_delay=False) is None


def test_a_controller_tuned_on_the_wrong_plant_is_kept_only_where_the_real_plant_fails_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from control_fixtures import controller

    from physgate.evaluation.per_role.answer import LtiTf

    task = control_task([1.0], [1.0, 1.0], delay=0.5, pm_min=0.0, ts=(0.0, 50.0), ess_max=1.0)
    aggressive = LtiTf.model_validate_json(json.dumps(controller([1.0], [1.0], gain=10.0)))
    monkeypatch.setattr(synthesise, "search", lambda _task, seed=0: aggressive)
    bads = synthesise.bad_references(task, aggressive)
    assert bads["bad_delay_free"][1] == "stable"
    assert "bad_truncated_plant" not in bads


def test_a_task_no_controller_meets_is_reported_and_still_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(synthesise, "GENERATIONS", 1)
    monkeypatch.setattr(synthesise, "POPULATION", 2)
    # Settle within 0.1 ms to 0.2 ms with 89 degrees of margin: nothing in reach does.
    impossible = control_task(pm_min=89.0, ts=(1e-4, 2e-4))
    with pytest.raises(SynthesisError):
        synthesise.search(impossible)
    rows = synthesise.prepare([impossible], tmp_path)
    assert rows[0]["good"] is False and not rows[0]["checked"] and "reason" in rows[0]
    assert (tmp_path / impossible.id / "task.json").is_file()


def test_prepare_writes_held_references_and_one_row_per_task(tmp_path: Path) -> None:
    rows = synthesise.prepare([control_task()], tmp_path)
    assert rows == [
        {
            "task": "control.test_plant",
            "good": True,
            "bad": ["bad_margin:margin", "bad_slow:settling", "bad_unstable:stable"],
            "checked": True,
        }
    ]
    expect = json.loads(
        (tmp_path / "control.test_plant/references/bad_slow/expect.json").read_text()
    )
    assert expect == {"fails": "settling"}
