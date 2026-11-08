"""A version is stale, all three tiers of it, once the question its author was asked changed.

The question is the author brief and the requirements source it draws on (the metrics and
their units, the scorer's id and version, the composition rule). A version records both
digests; a changed brief template, a changed metric unit or a changed composition rule each
make every tier of an older version stale. ``physgate tiers status`` prints each version's
state with counts and digests only.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role import metrics
from physgate.evaluation.tiers import authoring
from physgate.evaluation.tiers.task import canonical_json

TIERS = ["visible", "validation", "held_out"]


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _store(tmp_path: Path) -> tuple[Path, Any]:
    store = tmp_path.resolve() / "store"
    pool = store / "control" / "withheld" / "pool"
    ids = [f"control.t{i:02d}" for i in range(24)]
    for task_id in ids:
        write_task_dir(
            pool / task_id,
            own_task(id=task_id),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    manifest, _ = _api("physgate.evaluation.tiers.store.write_version")(
        store / "control",
        [pool / task_id for task_id in ids],
        role="control",
        seed=3,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": []}),
        retire=pool,
    )
    return store, manifest


def _stale(manifest: Any) -> tuple[list[str], list[str]]:
    found = _api("physgate.evaluation.tiers.manifest.staleness")(manifest)
    return list(found.tiers), list(found.because)


def test_a_version_written_to_today_s_question_is_fresh(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    assert _stale(manifest) == ([], [])


def test_a_changed_brief_template_makes_every_tier_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest = _store(tmp_path)
    monkeypatch.setattr(authoring, "AUTHOR_BRIEF", authoring.AUTHOR_BRIEF + "\nOne more rule.\n")
    assert _stale(manifest) == (TIERS, ["brief_changed"])


def test_a_changed_metric_unit_makes_every_tier_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, manifest = _store(tmp_path)
    monkeypatch.setitem(metrics.CONTROL_METRIC_UNITS, "phase_margin", "rad")
    tiers, because = _stale(manifest)
    assert tiers == TIERS and "requirements_changed" in because


@pytest.mark.parametrize(
    ("module", "name", "value"),
    [
        ("physgate.evaluation.tiers.manifest", "COMPOSES_AT_LEAST", 3),
        ("physgate.evaluation.tiers.manifest", "CONTROL_SCORER_VERSION", "9.9.9"),
    ],
    ids=["the composition rule", "the scorer's version"],
)
def test_a_changed_requirements_source_alone_makes_every_tier_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, name: str, value: Any
) -> None:
    _, manifest = _store(tmp_path)
    _api(f"{module}.{name}")
    monkeypatch.setattr(importlib.import_module(module), name, value)
    assert _stale(manifest) == (TIERS, ["requirements_changed"])


def test_status_prints_each_version_s_state_with_counts_and_digests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    store, manifest = _store(tmp_path)
    held = sorted(
        p.name for p in (store / "control" / manifest.version / "held_out").iterdir() if p.is_dir()
    )
    assert main(["tiers", "status", "--store", str(store)]) == 0
    printed = capsys.readouterr().out
    found = json.loads(printed)
    (row,) = found["versions"]
    assert (row["role"], row["version"], row["state"]) == ("control", manifest.version, "fresh")
    assert row["tiers"]["held_out"]["count"] == 8
    assert row["tiers"]["held_out"]["sha256"] == manifest.held_out.sha256
    assert found["left"] == {"pool_left": 0, "temporary_version_left": 0, "work_left": 0}
    assert not [task_id for task_id in held if task_id in printed]
    monkeypatch.setattr(authoring, "AUTHOR_BRIEF", authoring.AUTHOR_BRIEF + "\nchanged\n")
    assert main(["tiers", "status", "--store", str(store)]) == 0
    (row,) = json.loads(capsys.readouterr().out)["versions"]
    assert row["state"] == "stale" and row["stale_tiers"] == TIERS
    assert row["because"] == ["brief_changed"]


def test_status_names_a_version_that_is_not_its_manifest_and_a_split_s_leftovers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    store, manifest = _store(tmp_path)
    (store / "control" / manifest.version / "notes.txt").write_text("a person's note")
    (store / "control" / "withheld" / "pool").mkdir(parents=True)
    assert main(["tiers", "status", "--store", str(store)]) == 1
    found = json.loads(capsys.readouterr().out)
    (row,) = found["versions"]
    assert row["state"] == "refused" and row["because"] == ["version_holds_other"]
    assert found["left"] == {"pool_left": 1, "temporary_version_left": 0, "work_left": 0}


def test_status_counts_a_session_s_work_left_out_of_a_role_s_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    store, _ = _store(tmp_path)
    (store / "control" / "check.working").write_text('{"work": "/elsewhere/work"}\n')
    code = main(["tiers", "status", "--store", str(store)])
    found = json.loads(capsys.readouterr().out)
    assert found["left"].get("work_left") == 1 and code == 1


def test_status_on_a_store_that_cannot_be_read_prints_a_refusal_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    store, _ = _store(tmp_path)
    store_module = importlib.import_module("physgate.evaluation.tiers.store")
    real = store_module.os.listdir

    def unlistable(path: Any = ".") -> list[str]:
        if isinstance(path, str | os.PathLike) and Path(path) == store:
            raise PermissionError(f"cannot list {path}")
        return list(real(path))

    monkeypatch.setattr(store_module.os, "listdir", unlistable)
    try:
        code = main(["tiers", "status", "--store", str(store)])
    except OSError as exc:
        pytest.fail(f"an unreadable store gives a traceback, not a refusal line: {exc!r}")
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 1 and len(lines) == 1
    assert json.loads(lines[0]).get("refused_because") == "store_unreadable"
