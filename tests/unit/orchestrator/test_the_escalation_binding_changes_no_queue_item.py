"""The escalation decision changes nothing that reaches a person (ARCH-131).

ARCH-131 asks the question "does this subtask go to the approval queue" through one
interface. With the default binding, the deterministic rules, the approval queue must
receive exactly the items it receives with no interface at all. This test holds that
by building every way a subtask reaches the queue (``escalation_paths``) and
comparing the run's records with the ones the loop produced before the interface
existed (``escalation_paths.golden.json``, committed before any change to the loop).

What is compared, per run: the configuration, every event line, the task ledger, the
queue and its decisions, the graph journal and the trees of every commit, normalised
as an exact rerun comparison normalises them. Two things are set aside, and only
these: the sequence number of an event line, since a line the interface adds moves
every later one; and the lines and fields named below, each added on purpose after
the golden file was written. The real gate's own records are compared as the gate now
writes them: where the gate's coverage changed after the golden file was written, the
recorded result is rewritten by the one rule that change states (``_as_the_gate_now_judges``),
and nothing else in it. Anything else that differs is a change in what the loop did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from escalation_paths import (
    GOLDEN,
    MODES,
    RECORDS,
    STAND_INS,
    build,
    records,
    scenario_names,
)
from stand_in_drive_plan import DRIVE_MODULE, POWER_BUS

from physgate.gate.catalogue import catalogue_digest
from physgate.orchestrator import decompose

#: Event kinds the escalation interface writes, absent from the golden file by
#: construction: one decision line at every attempt end that did not merge.
ADDED_LINES: frozenset[str] = frozenset({"escalation_decided"})

#: Fields added to an existing record after the golden file was written, per event
#: kind (or ``config`` for the run configuration), each with the value that means
#: "as before": a line or record that carries exactly that value is compared without
#: it.
ADDED_FIELDS: dict[str, dict[str, Any]] = {
    # The run's escalation binding, recorded in its configuration and on its first line.
    # Every run before the interface was, by construction, the rules binding.
    "config": {"escalation_backend": "rules"},
    "run_started": {"escalation_backend": "rules"},
    # The series records a session left: none, in every session the golden file recorded.
    "session_ended": {"series": {"records": [], "refused": [], "discarded": []}},
    # The proposed quantities held to the records they name: none, in every run recorded.
    "proposals_checked": {"series_checks": []},
}

#: Fields added after the golden file was written that carry new information, not a
#: default, so they are set aside whatever their value; their content is held by tests of
#: their own. ``proposed`` on the change check names the nodes an attempt proposed, which
#: the escalation decision's state reports (its tests check it against the proposals).
SET_ASIDE: dict[str, frozenset[str]] = {"proposals_checked": frozenset({"proposed"})}

#: Every source the loop could put on an item before the interface: the golden file
#: must show each of them, or it does not cover what it claims to.
SOURCES = {"repair_budget_exhausted", "review_blocked", "review_unavailable", "gate_escalation"}


@pytest.fixture(autouse=True)
def _runs_as_the_golden_file_was_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Build every run without the series writer in its run branch.

    The golden file was recorded before decomposition put the series writer into the run
    branch, and every tree compared here is a hash, so the one added file changes every tree
    of every run. What this file holds is the escalation binding, which the writer does not
    touch; the writer's copy into the run branch is held by the series tests. Nothing else
    about the runs is changed, and they are compared exactly as before.
    """
    monkeypatch.setattr(decompose, "series_library", dict)


#: The stand-in plan's nodes, by id, as the real gate reads them.
PLAN = {n["id"]: n for n in (POWER_BUS, *DRIVE_MODULE)}


def _without_a_bound(node_id: str) -> list[str]:
    """The plan node's quantities with a kind that the gate now has no range or envelope for."""
    from physgate.gate.bounds_table import load_bounds
    from physgate.gate.catalogue import kind_of

    bounds = load_bounds()
    found = []
    for name in PLAN[node_id]["quantities"]:
        kind = kind_of(name)
        if kind is not None and bounds.lookup(PLAN[node_id]["domain"], name, kind.name) is None:
            found.append(name)
    return sorted(found)


def _as_the_gate_now_judges(event: dict[str, Any]) -> dict[str, Any]:
    """A recorded gate result as the gate's later coverage rules write it, and nothing else.

    What changed after the golden file was written, all in the gate: its catalogue (so its
    digest); the stall-current headroom, which the unit check recorded as a relation no check
    judged and the power check now judges (the plan's motors fit their driver, so it writes
    nothing); and which quantities the magnitude check has a bound for. The stall current's
    range is gone, so it joins the quantities with no range; the temperature envelope holds
    the driver's two temperatures, so they leave that list. A quantity that leaves the list
    joins the count of those evaluated, and one that joins it leaves that count; the unchecked
    record itself is dropped when its list is empty. Which quantities have a bound is read
    from the gate's own tables, so the rule is the one sentence above, not a list of names.
    """
    if event.get("kind") not in ("gate_ran", "integration_gate_ran"):
        return event
    result = {**event["result"], "catalogue_sha256": catalogue_digest()}
    checks: list[dict[str, Any]] = []
    moved: dict[str, int] = {}
    for record in result["checks"]:
        if record["name"] == "units" and "is not one of the gate's checks" in record["message"]:
            continue
        unranged = record["name"] == "magnitude" and record["outcome"] == "unchecked"
        if unranged and record["node"] in PLAN and "no sourced range" in record["message"]:
            names = _without_a_bound(record["node"])
            was = list(record["details"]["quantities"])
            moved[record["scope"]] = moved.get(record["scope"], 0) + len(was) - len(names)
            if not names:
                continue
            record = {
                **record,
                "details": {**record["details"], "quantities": names},
                "message": f"{', '.join(names)} of {record['node']} have no sourced range "
                "for their domain and no envelope for their kind",
            }
        checks.append(record)
    for k, record in enumerate(checks):
        if record["name"] == "magnitude" and record["outcome"] == "pass":
            count = record["details"]["evaluated"] + moved.get(record["scope"], 0)
            checks[k] = {
                **record,
                "details": {**record["details"], "evaluated": count},
                "message": f"the magnitude check found nothing wrong ({count} evaluated)",
            }
    # A check that judged nothing and left a record unchecked no longer writes a pass.
    unchecked = {(r["name"], r["scope"]) for r in checks if r["outcome"] == "unchecked"}
    checks = [
        r
        for r in checks
        if not (
            r["outcome"] == "pass"
            and r["details"].get("evaluated") == 0
            and (r["name"], r["scope"]) in unchecked
        )
    ]
    return {**event, "result": {**result, "checks": checks}}


def _golden() -> dict[str, dict[str, list[Any]]]:
    loaded: dict[str, dict[str, list[Any]]] = json.loads(GOLDEN.read_text())
    return loaded


def _without_added(kind: str, line: dict[str, Any]) -> dict[str, Any]:
    added = ADDED_FIELDS.get(kind, {})
    aside = SET_ASIDE.get(kind, frozenset())
    return {k: v for k, v in line.items() if not (k in added and added[k] == v) and k not in aside}


def comparable(run: dict[str, list[Any]]) -> dict[str, list[Any]]:
    """A run's records with only the differences the interface is allowed removed."""
    out = {name: run[name] for name in RECORDS}
    out["config"] = [_without_added("config", c) for c in run["config"]]
    out["events"] = [
        _without_added(str(e["kind"]), {k: v for k, v in e.items() if k != "seq"})
        for e in run["events"]
        if e["kind"] not in ADDED_LINES
    ]
    return out


def differences(golden: dict[str, list[Any]], now: dict[str, list[Any]]) -> list[str]:
    """Where ``now`` departs from ``golden``: one line per record, the first index that differs."""
    found = []
    for name in RECORDS:
        before, after = golden[name], now[name]
        if before == after:
            continue
        index = next(
            (i for i, (b, a) in enumerate(zip(before, after, strict=False)) if b != a),
            min(len(before), len(after)),
        )
        b = before[index] if index < len(before) else "<absent>"
        a = after[index] if index < len(after) else "<absent>"
        found.append(f"{name}[{index}]: before {json.dumps(b)[:400]} now {json.dumps(a)[:400]}")
    return found


STAND_IN_NAMES = [n for n in scenario_names() if not n.startswith("real_gate")]


def test_the_golden_file_covers_every_scenario_every_mode_and_every_source() -> None:
    golden = _golden()
    assert sorted(golden) == sorted(scenario_names())
    assert len(STAND_IN_NAMES) >= len(STAND_INS)
    sources = {item["source"] for run in golden.values() for item in run["queue"]}
    assert sources == SOURCES
    modes = {run["config"][0]["gate_mode"] for run in golden.values()}
    assert modes == set(MODES)
    # A run with nothing in it would compare equal to anything empty.
    assert all(run["events"] and run["ledger"] for run in golden.values())


@pytest.mark.parametrize("name", STAND_IN_NAMES)
def test_every_path_reaches_the_queue_exactly_as_before(name: str, tmp_path: Path) -> None:
    golden = _golden()[name]
    now = build(name, tmp_path)
    assert differences(comparable(golden), comparable(now)) == []


def test_the_real_gate_s_three_modes_reach_the_queue_exactly_as_before(tmp_path: Path) -> None:
    from ui_three_mode_rig import three_mode_runs  # noqa: PLC0415 - real git and gate

    golden = _golden()
    built = three_mode_runs(tmp_path, tmp_path / "runs")
    assert len(built) == len(MODES)
    for run_dir in built:
        name = f"real_gate_three_modes/{run_dir.name.removeprefix('drive-')}"
        recorded = {
            **golden[name],
            "events": [_as_the_gate_now_judges(e) for e in golden[name]["events"]],
        }
        assert differences(comparable(recorded), comparable(records(run_dir))) == [], name


def test_the_comparison_sees_one_changed_queue_item_and_one_extra_event() -> None:
    golden = _golden()["review_rejects_three_times/on"]
    item = dict(golden["queue"][0])
    item["source"] = "review_blocked"
    changed = {**golden, "queue": [item]}
    assert [d.split(":")[0] for d in differences(comparable(golden), comparable(changed))] == [
        "queue[0]"
    ]
    extra = {**golden, "events": [*golden["events"], {**golden["events"][-1], "seq": 999}]}
    assert differences(comparable(golden), comparable(extra)) != []
