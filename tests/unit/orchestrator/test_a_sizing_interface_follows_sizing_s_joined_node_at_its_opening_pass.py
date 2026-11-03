"""A sizing-produced interface takes its joined sizing node's values at the opening pass (M-195).

The decomposition writes an interface's values as a forecast of sizing's work. At the change check
of sizing's opening attempt, while no other module has spawned, code derives the interface's next
revision from the attempt's own nodes joined to it (a ``constrains`` edge either way): each
quantity takes the value and unit those nodes hold under its name, with a source that names the
node and the attempt. Nothing else of the interface changes. The attempt is refused before the gate
when no node of its own is joined, when a joined node lacks a name, when two joined nodes disagree,
or when a unit is not of the interface's root units. Where nothing differs nothing is written. The
revision goes into the change check's scratch graph, so the gate judges it as the attempt's own;
the store writes it only as that derivation, by the interface's owner; the merge rewrites the run
branch's contract file; the divergence check names any other interface rewrite. No session writes
an interface: ``write_node`` still refuses, and a dispute of an interface quantity is refused,
naming the sizing node to dispute.

Each row reaches the build's new names through ``pytest.fail`` while they are missing, so a row
fails on an assertion before the build and passes after it.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.gate.graph import GraphView
from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.decompose import contracts_of, interface_contract
from physgate.orchestrator.dispute import DisputeError, parse
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.ports import ChangeCheck
from physgate.state.divergence import Duties
from physgate.state.protocol import REJECT_INTERFACE_IMMUTABLE
from physgate.state.schema import Node
from physgate.state.store import JOURNAL_NAME, Store, payload_digest

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
IFACE = "drive.motor"
JOINED = "sizing.drive"
PLAN_VALUES = {
    "stall_current": (1.44, "A"),
    "current_limit": (1.8, "A"),
    "no_load_speed": (61.261, "rad/s"),
}
SIZED_VALUES = {
    "stall_current": (1.35, "A"),
    "current_limit": (1.8, "A"),
    "no_load_speed": (60.505, "rad/s"),
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, env=_ENV, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


def need(module: str, name: str) -> Any:  # noqa: ANN401 - whatever the build names
    """``module.name``, or a failing assertion while the build has not made it."""
    try:
        found = getattr(importlib.import_module(module), name, None)
    except ImportError:
        found = None
    if found is None:
        pytest.fail(f"{module}.{name} is not built yet")
    return found


def quantities(values: dict[str, tuple[float | int, str]], by: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        name: {
            "value": v,
            "unit": u,
            "source": "the plan" if by == "plan" else "sized",
            "written_by": "sizing",
            **extra,
        }
        for name, (v, u) in values.items()
    }


def interface(
    values: dict[str, tuple[float | int, str]] = PLAN_VALUES,
    *,
    owner: str = "sizing",
    node_id: str = IFACE,
) -> dict[str, Any]:
    return {
        "id": node_id, "kind": "interface", "domain": "cross" if owner == "sizing" else owner,
        "owner_role": owner, "quantities": quantities(values, "plan"),
        "requirements": ["criterion 6"], "constrains": ["control.loop"], "model": None,
        "geometry_hash": "none", "updated": "2026-11-03",
    }  # fmt: skip


MASS = {"value": 0.36, "unit": "kg", "source": "scale", "written_by": "sizing"}


def sized(
    node_id: str = JOINED,
    values: dict[str, tuple[float | int, str]] = SIZED_VALUES,
    *,
    edges: tuple[str, ...] = (IFACE,),
) -> dict[str, Any]:
    return {
        "id": node_id, "kind": "component", "domain": "cross", "owner_role": "sizing",
        "quantities": {**quantities(values, "sizing"), "mass": MASS},
        "requirements": [], "constrains": list(edges), "model": None,
        "geometry_hash": "none", "updated": "2026-11-03",
    }  # fmt: skip


def store_of(root: Path, *payloads: dict[str, Any]) -> Path:
    store = Store(root)
    try:
        for payload in payloads:
            assert store.write_node(payload, str(payload["owner_role"])).accepted
    finally:
        store.close()
    return root


def attempt_run(tmp_path: Path, *proposals: dict[str, Any]) -> tuple[RunGit, str]:
    """A run whose sizing subtask ``z0`` committed ``proposals`` in its first attempt."""
    repo = tmp_path / "target"
    (repo / "modules" / "z0").mkdir(parents=True)
    (repo / "modules" / "z0" / "a.txt").write_text("0\n")
    for relative, text in contracts_of([Node.model_validate(interface())]).items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "specifications")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("z0")
    for payload in proposals:
        path = worktree / ".physgate" / "proposals" / f"{payload['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return run, commit_attempt(worktree, "z0", 1, "sess-1", repo=run.repo)


def checked(
    tmp_path: Path,
    store: Path,
    *proposals: dict[str, Any],
    follows: int | None = 1,
    role: str = "sizing",
) -> ChangeCheck:
    run, commit = attempt_run(tmp_path, *proposals)
    checker = GitChangeChecker(run, store, {"z0": "modules/z0"})
    if "follows" not in inspect.signature(checker.check).parameters:
        pytest.fail("the change check takes no follows argument yet")
    return checker.check("z0", commit, role, follows=follows)


def followed(check: ChangeCheck) -> tuple[Any, ...]:
    found: tuple[Any, ...] = getattr(check, "followed", ())
    return found


# --- the derivation at the change check ---------------------------------------------------------


def test_the_opening_attempt_s_joined_node_gives_the_interface_its_values(tmp_path: Path) -> None:
    store = store_of(tmp_path / "store", interface())
    check = checked(tmp_path, store, sized())
    assert check.refused_by is None
    (entry,) = followed(check)
    assert entry.interface == IFACE and tuple(entry.joined) == (JOINED,)
    after = entry.after
    assert {n: (q["value"], q["unit"]) for n, q in after["quantities"].items()} == SIZED_VALUES
    assert all(
        q["source"] == f"followed from {JOINED} at attempt 1" for q in after["quantities"].values()
    )
    assert all(q["written_by"] == "sizing" for q in after["quantities"].values())
    before = interface()
    assert {k: v for k, v in after.items() if k != "quantities"} == {
        k: v for k, v in before.items() if k != "quantities"
    }
    assert entry.payload_sha256 == payload_digest(after)
    assert {name for name, *_ in entry.changed()} == {"stall_current", "no_load_speed"}
    # The scratch graph holds the revision above the attempt's base, so the gate judges it as own.
    view = GraphView.read(Path(check.graph_root), base_revision=1)
    assert IFACE in view.own()
    assert view.nodes[IFACE].quantities["stall_current"].value == 1.35


def test_an_edge_from_the_interface_to_the_node_joins_them_too(tmp_path: Path) -> None:
    payload = interface()
    payload["constrains"] = ["control.loop", JOINED]
    store = store_of(tmp_path / "store", payload)
    check = checked(tmp_path, store, sized(edges=()))
    assert check.refused_by is None and [e.interface for e in followed(check)] == [IFACE]


def test_an_attempt_not_due_to_follow_derives_nothing(tmp_path: Path) -> None:
    store = store_of(tmp_path / "store", interface())
    check = checked(tmp_path, store, sized(), follows=None)
    assert check.refused_by is None and followed(check) == ()
    assert IFACE not in GraphView.read(Path(check.graph_root), base_revision=1).own()


@pytest.mark.parametrize(
    ("proposals", "said"),
    [
        pytest.param((sized(edges=()),), "joined", id="no-joined-node"),
        pytest.param(
            (sized(values={k: v for k, v in SIZED_VALUES.items() if k != "no_load_speed"}),),
            "no_load_speed",
            id="a-joined-node-lacks-a-name",
        ),
        pytest.param(
            (sized(), sized("sizing.drive_b", {**SIZED_VALUES, "stall_current": (1.5, "A")})),
            "stall_current",
            id="two-joined-nodes-disagree",
        ),
        pytest.param(
            (sized(values={**SIZED_VALUES, "stall_current": (1.35, "V")}),),
            "stall_current",
            id="a-unit-not-of-the-interface-s-root-units",
        ),
    ],
)
def test_an_interface_sizing_cannot_follow_refuses_the_attempt_before_the_gate(
    tmp_path: Path, proposals: tuple[dict[str, Any], ...], said: str
) -> None:
    store = store_of(tmp_path / "store", interface())
    check = checked(tmp_path, store, *proposals)
    assert str(check.refused_by) == "interface"
    assert check.subject == IFACE
    assert said in str(check.reason) and IFACE in str(check.reason)
    assert followed(check) == ()


def test_two_joined_nodes_that_agree_are_followed_from_the_first(tmp_path: Path) -> None:
    store = store_of(tmp_path / "store", interface())
    other = sized("sizing.drive_b", {**SIZED_VALUES, "stall_current": (1350, "mA")})
    check = checked(tmp_path, store, sized(), other)
    assert check.refused_by is None
    (entry,) = followed(check)
    assert tuple(entry.joined) == (JOINED, "sizing.drive_b")
    assert (
        entry.after["quantities"]["stall_current"]["value"],
        entry.after["quantities"]["stall_current"]["unit"],
    ) == (1.35, "A")


def test_where_nothing_differs_nothing_is_followed_or_written(tmp_path: Path) -> None:
    store = store_of(tmp_path / "store", interface())
    check = checked(tmp_path, store, sized(values=PLAN_VALUES))
    assert check.refused_by is None and followed(check) == ()
    assert IFACE not in GraphView.read(Path(check.graph_root), base_revision=1).own()


def test_an_interface_another_role_owns_is_never_followed(tmp_path: Path) -> None:
    owned = interface(owner="control", node_id="balance.controller")
    store = store_of(tmp_path / "store", owned)
    check = checked(tmp_path, store, sized(edges=("balance.controller",)))
    assert check.refused_by is None and followed(check) == ()
    assert "balance.controller" not in GraphView.read(Path(check.graph_root), base_revision=1).own()


def test_a_dropped_series_reference_lets_no_sealed_series_check_pass_falsely(
    tmp_path: Path,
) -> None:
    derive = need("physgate.orchestrator.follow", "derive")
    series = {"record": "sizing_speed", "extract": "final", "trace": "ground_speed"}
    node = sized()
    node["quantities"]["no_load_speed"]["series"] = series
    after = derive(interface(), {JOINED: node}, "sizing", 1)
    assert "series" not in after["quantities"]["no_load_speed"]
    # The joined node still names a record its attempt never sealed: the series check refuses the
    # attempt, and nothing is followed from it.
    store = store_of(tmp_path / "store", interface())
    check = checked(tmp_path, store, node)
    assert check.refused_by == "series" and followed(check) == ()


# --- the store writes an interface only as that derivation ---------------------------------------


def test_the_store_writes_an_interface_only_as_its_owner_s_derivation(tmp_path: Path) -> None:
    derive = need("physgate.orchestrator.follow", "derive")
    root = store_of(tmp_path / "store", interface(), sized())
    after = derive(interface(), {JOINED: sized()}, "sizing", 1)
    store = Store(root)
    try:
        follow = getattr(store, "follow_interface", None)
        if follow is None:
            pytest.fail("Store.follow_interface is not built yet")
        # write_node is unchanged: an interface is still refused to it.
        assert store.write_node(after, "sizing").reason == REJECT_INTERFACE_IMMUTABLE
        forged = json.loads(json.dumps(after))
        forged["quantities"]["stall_current"]["value"] = 1.2
        edged = {**after, "constrains": []}
        for payload, actor, joined in (
            (forged, "sizing", (JOINED,)),
            (edged, "sizing", (JOINED,)),
            (after, "control", (JOINED,)),
            (after, "sizing", ("sizing.unjoined",)),
        ):
            refused = follow(payload, actor, joined)
            assert not refused.accepted and refused.reason == "interface_not_followed"
        done = follow(after, "sizing", (JOINED,))
        assert done.accepted and done.revision == 3
    finally:
        store.close()
    reopened = Store(root)
    try:
        assert reopened.read_node(IFACE) == after
    finally:
        reopened.close()
    last = json.loads((root / JOURNAL_NAME).read_text().splitlines()[-1])
    assert (last["op"], last["version"], last["node_id"]) == ("write", 2, IFACE)


def test_divergence_names_an_interface_rewrite_other_than_the_followed_one(tmp_path: Path) -> None:
    run = importlib.import_module("physgate.state.divergence").divergence
    if "admitted" not in inspect.signature(run).parameters:
        pytest.fail("divergence takes no admitted revisions yet")
    root = store_of(tmp_path / "store", interface())
    rewritten = json.loads(json.dumps(interface(SIZED_VALUES)))
    line = {"rev": 2, "op": "write", "node_id": IFACE, "version": 2, "payload": rewritten}
    with (root / JOURNAL_NAME).open("ab") as journal:
        journal.write(json.dumps(line, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    store = Store(root)
    duties = Duties(cross_nodes=("sizing",), completion=("integration",))
    try:
        named = run(store, store.diff(1), "sizing", duties)
        assert [(d.node_id, d.reason) for d in named] == [(IFACE, "interface_rewritten")]
        assert run(store, store.diff(1), "sizing", duties, admitted=frozenset({2})) == []
    finally:
        store.close()


# --- the merge rewrites the contract file -


def test_the_merge_rewrites_the_run_branch_s_contract_file(tmp_path: Path) -> None:
    derive = need("physgate.orchestrator.follow", "derive")
    run, commit = attempt_run(tmp_path, sized())
    after = derive(interface(), {JOINED: sized()}, "sizing", 1)
    contracts = contracts_of([Node.model_validate(after)])
    merger = GitMerger(run, removal_timeout_s=60)
    if "contracts" not in inspect.signature(merger.merge).parameters:
        pytest.fail("the merge takes no contracts yet")
    merged = merger.merge("z0", 1, commit, "Merge subtask z0, attempt 1\n", contracts=contracts)
    shown = _git(run.repo, "show", f"{merged}:{interface_contract(IFACE)}")
    assert shown + "\n" == contracts[interface_contract(IFACE)]
    assert _git(run.repo, "rev-parse", f"{merged}^2") == commit


# --- no session writes or disputes an interface -


def test_a_dispute_of_an_interface_quantity_is_refused_naming_the_sizing_node_to_dispute() -> None:
    nodes = {IFACE: interface(), JOINED: sized()}
    body = json.dumps({"value": 0.07, "unit": "N*m", "reason": "the controller needs it"}).encode()
    with pytest.raises(DisputeError) as refused:
        parse(f".physgate/disputes/{IFACE}.stall_current.json", body, "control", nodes)
    assert "interface" in str(refused.value)
    assert JOINED in str(refused.value)


# --- the reviewer is shown the contract change ------------------------------------------------


def test_sizing_s_reviewer_is_shown_each_changed_interface_quantity_old_and_new() -> None:
    follow = need("physgate.orchestrator.follow", "follow")
    text_of = need("physgate.reviewers.packet", "followed_text")
    entry = follow(interface(), {JOINED: sized()}, "sizing", 2)
    text = text_of((entry,)).decode("utf-8")
    assert f"{IFACE}.stall_current: 1.44 A -> 1.35 A" in text
    assert f"{IFACE}.no_load_speed: 61.261 rad/s -> 60.505 rad/s" in text
    assert JOINED in text and "attempt 2" in text
    # Unchanged quantities get no line, and no session's source text is quoted.
    assert "current_limit" not in text and "sized" not in text
    fields = need("physgate.orchestrator.protocols", "Artefact").model_fields
    assert "followed" in fields
