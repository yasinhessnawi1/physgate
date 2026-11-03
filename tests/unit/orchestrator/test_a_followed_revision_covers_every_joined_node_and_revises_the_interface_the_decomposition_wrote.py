"""A followed revision covers every joined node and revises the interface as it was written (M-195).

The store's own method writes an interface's followed revision only as the copy from every node
of the owner role joined to the interface in its heads: a revision that names some of them, and
leaves out one that agrees or one that disagrees, is refused. The decomposition records, for the
role that owns the cross nodes, the digest of each interface that role produces as the store holds
it, and nothing where that role produces none. Replay holds a followed line to both: the role of
the change check that follows is the one recorded, so a domain module that comes first and follows
its own interface is refused, and the interface a followed revision revises is the one the
decomposition wrote, so a line whose interface before and revision were both edited is refused.
The loop asks nothing to follow in a run whose decomposition recorded no such role.

Each row reaches the build's new names through ``pytest.fail`` while they are missing, so a row
fails on an assertion before the build and passes after it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbitration_runs import entry, events_of, refusal  # noqa: E402
from test_a_followed_interface_is_written_at_the_merge_and_recomputed_on_replay import (  # noqa: E402
    IFACE,
    JOINED,
    Following,
    _edited,
    _honest,
    asked,
    rig_of,
    run,
)
from test_a_sizing_interface_follows_sizing_s_joined_node_at_its_opening_pass import (  # noqa: E402
    SIZED_VALUES,
    interface,
    sized,
    store_of,
)
from test_sizing_opens_and_closes_the_domain_work_and_integration_ends_it import (  # noqa: E402
    BOTH,
    BUDGET,
    DRIVE,
    FW,
    NODE,
    decomposed,
    integrated,
    sizing_registered,  # noqa: F401 - the autouse fixture: sizing registered
    started,
)

from physgate import roles  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    ProposalsChecked,
    StageEntered,
    WriteIntended,
    parse_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402
from physgate.roles import CrossCuttingRole  # noqa: E402
from physgate.state.store import (  # noqa: E402
    REJECT_INTERFACE_NOT_FOLLOWED,
    Store,
    followed_payload,
    payload_digest,
)

B = "sizing.drive_b"
#: Why replay refuses a followed line whose change check is not the recorded role's.
NOT_THE_ROLE = (
    "the {role} role's change check follows an interface: only the role the decomposition "
    "recorded as producing the interfaces that follow does"
)
#: Why replay refuses a followed line whose interface is not the one the decomposition wrote.
NOT_AS_WRITTEN = (
    f"the followed revision of {IFACE} revises another interface than the one the decomposition "
    "wrote"
)


def _follow(root: Path, payload: dict[str, Any], joined: tuple[str, ...]) -> Any:  # noqa: ANN401
    """The store's answer; a raise, where a refusal is due, fails the row and never errors it."""
    store = Store(root)
    try:
        return store.follow_interface(payload, "sizing", joined)
    except Exception as exc:  # noqa: BLE001 - any escape is this row's failure
        pytest.fail(f"the store raised: {type(exc).__name__}: {exc}")
    finally:
        store.close()


def _started(root: Path, plan: Any) -> Path:  # noqa: ANN401 - the plan of either form
    """The run directory of a run started from ``plan``; a start that raises fails the row."""
    try:
        run_dir, _ = started(root, plan, BOTH)
    except Exception as exc:  # noqa: BLE001 - any escape is this row's failure
        pytest.fail(f"the run did not start: {type(exc).__name__}: {exc}")
    return run_dir


# --- the store: every joined node, never some of them -------------------------------------------


def test_the_store_refuses_a_revision_that_leaves_out_a_joined_node_that_disagrees(
    tmp_path: Path,
) -> None:
    # The change check refuses the pair, since they disagree; the store refuses the revision
    # copied from the one that names only it.
    a, b = sized(), sized(B, {**SIZED_VALUES, "stall_current": (2.5, "A")})
    root = store_of(tmp_path / "store", interface(), a, b)
    refused = _follow(root, followed_payload(interface(), [b], "sizing", 1), (B,))
    assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED


def test_the_store_refuses_a_revision_that_leaves_out_a_joined_node_that_agrees(
    tmp_path: Path,
) -> None:
    a, b = sized(), sized(B)
    root = store_of(tmp_path / "store", interface(), a, b)
    refused = _follow(root, followed_payload(interface(), [a], "sizing", 1), (JOINED,))
    assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED


def test_the_store_takes_the_revision_copied_from_every_joined_node(tmp_path: Path) -> None:
    # Written out of id order, beside a node not joined and another interface that is: the
    # joined set is the role's non-interface nodes with an edge, in id order.
    a, b = sized(), sized(B)
    other = {**interface(node_id="drive.other"), "constrains": [IFACE]}
    loose = sized("sizing.loose", edges=())
    root = store_of(tmp_path / "store", interface(), b, a, loose, other)
    taken = _follow(root, followed_payload(interface(), [a, b], "sizing", 1), (JOINED, B))
    assert taken.accepted and taken.revision == 6


def test_the_store_refuses_a_revision_naming_no_joined_node_where_none_is_joined(
    tmp_path: Path,
) -> None:
    loose = sized("sizing.loose", edges=())
    root = store_of(tmp_path / "store", interface(), loose)
    refused = _follow(root, followed_payload(interface(), [loose], "sizing", 1), ())
    assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED


def test_the_store_refuses_a_revision_beside_a_second_joined_node_that_lacks_a_name(
    tmp_path: Path,
) -> None:
    short = {k: v for k, v in SIZED_VALUES.items() if k != "no_load_speed"}
    a, b = sized(), sized(B, short)
    root = store_of(tmp_path / "store", interface(), a, b)
    refused = _follow(root, followed_payload(interface(), [a, b], "sizing", 1), (JOINED, B))
    assert not refused.accepted and refused.reason == REJECT_INTERFACE_NOT_FOLLOWED


# --- the decomposition records what follows, and from what ---------------------------------------

#: An interface sizing produces, beside the control one the fixtures plan.
PRODUCED: dict[str, Any] = {
    **NODE,
    "id": "iface.budget",
    "domain": "cross",
    "owner_role": "sizing",
    "quantities": {"i": {"value": 2, "unit": "A", "source": "brief", "written_by": "sizing"}},
}
TWO = {
    "interface_nodes": [NODE, PRODUCED],
    "interface_consumers": [
        {"interface": "iface.drive", "consumers": ["fw"]},
        {"interface": "iface.budget", "consumers": ["drive"]},
    ],
}


def _recorded(run_dir: Path) -> Any:  # noqa: ANN401 - whatever the build names
    line = decomposed(run_dir)
    if "followable" not in type(line).model_fields:
        pytest.fail("the decomposition's line records no followable interfaces yet")
    return line.followable


def test_the_decomposition_records_each_interface_sizing_produces_by_its_digest(
    tmp_path: Path,
) -> None:
    run_dir = _started(tmp_path, integrated([BUDGET, DRIVE, FW], **TWO))
    recorded = _recorded(run_dir)
    store = Store(run_dir / "store")
    try:
        held = payload_digest(store.read_node("iface.budget"))
    finally:
        store.close()
    assert recorded is not None and recorded.role == "sizing"
    assert dict(recorded.payload_sha256) == {"iface.budget": held}


def test_a_decomposition_whose_sizing_produces_no_interface_records_none(tmp_path: Path) -> None:
    run_dir = _started(tmp_path, integrated([BUDGET, DRIVE, FW]))
    assert getattr(decomposed(run_dir), "followable", None) is None
    written = next(
        raw for raw in (run_dir / "events.jsonl").read_text().splitlines() if '"decomposed"' in raw
    )
    assert "followable" not in json.loads(written)


def test_a_decomposition_with_two_owners_of_the_cross_nodes_records_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = CrossCuttingRole(name="sizing_b", architecture="ARCH-051", owns="cross_nodes")
    monkeypatch.setitem(roles.ROLES, second.name, second)
    run_dir = _started(tmp_path, integrated([BUDGET, DRIVE, FW], **TWO))
    assert getattr(decomposed(run_dir), "followable", None) is None


@pytest.mark.parametrize(
    ("digests", "said"),
    [
        pytest.param(
            {"other.iface": "0" * 64},
            "a followable interface is an interface node of the plan",
            id="an-interface-not-its-own",
        ),
        pytest.param({}, "at least 1 item", id="no-interface"),
    ],
)
def test_a_decomposed_line_whose_followable_interfaces_are_not_some_of_its_own_is_refused(
    tmp_path: Path, digests: dict[str, str], said: str
) -> None:
    def elsewhere(line: dict[str, Any]) -> dict[str, Any]:
        if line.get("kind") == "decomposed":
            line["followable"] = {"role": "sizing", "payload_sha256": digests}
        return line

    with pytest.raises(CorruptEventLogError) as refused:
        _edited(_honest(tmp_path), elsewhere)
    assert said in str(refused.value.context.get("reason", ""))


# --- replay: the recorded role follows, and revises the interface as written ---------------------


def _forge_before(line: dict[str, Any]) -> dict[str, Any]:
    """The interface before and its revision both given an edge and a requirement; digests agree."""
    if line.get("kind") == "proposals_checked" and line.get("followed"):
        found = line["followed"][0]
        for side in ("before", "after"):
            found[side]["constrains"] = ["control.secret"]
            found[side]["requirements"] = ["R-forged"]
        found["payload_sha256"] = payload_digest(found["after"])
        _forge_before.digest = found["payload_sha256"]  # type: ignore[attr-defined]
    if line.get("kind") == "write_intended" and line.get("node_id") == IFACE:
        line["payload_sha256"] = _forge_before.digest  # type: ignore[attr-defined]
    return line


def test_replay_refuses_a_followed_revision_of_an_interface_the_decomposition_did_not_write(
    tmp_path: Path,
) -> None:
    assert refusal(_edited(_honest(tmp_path), _forge_before)) == NOT_AS_WRITTEN


def _a_domain_follows(line: dict[str, Any]) -> dict[str, Any]:
    """Sizing's opening subtask made a domain's, every line of it, with each digest agreed.

    The domain module comes first and follows an interface it produces: the record is the
    honest run's, its roles renamed on z0's lines alone.
    """

    def renamed(value: Any) -> Any:  # noqa: ANN401 - a line's own fields
        if isinstance(value, dict):
            return {k: renamed(v) for k, v in value.items()}
        if isinstance(value, list):
            return [renamed(v) for v in value]
        return "electrical" if value == "sizing" else value

    if line.get("subtask_id") != "z0":
        return line
    line = renamed(line)
    if line.get("kind") == "proposals_checked" and line.get("followed"):
        found = line["followed"][0]
        found["payload_sha256"] = payload_digest(found["after"])
        _a_domain_follows.digests = {  # type: ignore[attr-defined]
            IFACE: found["payload_sha256"],
            **{p["id"]: payload_digest(p) for p in found["joined_payloads"]},
        }
    if line.get("kind") == "write_intended":
        line["payload_sha256"] = _a_domain_follows.digests[line["node_id"]]  # type: ignore[attr-defined]
    return line


def test_replay_refuses_a_domain_module_that_comes_first_and_follows_its_own_interface(
    tmp_path: Path,
) -> None:
    assert refusal(_edited(_honest(tmp_path), _a_domain_follows)) == NOT_THE_ROLE.format(
        role="electrical"
    )


def test_replay_refuses_a_followed_line_where_the_decomposition_recorded_no_role(
    tmp_path: Path,
) -> None:
    def unrecorded(line: dict[str, Any]) -> dict[str, Any]:
        if line.get("kind") == "decomposed":
            line.pop("followable", None)
        return line

    assert refusal(_edited(_honest(tmp_path), unrecorded)) == NOT_THE_ROLE.format(role="sizing")


# --- the loop: nothing is due but to the recorded role ---------------------------------------


def test_a_run_whose_decomposition_recorded_no_followable_interface_asks_nothing_to_follow(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run")
    try:
        kind = run(rig, recorded=False)
    except Exception as exc:  # noqa: BLE001 - any escape is this row's failure
        pytest.fail(f"the run did not end: {type(exc).__name__}: {exc}")
    assert kind == "done"
    assert asked(rig) == [("z0", None), ("s1", None), ("zc", None)]


def test_a_domain_s_opening_subtask_that_spawned_first_is_due_to_follow_nothing(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path / "run")
    assert isinstance(rig.changes, Following)
    rig.changes.graph.writes["s1"] = [{**sized("electrical.drive"), "owner_role": "electrical"}]
    late = [entry("s1", "electrical"), entry("z0", "sizing"), entry("zc", "sizing", "modules/z0")]
    assert run(rig, late) == "done"
    events = events_of(rig)
    # The record as it stood at s1's change check: s1 alone has spawned.
    at = next(
        i for i, e in enumerate(events) if isinstance(e, ProposalsChecked) and e.subtask_id == "s1"
    )
    state = replay(events[:at])
    spawned = [e.subtask_id for e in events[:at] if isinstance(e, StageEntered)]
    assert set(spawned) == {"s1"}
    assert state.follows("s1") is None
    assert not any(
        isinstance(e, WriteIntended) and e.node_id == IFACE and e.subtask_id == "s1" for e in events
    )


def test_the_honest_run_still_replays_with_its_followed_line(tmp_path: Path) -> None:
    events = _honest(tmp_path)
    assert refusal(events) is None
    assert parse_events(
        b"".join(e.model_dump_json().encode() + b"\n" for e in events), log="events.jsonl"
    )
