"""The isolation probe counts what answers built for one requirement alone score on held-out tasks.

For each held-out scenario and each requirement it composes, the probe builds an answer aimed at
that requirement's own specifications alone and scores it as the scenario scores any answer. A
scenario every such answer fails is one whose pass needs its requirements together; one that some
such answer passes turns on one requirement, whatever it declares. Neither found nor scored is
counted apart, never as either. It prints counts, never an id, and every probe of a version is one
measurement of it in the register. It refuses, counting nothing, inside a session, for a version
the register marks exposed, for a version it does not know, for a register or a tier it cannot
read whole, for a tier that changed after the version was read, for a task it cannot read, and
for a task of another role or one its way of answering makes no scenario of. Whatever goes wrong,
even an error it did not foresee, the command prints one line, no traceback and nothing of a
held-out task, counts nothing and leaves no answer behind. These rows use a fixture way of
answering, so the scorer is not needed; the control scorer's own rows are in the evaluation
environment.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from probe_fixtures import FixtureMethod, StandInStore, api, stand_in_store

from physgate.cli import main
from physgate.evaluation.tiers.store import withheld_root

PROBE = "physgate.evaluation.tiers.probe"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "pr")


def _probe(made: StandInStore, method: FixtureMethod, *, seed: int = 3) -> dict[str, Any]:
    found = api(f"{PROBE}.probe_version")(
        withheld_root(made.store, "control"), made.version, seed=seed, method=method
    )
    dumped: dict[str, Any] = found.model_dump(mode="json")
    return dumped


def _module() -> Any:  # noqa: ANN401
    """The probe's module, or the row fails: it is not built yet."""
    found = None
    with contextlib.suppress(ImportError):
        found = importlib.import_module(PROBE)
    assert found is not None, "the probe is not built"
    return found


def _composes(result: dict[str, Any]) -> bool:
    """The composing tier's check: every scenario failed by every one-requirement answer."""
    findings = result["findings"]
    return bool(
        findings["tasks"] > 0
        and findings["tasks_failed_by_every_single_requirement_answer"] == findings["tasks"]
    )


def _measurements(made: StandInStore) -> list[Any]:
    lines = api("physgate.evaluation.tiers.exposure.register_lines")(made.store, "control")
    return [line for line in lines if line.kind == "measurement"]


def _refused(made: StandInStore, method: FixtureMethod, **kwargs: Any) -> str:  # noqa: ANN401
    """Why the probe refused; the row fails if it counted a measurement."""
    before = _measurements(made)
    error = api("physgate.evaluation.per_role.exceptions.PerRoleError")
    withheld = kwargs.pop("withheld", withheld_root(made.store, "control"))
    version = kwargs.pop("version", made.version)
    caught: Any = None
    try:
        api(f"{PROBE}.probe_version")(withheld, version, seed=3, method=method)
    except error as exc:
        caught = exc
    except Exception as exc:  # noqa: BLE001 - a row fails on its assertion, never on an error
        raise AssertionError(f"the probe raised {type(exc).__name__}, not a refusal") from None
    assert caught is not None, "the probe did not refuse"
    assert _measurements(made) == before, "a refused probe counted a measurement"
    _names_no_held_out_task(made, str(caught))
    reason: str = caught.context.get("refused_because", "")
    return reason


def _names_no_held_out_task(made: StandInStore, said: str) -> None:
    """The row fails if ``said`` holds a held-out task's id or brief."""
    for task in made.tasks["held_out"]:
        assert task.id not in said, "a held-out task's id is in what the probe said"
        assert task.brief not in said, "a held-out task's brief is in what the probe said"


def test_on_a_tier_that_composes_every_one_requirement_answer_fails_its_scenario(
    made: StandInStore,
) -> None:
    result = _probe(made, FixtureMethod(decides="every"))
    findings = result["findings"]
    assert findings["tasks"] == 8
    assert findings["requirements_per_task"] == {"2": 8}
    assert findings["answers"] == {
        "asked": 16,
        "found": 16,
        "not_found": 0,
        "pass": 0,
        "fail": 16,
        "unscored": 0,
        "flaky": 0,
    }
    assert findings["tasks_failed_by_every_single_requirement_answer"] == 8
    assert findings["tasks_passed_by_a_single_requirement_answer"] == 0
    assert findings["tasks_undecided"] == 0
    assert _composes(result)


def test_on_a_tier_whose_scenarios_turn_on_one_requirement_the_probe_goes_red(
    made: StandInStore,
) -> None:
    result = _probe(made, FixtureMethod(decides="first"))
    findings = result["findings"]
    assert findings["tasks_passed_by_a_single_requirement_answer"] == 8
    assert findings["tasks_failed_by_every_single_requirement_answer"] == 0
    assert findings["answers"]["pass"] == 8 and findings["answers"]["fail"] == 8
    with pytest.raises(AssertionError):
        assert _composes(result), "the probe's check holds on a tier that does not compose"


def test_a_requirement_no_answer_is_found_for_leaves_its_scenario_undecided(
    made: StandInStore,
) -> None:
    findings = _probe(made, FixtureMethod(decides="every", missing=(1,)))["findings"]
    assert findings["answers"]["not_found"] == 8 and findings["answers"]["found"] == 8
    assert findings["tasks_undecided"] == 8
    assert findings["tasks_failed_by_every_single_requirement_answer"] == 0


def test_an_answer_found_for_no_requirement_is_never_scored(made: StandInStore) -> None:
    method = FixtureMethod(decides="every", missing=(0, 1))
    findings = _probe(made, method)["findings"]
    assert method.built == []
    assert findings["answers"]["found"] == 0 and findings["tasks_undecided"] == 8


@pytest.mark.parametrize("outcome", ["unscored", "flaky"])
def test_an_answer_the_scenario_cannot_judge_is_counted_apart_never_as_a_fail(
    made: StandInStore, outcome: str
) -> None:
    findings = _probe(made, FixtureMethod(outcome=outcome))["findings"]
    assert findings["answers"][outcome] == 16 and findings["answers"]["fail"] == 0
    assert findings["tasks_undecided"] == 8
    assert findings["tasks_failed_by_every_single_requirement_answer"] == 0


def test_one_pass_among_a_scenario_s_answers_is_enough_to_say_it_does_not_compose(
    made: StandInStore,
) -> None:
    findings = _probe(made, FixtureMethod(decides="first", missing=(1,)))["findings"]
    assert findings["tasks_passed_by_a_single_requirement_answer"] == 8
    assert findings["tasks_undecided"] == 0


def test_an_outcome_no_scenario_gives_refuses_the_probe(made: StandInStore) -> None:
    assert _refused(made, FixtureMethod(outcome="maybe")) == "outcome_unknown"


def test_a_scenario_composing_one_requirement_is_refused_without_its_id(
    made: StandInStore,
) -> None:
    error = api("physgate.evaluation.per_role.exceptions.PerRoleError")
    with pytest.raises(error) as caught:
        api(f"{PROBE}.probe_version")(
            withheld_root(made.store, "control"),
            made.version,
            seed=3,
            method=FixtureMethod(declared=("only_one",)),
        )
    assert caught.value.context.get("refused_because") == "scenario_not_composing"
    held = {t.id for t in made.tasks["held_out"]}
    assert not any(task_id in str(caught.value) for task_id in held)


def test_every_answer_is_built_in_a_place_of_its_own_beneath_the_withheld_root(
    made: StandInStore,
) -> None:
    method = FixtureMethod()
    _probe(made, method)
    withheld = withheld_root(made.store, "control").resolve()
    assert len(method.built) == 16
    assert len({p.parent for p in method.built}) == 16
    assert all(p.resolve().is_relative_to(withheld) for p in method.built)
    assert not any(p.exists() for p in method.built), "an answer outlived the probe"


def test_the_seed_reaches_every_answer_and_the_result(made: StandInStore) -> None:
    seen: list[int] = []
    method = FixtureMethod()
    original = method.probed

    def probed(task: Any, seed: int) -> Any:  # noqa: ANN401
        seen.append(seed)
        return original(task, seed)

    object.__setattr__(method, "probed", probed)
    result = _probe(made, method, seed=11)
    assert seen == [11] * 8
    assert result["seed"] == 11


def test_every_probe_is_one_measurement_of_the_version_and_says_its_count(
    made: StandInStore,
) -> None:
    first = _probe(made, FixtureMethod())
    lines = _measurements(made)
    assert [(line.measured, line.version, line.key) for line in lines] == [
        ("probe", made.version, first["measurement"]["key"])
    ]
    assert first["measurement"]["count"] == 1
    second = _probe(made, FixtureMethod())
    assert second["measurement"]["count"] == 2
    assert len(_measurements(made)) == 2


def test_the_result_names_its_version_its_tier_and_the_tier_s_digest(made: StandInStore) -> None:
    from physgate.evaluation.tiers.heldout import tier_digest

    result = _probe(made, FixtureMethod())
    held_out = made.store / "control" / made.version / "held_out"
    assert (result["role"], result["version"], result["tier"]) == (
        "control",
        made.version,
        "held_out",
    )
    assert result["tier_sha256"] == tier_digest(held_out)
    assert result["method"] == {"answers": "fixture"}


def test_the_same_tier_and_seed_give_the_same_counts_and_key(made: StandInStore) -> None:
    first, second = _probe(made, FixtureMethod()), _probe(made, FixtureMethod())
    assert first["findings"] == second["findings"]
    assert first["measurement"]["key"] == second["measurement"]["key"]


def test_a_version_the_register_marks_exposed_is_not_probed(made: StandInStore) -> None:
    api("physgate.evaluation.tiers.exposure.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened it by hand"
    )
    method = FixtureMethod()
    assert _refused(made, method) == "version_exposed"
    assert method.built == []


def test_a_version_the_role_does_not_have_is_not_probed(made: StandInStore) -> None:
    assert _refused(made, FixtureMethod(), version="f" * 64) == "version_unknown"


def test_the_probe_is_given_a_role_s_withheld_root_and_nothing_else(made: StandInStore) -> None:
    assert _refused(made, FixtureMethod(), withheld=made.store / "control") == "not_a_withheld_root"


def test_a_role_the_way_of_answering_is_not_for_is_refused(made: StandInStore) -> None:
    assert _refused(made, FixtureMethod(role="firmware")) == "role_not_probed"


def test_inside_a_session_the_probe_counts_nothing(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", "/tmp/session")
    method = FixtureMethod()
    assert _refused(made, method) == "inside_a_session"
    assert method.built == []


def test_a_tier_changed_after_its_version_was_read_is_refused(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real = module.snapshot

    def changed_first(root: Path) -> dict[str, bytes]:
        task = sorted(p for p in root.iterdir() if p.is_dir())[0]
        (task / "task.json").write_bytes((task / "task.json").read_bytes() + b" ")
        return dict(real(root))

    monkeypatch.setattr(module, "snapshot", changed_first)
    method = FixtureMethod()
    assert _refused(made, method) == "tier_changed"
    assert method.built == []


# ---------------------------------------------------------------- the command and what it says


def _command(
    made: StandInStore,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
    version: str | None = None,
) -> tuple[int, str]:
    args = [
        "tiers",
        "probe",
        "--withheld",
        str(withheld_root(made.store, "control")),
        "--version",
        version or made.version,
        *extra,
    ]
    raised = ""
    try:
        code = main(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - a row fails on its assertion, never on an error
        code, raised = -1, f"\n(the command raised {type(exc).__name__})"
    captured = capsys.readouterr()
    return code, captured.out + captured.err + raised


def _with_fixture_method(monkeypatch: pytest.MonkeyPatch, method: FixtureMethod) -> None:
    module = _module()
    monkeypatch.setattr(module, "default_method", lambda: method)


def test_the_command_prints_the_counts_on_one_line(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_fixture_method(monkeypatch, FixtureMethod())
    code, out = _command(made, capsys, "--seed", "3")
    assert code == 0, out
    lines = out.strip().splitlines()
    assert len(lines) == 1
    said = json.loads(lines[0])
    assert said["findings"]["tasks_failed_by_every_single_requirement_answer"] == 8
    assert said["seed"] == 3 and said["measurement"]["count"] == 1


def test_the_command_asks_for_the_seed(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_fixture_method(monkeypatch, FixtureMethod())
    code, out = _command(made, capsys)
    assert code != 0 and "--seed" in out, out
    assert _measurements(made) == []


def test_a_refusal_is_one_line_with_its_reason_and_exit_1(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_fixture_method(monkeypatch, FixtureMethod())
    code, out = _command(made, capsys, "--seed", "3", version="f" * 64)
    assert code == 1
    assert json.loads(out.strip().splitlines()[-1])["refused_because"] == "version_unknown"


def test_outside_the_evaluation_environment_the_command_says_where_it_runs(
    made: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    _module()
    try:
        import numpy  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("the evaluation's numerical libraries are present here")
    code, out = _command(made, capsys, "--seed", "3")
    assert code == 1
    said = json.loads(out.strip().splitlines()[-1])
    assert said["refused_because"] == "evaluation_environment_missing"
    assert _measurements(made) == []


def _everything_written(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def test_nothing_the_probe_says_or_records_names_a_held_out_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from baseline_fixtures import marker

    marked = stand_in_store(tmp_path / "mk", marked=True)
    withheld = withheld_root(marked.store, "control")
    _with_fixture_method(monkeypatch, FixtureMethod())
    code, said = _command(marked, capsys, "--seed", "3")
    assert code == 0, said
    # A refusal, too: the tier changed, which names nothing either.
    module = _module()
    real = module.snapshot

    def changed_first(root: Path) -> dict[str, bytes]:
        task = sorted(p for p in root.iterdir() if p.is_dir())[0]
        (task / "task.json").write_bytes((task / "task.json").read_bytes() + b" ")
        return dict(real(root))

    monkeypatch.setattr(module, "snapshot", changed_first)
    code, refused = _command(marked, capsys, "--seed", "3")
    assert code == 1 and "tier_changed" in refused
    written = _everything_written(withheld)
    held = marked.tasks["held_out"]
    for task in held:
        index = int(task.id.removeprefix("control.zqmark")[:2])
        for text in (marker(index), task.brief):
            assert text not in said and text not in refused
            assert text.encode() not in written
    assert not any(p.name.startswith(".probe") for p in withheld.iterdir())


# ------------------------------------------------- whatever goes wrong, no held-out task is said
#
# A task the way of answering cannot make a scenario of, a task of another role, and an error
# anywhere in reading, building or scoring: each ends in one line naming why, and nothing of a
# held-out task (its id, a field carrying its marker, its brief) is in anything the command
# prints, on either stream; nothing is counted and no answer is left.

MARK = "zqmark"


def _register_bytes(made: StandInStore) -> dict[str, bytes]:
    withheld = withheld_root(made.store, "control")
    return {p.name: p.read_bytes() for p in sorted(withheld.glob("register.*")) if p.is_file()}


def _refused_by_the_command(
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    method: FixtureMethod,
) -> str:
    """Why the command refused: the row fails on anything held out said, counted or left."""
    _with_fixture_method(monkeypatch, method)
    before = _register_bytes(made)
    code, out = _command(made, capsys, "--seed", "3")
    assert code == 1, out
    assert MARK not in out, "a field of a marked task is in what the command printed"
    _names_no_held_out_task(made, out)
    assert "Traceback" not in out, "the command printed a traceback"
    lines = out.strip().splitlines()
    assert len(lines) == 1, out
    assert _register_bytes(made) == before, "a probe that failed wrote to the register"
    withheld = withheld_root(made.store, "control")
    assert not any(p.name.startswith(".probe") for p in withheld.iterdir()), "an answer is left"
    reason: str = json.loads(lines[0])["refused_because"]
    return reason


def test_a_task_the_way_of_answering_cannot_make_a_scenario_of_is_refused_without_its_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scored_otherwise = {"scorer": {"id": "whole_design", "version": "1.1.0", "params": []}}
    made = stand_in_store(tmp_path / "ws", marked=True, changes=scored_otherwise)
    method = FixtureMethod(judges="control")
    assert _refused_by_the_command(made, monkeypatch, capsys, method) == "task_not_probed"
    assert method.built == []


def test_a_task_of_another_role_is_refused_without_its_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made = stand_in_store(tmp_path / "or", marked=True, changes={"role": "firmware"})
    method = FixtureMethod()
    assert _refused_by_the_command(made, monkeypatch, capsys, method) == "task_of_another_role"
    assert method.built == []


def _fail_reading(module: Any, made: StandInStore, monkeypatch: pytest.MonkeyPatch) -> None:
    task = made.tasks["held_out"][0]

    def unreadable(root: Path) -> dict[str, bytes]:
        raise OSError(5, f"{task.id} cannot be read", str(root / task.id / "task.json"))

    monkeypatch.setattr(module, "snapshot", unreadable)


def _fail_placing(module: Any, made: StandInStore, monkeypatch: pytest.MonkeyPatch) -> None:
    task = made.tasks["held_out"][0]

    def no_place(*_: Any, **__: Any) -> str:  # noqa: ANN401
        raise OSError(28, f"no space for {task.id}")

    monkeypatch.setattr(module.tempfile, "mkdtemp", no_place)


def _fail_in_the_command(module: Any, made: StandInStore, monkeypatch: pytest.MonkeyPatch) -> None:
    task = made.tasks["held_out"][0]

    def broken(*_: Any, **__: Any) -> Any:  # noqa: ANN401
        msg = f"something unforeseen about {task.id}: {task.brief}"
        raise RuntimeError(msg)

    monkeypatch.setattr(module, "probe_version", broken)


@pytest.mark.parametrize(
    ("where", "reason"),
    [
        ("reading the tier", "tier_unreadable"),
        ("making the answers' place", "probe_failed"),
        ("building an answer", "probe_failed"),
        ("scoring an answer", "probe_failed"),
        ("the command", "probe_failed"),
    ],
)
def test_an_error_anywhere_in_the_probe_names_no_held_out_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    where: str,
    reason: str,
) -> None:
    made = stand_in_store(tmp_path / "er", marked=True)
    module = _module()
    method = FixtureMethod(
        raising={"building an answer": "answer", "scoring an answer": "score"}.get(where)
    )
    patch = {
        "reading the tier": _fail_reading,
        "making the answers' place": _fail_placing,
        "the command": _fail_in_the_command,
    }.get(where)
    with monkeypatch.context() as patched:
        if patch is not None:
            patch(module, made, patched)
        assert _refused_by_the_command(made, patched, capsys, method) == reason


# ---------------------------------------------- every refusal the probe lists has its row


def _first_held_out_task(made: StandInStore) -> Path:
    held_out = made.store / "control" / made.version / "held_out"
    return sorted(p for p in held_out.iterdir() if p.is_dir())[0]


def _released_if_it_waits(pipe: Path) -> None:
    """Open the FIFO's other end, so a reader blocked on it returns."""
    with contextlib.suppress(OSError):
        os.close(os.open(pipe, os.O_WRONLY | os.O_NONBLOCK))


def _plant(task: Path, entry: str, elsewhere: Path) -> None:
    if entry == "a link":
        copy = elsewhere / "copy.json"
        copy.write_bytes((task / "task.json").read_bytes())
        (task / "task.json").unlink()
        (task / "task.json").symlink_to(copy)
    elif entry == "a pipe":
        os.mkfifo(task / "pipe")
    else:
        os.link(task / "task.json", elsewhere / "second-name.json")


@pytest.mark.parametrize(
    ("when", "reason"),
    [
        # The version is held to its manifest first, so the version itself is refused.
        ("before the probe", "version_unknown"),
        # Between that check and the probe's own read: the read refuses.
        ("as the probe reads it", "tier_unreadable"),
    ],
)
@pytest.mark.parametrize("entry", ["a link", "a pipe", "a second name"])
def test_a_tier_that_cannot_be_read_whole_is_refused(
    made: StandInStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
    when: str,
    reason: str,
) -> None:
    task = _first_held_out_task(made)
    if when == "before the probe":
        _plant(task, entry, tmp_path)
    else:
        module = _module()
        real = module.snapshot

        def planted_first(root: Path) -> dict[str, bytes]:
            _plant(task, entry, tmp_path)
            return dict(real(root))

        monkeypatch.setattr(module, "snapshot", planted_first)
    method = FixtureMethod()
    said: list[str] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            said.append(_refused(made, method))
        except BaseException as exc:  # noqa: BLE001 - reported below, on the test's thread
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=60)
    if worker.is_alive():
        _released_if_it_waits(task / "pipe")
        worker.join(timeout=10)
        pytest.fail(f"the probe waited on {entry} in the tier")
    if errors:
        raise errors[0]
    assert said == [reason]
    assert method.built == []


@pytest.mark.parametrize("how", ["not a task", "no task file"])
def test_a_task_that_cannot_be_read_is_refused_without_its_id(
    made: StandInStore, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    module = _module()
    task = made.tasks["held_out"][0]
    if how == "not a task":
        error = api("physgate.evaluation.per_role.exceptions.TaskFormatError")

        def unparsable(raw: bytes, *, where: str = "task.json") -> Any:  # noqa: ANN401
            raise error(f"{task.id}/task.json is not a task", where=task.id)

        monkeypatch.setattr(module, "parse_task", unparsable)
    else:
        # Read whole and as its manifest names it, but without one task's file: what a tier
        # written by hand could hold.
        real_snapshot, real_sums = module.snapshot, module._sums
        whole: dict[str, bytes] = {}

        def without_a_task_file(root: Path) -> dict[str, bytes]:
            whole.update(real_snapshot(root))
            return {n: b for n, b in whole.items() if n != f"{task.id}/task.json"}

        monkeypatch.setattr(module, "snapshot", without_a_task_file)
        monkeypatch.setattr(module, "_sums", lambda _: real_sums(whole))
    method = FixtureMethod()
    assert _refused(made, method) == "task_unreadable"
    assert method.built == []


def test_a_register_that_cannot_be_read_whole_refuses_the_probe(made: StandInStore) -> None:
    withheld = withheld_root(made.store, "control")
    head = withheld / "register.head"
    head.write_bytes(head.read_bytes()[: len(head.read_bytes()) // 2])
    before = _register_bytes(made)
    method = FixtureMethod()
    error = api("physgate.evaluation.per_role.exceptions.PerRoleError")
    with pytest.raises(error) as caught:
        api(f"{PROBE}.probe_version")(withheld, made.version, seed=3, method=method)
    assert caught.value.context.get("refused_because") == "register_unreadable"
    assert method.built == []
    assert _register_bytes(made) == before, "the probe wrote to a register it could not read"


@pytest.mark.parametrize("raising", ["answer", "score"])
def test_an_error_while_answers_are_built_leaves_no_answer_and_no_register_line(
    made: StandInStore, raising: str
) -> None:
    before = _register_bytes(made)
    method = FixtureMethod(raising=raising)
    assert _refused(made, method) == "probe_failed"
    assert method.built, "no answer was built before the error"
    assert not any(p.exists() for p in method.built), "an answer outlived the probe"
    withheld = withheld_root(made.store, "control")
    assert not any(p.name.startswith(".probe") for p in withheld.iterdir())
    assert _register_bytes(made) == before, "a probe that failed wrote to the register"
