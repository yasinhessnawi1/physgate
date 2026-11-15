"""A scripted run on the reference brief: one part owned, one made, the rest found; and its re-run.

ARCH-122, the run of the feature end to end with no model: the stand-in decomposition lists the
robot's six parts, the run holds before any session until a person has decided each one, the
release writes what the person stated onto the parts' nodes, the physics gate judges those values
before any session runs, both modules are designed, reviewed and merged, and every session is
handed the parts record the release names. The re-run reads the recorded configuration and the
recorded decisions and nothing else, and every record of the run comes out the same: the
configuration, the event log, the ledger, the queue and its decisions, the store's journal, and
the trees of every commit (the observability tests' exact comparison).

A rerun under a new run id cannot match the journal: a declared quantity's record names its
item, and an item's id carries the run's. A row below pins exactly where that rerun parts.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import reference_parts_run as ref

from physgate.evaluation.observe.rerun import Comparison, RerunPlan, compare_runs, rerun
from physgate.evaluation.observe.sequence import RECORDS
from physgate.orchestrator.events import read_events
from physgate.orchestrator.parts import choice_of, parts_choices, sourcing_lines
from physgate.orchestrator.queue import DECISIONS_NAME, PartsBody, parts_sha256
from physgate.orchestrator.replay import replay
from physgate.state.schema import DECLARED_SOURCE
from physgate.state.store import journal_records_after

HAVE, MAKE = ref.GEARMOTORS, ref.BUMPER


def outcome_of(how: Callable[[], Any]) -> Any:  # noqa: ANN401 - whatever came of it
    """What ``how`` returned, or the exception it raised: a row asserts on either."""
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the row asserts on
        return exc


FOUND = (ref.DRIVER, ref.IMU, ref.CELLS, ref.ENCODERS)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> ref.Made:
    with pytest.MonkeyPatch.context() as patch:
        return ref.recorded_run(patch, tmp_path_factory.mktemp("recorded"))


@pytest.fixture(scope="module")
def log(recorded: ref.Made) -> list[dict[str, Any]]:
    raw = (recorded.run_dir / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in raw]


def _kinds(log: list[dict[str, Any]]) -> list[str]:
    return [str(line["kind"]) for line in log]


def _decisions(run_dir: Path) -> list[dict[str, Any]]:
    raw = (run_dir / DECISIONS_NAME).read_text().splitlines()
    return [json.loads(line) for line in raw]


def _item(number: int) -> str:
    return f"{ref.RUN_ID}-parts-{number}"


def _head(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Each node as the store's journal last wrote it, read without opening the store."""
    return {line.node_id: line.payload for line in journal_records_after(run_dir / "store", 0)}


# --- the run ---------------------------------------------------------------------------------


def test_the_run_holds_for_its_parts_then_runs_to_its_end(
    recorded: ref.Made, log: list[dict[str, Any]]
) -> None:
    assert recorded.steps == ("wait", "done")
    kinds = _kinds(log)
    released = kinds.index("parts_released")
    first_dispatch = kinds.index("session_spawned") if "session_spawned" in kinds else None
    first_stage = kinds.index("stage_entered")
    assert released < first_stage
    assert first_dispatch is None or released < first_dispatch
    assert kinds.count("decision_taken") == len(ref.COMPONENTS)
    assert kinds.count("merged") == len(ref.MODULES)
    system = [line for line in log if line["kind"] == "integration_gate_ran"]
    assert len(system) == 1 and system[0]["result"]["verdict"] == "pass"
    assert kinds[-1] == "run_ended" or "run_ended" not in kinds


def test_the_brief_is_the_reference_brief_and_its_digest_is_recorded(recorded: ref.Made) -> None:
    config = json.loads((recorded.run_dir / "run.json").read_text())
    assert config["brief_sha256"] == ref.brief_sha256()
    assert ref.BRIEF.name == "balboa-32u4.md"
    assert config["parts_on_hand"] == "on"
    assert config["queue_decisions"] == "act"


def test_each_part_is_decided_by_the_person_once_have_make_and_the_rest_find(
    recorded: ref.Made, log: list[dict[str, Any]]
) -> None:
    lines = _decisions(recorded.run_dir)
    assert [line["item_id"] for line in lines] == [_item(n) for n in range(1, 7)]
    assert [line["position"] for line in lines] == ["have", "make", *["find"] * len(FOUND)]
    assert {line["resolved_by"] for line in lines} == {ref.OPERATOR}
    have, make = lines[0]["parts"], lines[1]["parts"]
    stated = {"mass": (0.0095, "kg"), "stall_current": (1.6, "A")}
    declared = {name: {"value": v, "unit": u} for name, (v, u) in stated.items()}
    assert have == {"declared": declared, "texts": []}
    assert make == {"declared": {"mass": {"value": 0.012, "unit": "kg"}}, "texts": [ref.MAKE_TEXT]}
    assert all("parts" not in line for line in lines[2:])
    taken = [line for line in log if line["kind"] == "decision_taken"]
    assert [line["effect"] for line in taken] == ["declare", "declare", *["find"] * len(FOUND)]
    assert all(line["acts"] for line in taken)


def test_what_the_person_stated_is_on_each_part_s_node_naming_its_decision(
    recorded: ref.Made,
) -> None:
    lines = {line["item_id"]: line for line in _decisions(recorded.run_dir)}
    head = _head(recorded.run_dir)
    for component, number in ((HAVE, 1), (MAKE, 2)):
        assert component.node in head, component.node
        node, line = head[component.node], lines[_item(number)]
        digest = parts_sha256(PartsBody.model_validate_json(json.dumps(line["parts"])))
        assert (node["owner_role"], node["domain"]) == (component.role, component.domain)
        assert set(node["quantities"]) == set(line["parts"]["declared"])
        for name, stated in line["parts"]["declared"].items():
            quantity = node["quantities"][name]
            assert (quantity["value"], quantity["unit"]) == (stated["value"], stated["unit"])
            assert quantity["source"] == DECLARED_SOURCE
            assert quantity["declared"] == {
                "item_id": _item(number),
                "decision_sha256": digest,
                "operator": ref.OPERATOR,
            }
    assert not {one.node for one in FOUND} & set(head)


def test_the_release_gate_judged_the_declared_values_before_any_session(
    log: list[dict[str, Any]],
) -> None:
    kinds = _kinds(log)
    gated = [line for line in log if line["kind"] == "parts_gate_ran"]
    assert len(gated) == 1
    result = gated[0]["result"]
    assert result is not None and result["verdict"] == "pass" and result["mode"] == "on"
    judged = {record["node"] for record in result["checks"] if record["node"] is not None}
    assert {HAVE.node, MAKE.node} <= judged
    assert {record["name"] for record in result["checks"]} >= {"units", "magnitude"}
    assert kinds.index("parts_gate_ran") < kinds.index("parts_released")
    assert kinds.count("parts_write_done") == 2
    assert [line["node_id"] for line in log if line["kind"] == "parts_write_done"] == [
        HAVE.node,
        MAKE.node,
    ]


def test_every_session_is_handed_the_record_the_release_names(
    recorded: ref.Made, log: list[dict[str, Any]]
) -> None:
    released = next(line for line in log if line["kind"] == "parts_released")
    assert recorded.requests, "no session ran"
    for request in recorded.requests:
        issued = request.parts_record
        assert issued is not None, request.subtask_id
        assert (issued.sha256, issued.length) == (
            released["record_sha256"],
            released["record_length"],
        )
        assert ref.MAKE_TEXT in issued.text
        assert HAVE.node in issued.text and MAKE.node in issued.text
    assert {r.assigned_role for r in recorded.requests} == set(ref.ROLES)


def test_each_part_s_choice_reads_back_and_sourcing_skips_the_owned_and_the_made(
    recorded: ref.Made,
) -> None:
    state = replay(read_events(recorded.run_dir / "events.jsonl"))
    choices = parts_choices(state)
    assert {node: c.choice for node, c in choices.items()} == {
        HAVE.node: "have",
        MAKE.node: "make",
        **{one.node: "find" for one in FOUND},
    }
    assert choice_of(choices, "electrical.not_planned") == "find"
    electrical = [one.node for one in ref.COMPONENTS if one.domain == "electrical"]
    lines = {line.node: line for line in sourcing_lines(electrical, choices)}
    assert (lines[HAVE.node].status, lines[HAVE.node].reason) == ("skipped", "owned")
    for one in FOUND:
        if one.domain == "electrical":
            assert (lines[one.node].status, lines[one.node].reason) == ("unchecked", None)
    assert (lambda line: (line.status, line.reason))(sourcing_lines([MAKE.node], choices)[0]) == (
        "skipped",
        "custom",
    )


def test_a_further_process_over_the_ended_run_finds_the_system_scope_result_as_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The call is asked again of the canonical store and must give what the log recorded.
    run = ref.recorded_run(monkeypatch, tmp_path)
    before = _kinds(
        [json.loads(x) for x in (run.run_dir / "events.jsonl").read_text().splitlines()]
    )
    assert ref.driven_once_more(monkeypatch, run) == "done"
    after = _kinds([json.loads(x) for x in (run.run_dir / "events.jsonl").read_text().splitlines()])
    assert after[: len(before)] == before
    assert "incident" not in after[len(before) :] and "halted" not in after[len(before) :]


# --- the re-run ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def again(recorded: ref.Made, tmp_path_factory: pytest.TempPathFactory) -> ref.Made:
    with pytest.MonkeyPatch.context() as patch:
        return ref.rerun_from_config(patch, recorded, tmp_path_factory.mktemp("again"))


def test_a_rerun_from_the_recorded_configuration_reproduces_every_record_exactly(
    recorded: ref.Made, again: ref.Made
) -> None:
    assert again.steps == recorded.steps
    assert (again.run_dir / "run.json").read_bytes() == (recorded.run_dir / "run.json").read_bytes()
    found = outcome_of(lambda: compare_runs(recorded.run_dir, again.run_dir))
    assert isinstance(found, Comparison), found
    assert found.level == "exact"
    assert {name: found.exact[name] for name in RECORDS} == dict.fromkeys(RECORDS)
    assert found.decisions is None and found.decisions_compared > 0
    assert found.reproduced and found.first is None
    # The person's decisions and the store's journal are the same bytes, not only the same
    # once normalised.
    for name in (DECISIONS_NAME, "queue.jsonl", "store/journal.jsonl"):
        assert (again.run_dir / name).read_bytes() == (recorded.run_dir / name).read_bytes(), name


def test_the_rerun_s_sessions_were_handed_the_same_record(
    recorded: ref.Made, again: ref.Made
) -> None:
    assert [r.parts_record for r in again.requests] == [r.parts_record for r in recorded.requests]


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", ref.ENDPOINT)
    yield


def test_a_rerun_under_a_new_run_id_parts_only_where_a_record_names_the_run_s_own_item(
    recorded: ref.Made, tmp_path: Path, endpoint: None
) -> None:
    """The evaluation's rerun, which needs a run id of its own: where it parts, and why.

    Two records bind to an item's id, which carries the run's: a person's decision binds to the
    digest of the item's line, and a declared quantity names its item. The comparison maps the
    run id in every line it reads but cannot reach into a digest, and reads the journal raw and
    the store's commits by their trees. So exactly those part, and nothing else.
    """
    elsewhere = tmp_path / "elsewhere"

    def driver(plan: RerunPlan) -> None:
        cfg = plan.recorded.model_copy(update={"run_id": plan.run_id})
        with pytest.MonkeyPatch.context() as patch:
            ref.made(
                patch,
                plan.run_dir.parent,
                cfg,
                plan.target,
                lambda run_dir: ref.decide_as_recorded(
                    recorded.run_dir, run_dir, plan.recorded.run_id
                ),
            )

    found = outcome_of(
        lambda: rerun(
            recorded.run_dir,
            brief=ref.BRIEF,
            run_id="run-other",
            run_dir=elsewhere / "run-other",
            target=recorded.repo,
            install=tmp_path / "install",
            review_root=tmp_path / "review-scratch",
            driver=driver,
        )
    )
    assert isinstance(found, Comparison), found
    assert not found.reproduced
    parted = {name for name in RECORDS if found.exact[name] is not None}
    assert parted == {"events", "queue_decisions", "journal", "git"}, found.exact
    events, decided = found.exact["events"], found.exact["queue_decisions"]
    assert events is not None and decided is not None
    assert (events.field, decided.field) == ("shown_sha256", "shown_sha256")
    log = [json.loads(x) for x in (recorded.run_dir / "events.jsonl").read_text().splitlines()]
    assert log[events.index]["kind"] == "decision_taken"
    assert found.decisions is None, "the decision sequence itself is the same"
    # Every journal line is the same once the run's id is read as the run's: only the item a
    # declared quantity names carries it.
    mine = (recorded.run_dir / "store" / "journal.jsonl").read_text().splitlines()
    theirs = (elsewhere / "run-other" / "store" / "journal.jsonl").read_text().splitlines()
    assert len(mine) == len(theirs)
    differing = [i for i, (a, b) in enumerate(zip(mine, theirs, strict=True)) if a != b]
    assert differing, "the journals did not part"
    for i in differing:
        assert '"declared"' in mine[i]
        assert mine[i].replace(ref.RUN_ID, "<run>") == theirs[i].replace("run-other", "<run>")
