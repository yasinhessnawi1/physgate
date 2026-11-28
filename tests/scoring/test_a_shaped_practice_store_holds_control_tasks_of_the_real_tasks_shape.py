"""A practice store of the shaped kind holds control tasks of the shape the real tier's tasks have.

``physgate tiers practice --kind shaped`` builds, at a new directory, one practice version of six
control tasks shaped like real control tasks rather than bare ones: each names a physical system
it invents, asks for a continuous controller ``C(s)`` judged on linear criteria of a unit step,
and holds its plant's values in its inputs. Most briefs write the plant in the scorer's own
symbols, whose values only the inputs hold; one plant is open-loop unstable; one task bounds the
controller's peak output by an actuator limit its brief calls given and states only in the
inputs; one is a plain stable plant written in numbers. No task states a rate limit.

Each task is solvable: its reference controller passes the real scorer and its deliberately wrong
one fails the spec it names. What a session is given for each (the issued text) leaves no symbol
without a value and states no number of the passing reference, by the values check itself. The
version says it is practice where every counting reader holds it (the manifest, the provenance,
the ids), never in a brief. The bare kind, the command's default, writes the bytes it wrote
before.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from physgate.cli import main
from physgate.evaluation.per_role.scorers.control import score
from physgate.evaluation.tiers.manifest import practice_refusal, read_version
from physgate.evaluation.tiers.practice import SEED, build_practice_store, write_practice_task
from physgate.evaluation.tiers.store import version_dir
from physgate.evaluation.tiers.task import LoadedTask, Task, load_task

TIERS = ("visible", "validation", "held_out")
#: The scorer's names, as a brief writes them: a word of its own.
SCORER_NAME = re.compile(
    r"(?<![A-Za-z0-9_])(plant_num_\d+|plant_den_\d+|plant_gain|plant_delay|reference_step|"
    r"actuator_limit)(?![A-Za-z0-9_])"
)
#: A number of the brief's own, never a digit of a name or a power.
NUMBER = re.compile(r"(?<![A-Za-z_^\d.])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
#: The criteria a real control task is judged on: linear ones, of the closed loop's unit step.
LINEAR = {"settling_time", "overshoot", "steady_state_error", "phase_margin", "max_real_pole"}
LINEAR_WITH_EFFORT = LINEAR | {"actuator_peak"}
#: Digests of the bare kind's six tasks and of its provenance, taken on the code before the shaped
#: kind was added.
BARE_TASKS_SHA256 = "da202553d9bd71b79e62bdc958c90baa81908d90ac4b0c5eb04588ed6b6ce5eb"
BARE_PROVENANCE_SHA256 = "197852de38aa8a3dcb5e17310a65e59e16fed1faf7b7b4a1edee7f507e1524b7"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    store = tmp_path_factory.mktemp("shaped") / "store"
    argv = ["tiers", "practice", "--store", str(store), "--implementer-model", "m"]
    assert main([*argv, "--kind", "shaped", "--seed", str(SEED)]) == 0
    versions = [p.name for p in (store / "control").iterdir() if len(p.name) == 64]
    assert len(versions) == 1
    return store, versions[0]


def _tasks(store: Path, version: str) -> dict[str, list[LoadedTask]]:
    directory = version_dir(store, "control", version)
    return {
        tier: [load_task(d) for d in sorted((directory / tier).iterdir()) if d.is_dir()]
        for tier in TIERS
    }


def _every(store: Path, version: str) -> list[LoadedTask]:
    return [loaded for tier in _tasks(store, version).values() for loaded in tier]


def _plant(task: Task, prefix: str) -> list[float]:
    by_name = {m.name: float(m.value) for m in task.inputs}
    found = []
    while f"{prefix}_{len(found)}" in by_name:
        found.append(by_name[f"{prefix}_{len(found)}"])
    return found


def _brief_numbers(task: Task) -> set[float]:
    return {float(x) for x in NUMBER.findall(task.brief)}


def _symbols_only(task: Task) -> bool:
    """The brief writes its plant in the scorer's symbols and states none of the plant's values."""
    coefficients = {m.name for m in task.inputs if m.name.startswith(("plant_num_", "plant_den_"))}
    named = set(SCORER_NAME.findall(task.brief))
    values = {float(m.value) for m in task.inputs if m.name in coefficients}
    return bool(named & coefficients) and not (values - {0.0, 1.0}) & _brief_numbers(task)


def _open_loop_unstable(task: Task) -> bool:
    return bool(np.max(np.real(np.roots(_plant(task, "plant_den")))) > 0)


def _bounds_effort(task: Task) -> bool:
    return any(spec.metric == "actuator_peak" for spec in task.specs)


def test_the_command_prints_the_shaped_kind_and_its_tiers_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["tiers", "practice", "--store", str(tmp_path / "s"), "--implementer-model", "m"]
    assert main([*argv, "--kind", "shaped", "--seed", "7"]) == 0
    line = json.loads(capsys.readouterr().out)
    assert line["kind"] == "shaped" and line["practice"] is True
    assert [line[tier]["count"] for tier in TIERS] == [2, 2, 2]
    manifest = read_version(version_dir(tmp_path / "s", "control", line["version"]))
    assert manifest.seed == 7


def test_the_version_is_practice_where_every_reader_holds_it_and_no_brief_says_so(
    built: tuple[Path, str],
) -> None:
    store, version = built
    directory = version_dir(store, "control", version)
    manifest = read_version(directory)
    assert manifest.practice is True
    assert practice_refusal(manifest, shakedown=False) is not None
    assert practice_refusal(manifest, shakedown=True) is None
    provenance = json.loads((directory / "provenance.json").read_bytes())
    assert provenance == {
        "kind": "shaped",
        "practice": True,
        "written_by": "physgate.tiers.practice",
    }
    tasks = _tasks(store, version)
    assert [len(tasks[tier]) for tier in TIERS] == [2, 2, 2]
    ids = sorted(loaded.task.id for tier in TIERS for loaded in tasks[tier])
    assert ids == [f"control.practice_shaped_{n:02d}" for n in range(6)]
    for tier in TIERS:
        for loaded in tasks[tier]:
            brief = loaded.task.brief
            # A brief says how the output is measured, never that the task is not.
            assert not re.search(
                r"practi[cs]e|shakedown|not (?:a )?measured|never a measured", brief, re.I
            )
            assert (loaded.task.canary is None) == (tier == "visible")


def test_each_task_names_a_system_and_asks_for_a_continuous_controller_on_linear_criteria(
    built: tuple[Path, str],
) -> None:
    store, version = built
    for loaded in _every(store, version):
        task = loaded.task
        brief = task.brief
        assert "C(s)" in brief and "unity negative feedback" in brief
        assert "write the controller to the file `answer.json`" in brief
        assert task.answer.form == "lti_tf"
        # A named physical system: its words come before the transfer function.
        assert len(brief.split("G(s)")[0].split()) >= 8
        metrics = {spec.metric for spec in task.specs}
        assert "settling_time" in metrics and metrics <= LINEAR_WITH_EFFORT
        # Nothing of a board, firmware or parts, and no rate limit anywhere.
        assert not re.search(
            r"firmware|board|\bparts?\b|\bsampling\b|sample (?:period|time)|\brate\b",
            brief,
            re.IGNORECASE,
        )
        assert not any("rate" in m.name for m in task.inputs)


def test_the_tasks_cover_the_real_tasks_shapes(
    built: tuple[Path, str],
) -> None:
    store, version = built
    tasks = [loaded.task for loaded in _every(store, version)]
    symbols = [t for t in tasks if _symbols_only(t)]
    unstable = [t for t in tasks if _open_loop_unstable(t)]
    effort = [t for t in tasks if _bounds_effort(t)]
    plain = [
        t
        for t in tasks
        if not _open_loop_unstable(t) and not _bounds_effort(t) and not SCORER_NAME.search(t.brief)
    ]
    assert len(symbols) == 4
    assert len(unstable) == 1 and unstable[0] in symbols
    assert len(plain) == 1
    # One bound on the peak output, by a limit the brief names and calls given, its number only
    # in the inputs; most tasks state no magnitude limit.
    assert len(effort) == 1
    (bounded,) = effort
    limit = next(m for m in bounded.inputs if m.name == "actuator_limit")
    assert "actuator_limit" in bounded.brief and "given" in bounded.brief
    assert float(limit.value) not in _brief_numbers(bounded)
    peak = next(spec for spec in bounded.specs if spec.metric == "actuator_peak")
    assert not isinstance(peak.bound, tuple)
    assert (peak.op, peak.bound.value, peak.bound.unit) == ("<=", limit.value, limit.unit)
    # Its gain is a symbol no input gives, as two real tasks' are: the scorer takes it as 1.
    assert "plant_gain" in bounded.brief and all(m.name != "plant_gain" for m in bounded.inputs)


@pytest.mark.parametrize("number", range(6))
def test_each_task_is_solvable_and_its_wrong_controller_fails_the_spec_it_names(
    built: tuple[Path, str], number: int
) -> None:
    store, version = built
    wanted = f"control.practice_shaped_{number:02d}"
    (loaded,) = [each for each in _every(store, version) if each.task.id == wanted]
    good = [ref for ref in loaded.references if ref.fails is None]
    bad = [ref for ref in loaded.references if ref.fails is not None]
    assert len(good) == 1 and len(bad) >= 1
    record = score(loaded.task, Path(good[0].answer_path))
    assert record["answer_valid"] is True and record["passed"] is True
    for ref in bad:
        record = score(loaded.task, Path(ref.answer_path))
        failed = {row["name"] for row in record["specs"] if not row["passed"]}
        assert record["passed"] is False and ref.fails in failed


def test_the_values_check_finds_no_symbol_without_a_value_and_no_leak_in_the_issued_text(
    built: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    store, version = built
    capsys.readouterr()
    argv = ["tiers", "values-check", "--store", str(store), "--role", "control"]
    assert main([*argv, "--version", version]) == 0
    tiers = json.loads(capsys.readouterr().out)["tiers"]
    for tier in TIERS:
        counts = tiers[tier]
        assert counts["tasks"] == 2
        assert counts["not_issuable"] == 0
        assert counts["symbol_without_value"]["issued"] == 0
        assert counts["given_without_value"]["issued"] == 0
        assert counts["issued_leaks"] == 0 and counts["issued_leak_unchecked"] == 0
        # Every tier holds a brief whose symbols only the issued text gives values to, so each
        # tier a round reads shows a session given the task's values, not its brief alone.
        assert counts["symbol_without_value"]["brief"] >= 1
    total = {
        key: sum(tiers[tier][key]["brief"] for tier in TIERS)
        for key in ("symbol_without_value", "given_without_value")
    }
    assert total == {"symbol_without_value": 5, "given_without_value": 1}
    assert sum(tiers[tier]["brief_names_a_defaulted_value"]["plant_gain"] for tier in TIERS) == 1


def test_the_bare_kind_is_the_default_and_writes_the_bytes_it_wrote_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    pool.mkdir()
    digest = hashlib.sha256()
    for n in range(6):
        directory = write_practice_task(pool, n)
        for f in sorted(p for p in directory.rglob("*") if p.is_file()):
            digest.update(str(f.relative_to(pool)).encode() + b"\0" + f.read_bytes() + b"\0")
    assert digest.hexdigest() == BARE_TASKS_SHA256
    manifest = build_practice_store(tmp_path / "store", implementer_model="m")
    assert manifest.provenance_sha256 == BARE_PROVENANCE_SHA256
    argv = ["tiers", "practice", "--store", str(tmp_path / "s"), "--implementer-model", "m"]
    assert main(argv) == 0
    line = json.loads(capsys.readouterr().out)
    assert sorted(line) == ["held_out", "practice", "validation", "version", "visible"]
    tasks = _every(tmp_path / "s", line["version"])
    assert sorted(t.task.id for t in tasks) == [f"control.practice_{n:02d}" for n in range(6)]


def test_the_command_offers_the_practice_module_s_kinds_and_refuses_another(
    tmp_path: Path,
) -> None:
    from physgate.evaluation import tierset_cli
    from physgate.evaluation.tiers.practice import KINDS, PracticeError

    assert tierset_cli._PRACTICE_KINDS == KINDS
    with pytest.raises(PracticeError) as refused:
        build_practice_store(tmp_path / "store", implementer_model="m", kind="other")
    assert refused.value.context["refused_because"] == "kind_unknown"
    assert not (tmp_path / "store").exists()
