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
the golden file was written. Anything else that differs is a change in what the loop
did.
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

#: Event kinds the escalation interface writes, absent from the golden file by
#: construction. Empty until the interface exists.
ADDED_LINES: frozenset[str] = frozenset()

#: Fields added to an existing record after the golden file was written, per event
#: kind (or ``config`` for the run configuration), each with the value that means
#: "as before": a line or record that carries exactly that value is compared without
#: it. Empty until such a field exists.
ADDED_FIELDS: dict[str, dict[str, Any]] = {}

#: Fields added after the golden file was written that carry new information, not a
#: default, so they are set aside whatever their value; their content is held by tests of
#: their own. ``proposed`` on the change check names the nodes an attempt proposed, which
#: the escalation decision's state reports (its tests check it against the proposals).
SET_ASIDE: dict[str, frozenset[str]] = {"proposals_checked": frozenset({"proposed"})}

#: Every source the loop could put on an item before the interface: the golden file
#: must show each of them, or it does not cover what it claims to.
SOURCES = {"repair_budget_exhausted", "review_blocked", "review_unavailable", "gate_escalation"}


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
        assert differences(comparable(golden[name]), comparable(records(run_dir))) == [], name


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
