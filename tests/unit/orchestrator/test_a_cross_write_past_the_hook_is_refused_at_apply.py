"""A proposal the hook refuses is refused again when the orchestrator applies it, for one reason.

The hook checks a node proposal as the Write or Edit tool writes it. A proposal can still
reach the attempt commit without passing it: where the OS layer is absent, a shell command
can put a file into the proposals directory by a route the text hooks do not see. So the
orchestrator reads every proposal from the commit, with the role the plan gave the
subtask and never one the proposal names, and refuses everything the hook refuses:

- a node of the ``cross`` domain from any role but the one the register names as owning
  the cross nodes, and a node of a domain from that role; while the register names no
  owner every cross node is refused, and while it names two, every node but an interface;
- a new interface node from any session: interface nodes are written from the plan;
- any node from the role that owns completion, whose one write is its declaration.

Each owner is looked up in the register by what it owns, through the lookup that counts
the owners itself. The rules run in the hook's order, so a proposal with two faults is
refused for the earlier one, as the hook refuses it. The table below is every ownership
case of the hook's own tests, and each is run through both: the hook's reason and the
orchestrator's must both be the one the case names.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import event, make_store, write_config  # noqa: E402
from hook_helpers import node as hook_node  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.hooks import graph  # noqa: E402
from physgate.hooks.config import HookInput  # noqa: E402
from physgate.orchestrator.apply import (  # noqa: E402
    GitChangeChecker,
    ProposalRefusedError,
    StoreKeeper,
    read_proposals,
)
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.roles import CrossCuttingRole  # noqa: E402
from physgate.state.protocol import (  # noqa: E402
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
)
from physgate.state.store import Store  # noqa: E402

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

ALLOW = "allow"
INVALID = "invalid"
INTERFACE = "iface.control.p01"
#: A second owner of the cross nodes, and another owner of completion, for registers
#: patched past the check the register makes when it is built.
BALLAST = CrossCuttingRole(name="ballast", architecture="ARCH-051", owns="cross_nodes")
CLOSER = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
DOMAINS = ("mechanical", "electrical", "control", "firmware")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def node(node_id: str, owner: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """A complete, legal node, as the hook tests write one."""
    return hook_node(node_id, owner, **fields)


def bare(payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` with a bare number for a quantity."""
    return {**payload, "quantities": {"stall_current": 2.4}}


def shadowing(payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` naming a quantity under a misspelling of one a relation reads."""
    owner = str(payload["owner_role"])
    entry = {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": owner}
    return {**payload, "quantities": {"stall_currnt": entry}}


# --- the registers the cases run under -------------------------------------------------------


def _shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as the harness ships it: no owner of the cross nodes yet."""


def _sizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _ballast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)


def _two_cross_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    _sizing(monkeypatch)
    _ballast(monkeypatch)


def _closer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(roles.ROLES, roles.INTEGRATION.name)
    monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)


def _no_completion_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(roles.ROLES, roles.INTEGRATION.name)


def _two_completion_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)


Register = Callable[[pytest.MonkeyPatch], None]

#: (session role, the register, the proposal, the reason both layers give: or "allow").
Case = tuple[str, Register, dict[str, Any], str]

CROSS_CASES: dict[str, Case] = {
    **{
        f"a domain role's new cross {kind}, sizing registered": (
            "control",
            _sizing,
            node("control.motor_current", "control", domain="cross", kind=kind),
            graph.CROSS_NODE,
        )
        for kind in ("component", "module", "requirement")
    },
    **{
        f"a domain role's new cross {kind}, as shipped": (
            "control",
            _shipped,
            node("control.motor_current", "control", domain="cross", kind=kind),
            graph.CROSS_NODE,
        )
        for kind in ("component", "module", "requirement")
    },
    "a domain role turning its own node cross": (
        "control",
        _sizing,
        node("control.loop", "control", domain="cross"),
        graph.CROSS_NODE,
    ),
    **{
        f"sizing's new {domain} node": (
            "sizing",
            _sizing,
            node("sizing.bracket", "sizing", domain=domain),
            graph.CROSS_NODE,
        )
        for domain in DOMAINS
    },
    "sizing turning its own cross node into a domain node": (
        "sizing",
        _sizing,
        node("sizing.motor_left", "sizing", domain="electrical"),
        graph.CROSS_NODE,
    ),
    "sizing's cross node where the register names another owner": (
        "sizing",
        _ballast,
        node("sizing.motor_right", "sizing"),
        graph.CROSS_NODE,
    ),
    "sizing's cross node where no registered role owns the cross nodes": (
        "sizing",
        _shipped,
        node("sizing.motor_right", "sizing"),
        graph.CROSS_NODE,
    ),
    "a domain role's cross node where no registered role owns the cross nodes": (
        "control",
        _shipped,
        node("control.motor_right", "control", domain="cross"),
        graph.CROSS_NODE,
    ),
    "sizing's cross node where the register names two owners": (
        "sizing",
        _two_cross_owners,
        node("sizing.motor_right", "sizing"),
        graph.CROSS_NODE,
    ),
    "the other owner's cross node where the register names two": (
        "ballast",
        _two_cross_owners,
        node("ballast.mass", "ballast"),
        graph.CROSS_NODE,
    ),
    "a domain role's domain node where the register names two owners": (
        "control",
        _two_cross_owners,
        node("control.gain", "control"),
        graph.CROSS_NODE,
    ),
}

INTERFACE_CASES: dict[str, Case] = {
    f"a new interface of the {domain} domain from {role}": (
        role,
        _sizing,
        node(f"iface.{role}.p09", role, kind="interface", domain=domain, quantities={}),
        graph.INTERFACE_CREATION,
    )
    for role, domain in (
        ("control", "cross"),
        ("control", "control"),
        ("sizing", "cross"),
        ("integration", "cross"),
    )
}

COMPLETION_CASES: dict[str, Case] = {
    **{
        f"the completion owner's {domain} node": (
            "integration",
            _shipped,
            node("integration.check", "integration", domain=domain),
            graph.COMPLETION_OWNER_NODE,
        )
        for domain in DOMAINS
    },
    "the completion owner found by what it owns, not by its name": (
        "closer",
        _closer,
        node("closer.check", "closer", domain="control"),
        graph.COMPLETION_OWNER_NODE,
    ),
    "a domain role's node where the register names two owners of completion": (
        "control",
        _two_completion_owners,
        node("control.gain", "control"),
        graph.COMPLETION_OWNER_NODE,
    ),
}

#: Two faults at once, and the rules that come before the new ones: the earlier rule's reason.
ORDER_CASES: dict[str, Case] = {
    "another role's node": (
        "control",
        _sizing,
        node("sizing.motor_left", "sizing"),
        REJECT_CROSS_ROLE,
    ),
    "a new node naming another role as its owner": (
        "control",
        _sizing,
        node("control.motor_right", "sizing"),
        REJECT_CROSS_ROLE,
    ),
    "a new domain node naming the owner of the cross nodes, from a domain role": (
        "control",
        _sizing,
        node("control.bracket", "sizing", domain="electrical"),
        REJECT_CROSS_ROLE,
    ),
    "an owner change": (
        "control",
        _sizing,
        node("control.loop", "sizing", domain="control"),
        graph.OWNER_CHANGE,
    ),
    "a kind change": (
        "control",
        _sizing,
        node("control.loop", "control", kind="module"),
        graph.KIND_CHANGE,
    ),
    "a cross write that is also a kind change": (
        "control",
        _sizing,
        node("control.loop", "control", kind="module", domain="cross"),
        graph.KIND_CHANGE,
    ),
    "an existing node turned into an interface": (
        "control",
        _sizing,
        node("control.loop", "control", kind="interface", domain="cross"),
        graph.KIND_CHANGE,
    ),
    "an existing interface node, by its producer": (
        "control",
        _sizing,
        node(INTERFACE, "control", kind="interface", domain="cross"),
        REJECT_INTERFACE_IMMUTABLE,
    ),
    "an existing interface node with a bare number": (
        "control",
        _sizing,
        bare(node(INTERFACE, "control", kind="interface", domain="cross")),
        REJECT_INTERFACE_IMMUTABLE,
    ),
    "a cross node with a bare number": (
        "control",
        _sizing,
        bare(node("control.motor_current", "control", domain="cross")),
        graph.CROSS_NODE,
    ),
    "a new interface with a bare number": (
        "control",
        _sizing,
        bare(node("iface.control.p09", "control", kind="interface", domain="cross")),
        graph.INTERFACE_CREATION,
    ),
    "sizing's domain node with a bare number": (
        "sizing",
        _sizing,
        bare(node("sizing.bracket", "sizing", domain="electrical")),
        graph.CROSS_NODE,
    ),
    "a cross node naming a shadowing quantity": (
        "control",
        _sizing,
        shadowing(node("control.motor_current", "control", domain="cross")),
        graph.CROSS_NODE,
    ),
    "the completion owner's new interface": (
        "integration",
        _shipped,
        node("iface.integration.p09", "integration", kind="interface", quantities={}),
        graph.INTERFACE_CREATION,
    ),
    "a cross node whose id is longer than an id may be": (
        "control",
        _sizing,
        node("control." + "m" * 130, "control", domain="cross"),
        INVALID,
    ),
    "a bare number alone": (
        "control",
        _sizing,
        bare(node("control.gain", "control")),
        REJECT_MISSING_UNIT,
    ),
    "a shadowing quantity alone": (
        "control",
        _sizing,
        shadowing(node("control.gain", "control")),
        graph.SHADOWED_QUANTITY,
    ),
    "a bare number beside a shadowing name": (
        "control",
        _sizing,
        {
            **node("control.gain", "control"),
            "quantities": {
                "stall_currnt": {"value": 2.4, "unit": "A", "source": "d", "written_by": "control"},
                "current": 2.4,
            },
        },
        REJECT_MISSING_UNIT,
    ),
    "a node invalid elsewhere": (
        "control",
        _sizing,
        node("control.gain", "control", requirements="none"),
        INVALID,
    ),
    "a node invalid elsewhere, naming a shadowing quantity": (
        "control",
        _sizing,
        shadowing(node("control.gain", "control", requirements="none")),
        graph.SHADOWED_QUANTITY,
    ),
}

LANDS: dict[str, Case] = {
    "a domain role's own domain node": (
        "control",
        _sizing,
        node("control.gain", "control"),
        ALLOW,
    ),
    "a domain role's own node, rewritten": (
        "control",
        _sizing,
        node("control.loop", "control", constrains=["x.y"]),
        ALLOW,
    ),
    "a domain role's domain node, as shipped": (
        "control",
        _shipped,
        node("control.gain", "control"),
        ALLOW,
    ),
    "sizing's new cross node": ("sizing", _sizing, node("sizing.motor_right", "sizing"), ALLOW),
    "sizing's own cross node, rewritten": (
        "sizing",
        _sizing,
        node("sizing.motor_left", "sizing", constrains=["x.y"]),
        ALLOW,
    ),
    "the owner the register names, whatever its name": (
        "ballast",
        _ballast,
        node("ballast.mass", "ballast"),
        ALLOW,
    ),
    "integration's node where another role owns completion": (
        "integration",
        _closer,
        node("integration.check", "integration", domain="control"),
        ALLOW,
    ),
    "integration's node where no role owns completion": (
        "integration",
        _no_completion_owner,
        node("integration.check", "integration", domain="control"),
        ALLOW,
    ),
}

EVERY_CASE: dict[str, Case] = {
    **CROSS_CASES,
    **INTERFACE_CASES,
    **COMPLETION_CASES,
    **ORDER_CASES,
    **LANDS,
}


# --- the two layers ---------------------------------------------------------------------------


def _store(root: Path) -> Path:
    """A store holding a domain node, a cross node and an interface, written by the store."""
    make_store(
        root,
        node("control.loop", "control"),
        node("sizing.motor_left", "sizing"),
        node(INTERFACE, "control", kind="interface", domain="cross", quantities={}),
    )
    return root


def through_the_hook(tmp_path: Path, store: Path, role: str, payload: dict[str, Any]) -> str:
    """The hook's reason for refusing ``payload`` from a ``role`` session, or ``allow``."""
    home = tmp_path / "hook" / role
    home.mkdir(parents=True, exist_ok=True)
    _, _, config = write_config(home, role=role, store_root=str(store))
    target = Path(config.worktree) / graph.PROPOSALS_DIR / f"{payload['id']}.json"
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(payload)},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    if decision.allow:
        return ALLOW
    found = re.search(r"refused \(([a-z_]+)\)", decision.reason or "")
    assert found is not None, decision.reason
    return found.group(1)


def _attempt(tmp_path: Path, payloads: dict[str, dict[str, Any]]) -> tuple[Path, str, str]:
    """A repository whose second commit adds ``payloads`` as proposals: (repo, base, commit)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "m.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    base = _git(repo, "rev-parse", "HEAD")
    for name, payload in payloads.items():
        path = repo / ".physgate" / "proposals" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "proposals")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def through_apply(tmp_path: Path, store: Path, role: str, payload: dict[str, Any]) -> str:
    """The orchestrator's reason for refusing ``payload`` in a ``role`` attempt, or ``allow``.

    The proposals are read from the commit under the plan's role, then written on a scratch
    copy of the graph under the store's own guards, as the change check does.
    """
    repo, base, commit = _attempt(tmp_path / "apply", {str(payload["id"]): payload})
    try:
        proposals = read_proposals(repo, base, commit, store, role=role)
    except ProposalRefusedError as exc:
        return exc.reason
    scratch = tmp_path / "apply" / "scratch"
    scratch.mkdir()
    (scratch / "journal.jsonl").write_bytes((store / "journal.jsonl").read_bytes())
    copy = Store(scratch)
    try:
        for proposal in proposals:
            result = copy.write_node(proposal, role)
            if not result.accepted:
                return str(result.reason)
    finally:
        copy.close()
    return ALLOW


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Case) -> tuple[str, str, str]:
    """(the hook's answer, the orchestrator's answer, the answer the case names)."""
    role, register, payload, expected = case
    store = _store(tmp_path / "store")
    register(monkeypatch)
    return (
        through_the_hook(tmp_path, store, role, payload),
        through_apply(tmp_path, store, role, payload),
        expected,
    )


# --- every case, through both layers ----------------------------------------------------------


@pytest.mark.parametrize("name", list(EVERY_CASE))
def test_apply_refuses_every_ownership_case_the_hook_refuses_for_the_same_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    hook, applied, expected = _case(tmp_path, monkeypatch, EVERY_CASE[name])
    assert (hook, applied) == (expected, expected)


def test_the_table_holds_every_rule_and_every_landing() -> None:
    # A table that lost a group would still pass case by case; so each reason is counted.
    reasons = {case[3] for case in EVERY_CASE.values()}
    assert {
        graph.CROSS_NODE,
        graph.INTERFACE_CREATION,
        graph.COMPLETION_OWNER_NODE,
        graph.OWNER_CHANGE,
        graph.KIND_CHANGE,
        REJECT_CROSS_ROLE,
        REJECT_INTERFACE_IMMUTABLE,
        ALLOW,
    } <= reasons
    assert len(EVERY_CASE) == sum(
        len(g) for g in (CROSS_CASES, INTERFACE_CASES, COMPLETION_CASES, ORDER_CASES, LANDS)
    )


# --- each rule, at apply ------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CROSS_CASES))
def test_a_cross_write_past_the_hook_is_refused_at_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _, applied, expected = _case(tmp_path, monkeypatch, CROSS_CASES[name])
    assert applied == expected == graph.CROSS_NODE


@pytest.mark.parametrize("name", list(INTERFACE_CASES))
def test_a_new_interface_node_past_the_hook_is_refused_at_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _, applied, expected = _case(tmp_path, monkeypatch, INTERFACE_CASES[name])
    assert applied == expected == graph.INTERFACE_CREATION


@pytest.mark.parametrize("name", list(COMPLETION_CASES))
def test_a_node_from_the_completion_owner_past_the_hook_is_refused_at_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _, applied, expected = _case(tmp_path, monkeypatch, COMPLETION_CASES[name])
    assert applied == expected == graph.COMPLETION_OWNER_NODE


@pytest.mark.parametrize("name", list(LANDS))
def test_what_the_rules_allow_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _, applied, _ = _case(tmp_path, monkeypatch, LANDS[name])
    assert applied == ALLOW


def test_a_cross_write_that_is_also_a_kind_change_is_refused_at_apply_as_a_kind_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, applied, _ = _case(
        tmp_path, monkeypatch, ORDER_CASES["a cross write that is also a kind change"]
    )
    assert applied == graph.KIND_CHANGE


# --- the owner lookup -----------------------------------------------------------------------------


def test_the_owner_is_looked_up_at_apply_on_every_read_not_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The register as it stands when the proposals are read decides, not as it stood before.
    store = _store(tmp_path / "store")
    payload = node("sizing.motor_right", "sizing")
    assert through_apply(tmp_path / "a", store, "sizing", payload) == graph.CROSS_NODE
    _sizing(monkeypatch)
    assert through_apply(tmp_path / "b", store, "sizing", payload) == ALLOW


def test_an_unexpected_error_in_the_owner_lookup_is_never_an_acceptance_at_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not a register error: apply must not turn it into an answer of its own. It reaches the
    # change check's caller, so nothing is applied, as the hook's runtime refuses the call.
    real = roles.owner_of

    def broken(duty: str) -> str:
        if duty != "cross_nodes":
            return real(duty)  # type: ignore[arg-type]
        msg = "the register could not be read"
        raise RuntimeError(msg)

    monkeypatch.setattr(roles, "owner_of", broken)
    store = _store(tmp_path / "store")
    with pytest.raises(RuntimeError, match="could not be read"):
        through_apply(tmp_path, store, "control", node("control.gain", "control"))


# --- where apply runs: the change check and the merge ------------------------------------------


def _run(tmp_path: Path, payloads: dict[str, dict[str, Any]]) -> tuple[RunGit, str]:
    """A run whose subtask ``s1`` committed ``payloads`` as proposals in one attempt."""
    repo = tmp_path / "target"
    (repo / "m1").mkdir(parents=True)
    (repo / "m1" / "a.txt").write_text("0\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("s1")
    for name, payload in payloads.items():
        path = worktree / ".physgate" / "proposals" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return run, commit_attempt(worktree, "s1", 1, "sess-1", repo=run.repo)


def test_the_change_check_rejects_a_cross_write_with_the_rule_s_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sizing(monkeypatch)
    store = _store(tmp_path / "store")
    cross = node("control.motor_current", "control", domain="cross")
    run, attempt = _run(tmp_path, {"control.motor_current": cross})
    found = GitChangeChecker(run, store, {"s1": "m1"}).check("s1", attempt, "control")
    assert found.refused_by == "proposal"
    assert graph.CROSS_NODE in str(found.reason) and found.subject == "control.motor_current"


def test_the_change_check_holds_the_plan_s_role_not_the_proposal_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A domain role's attempt that writes a cross node as if it were sizing's: refused as a
    # node of another role, because the role is the plan's, never the one the node names.
    _sizing(monkeypatch)
    store = _store(tmp_path / "store")
    posing = node("sizing.motor_right", "sizing")
    run, attempt = _run(tmp_path, {"sizing.motor_right": posing})
    found = GitChangeChecker(run, store, {"s1": "m1"}).check("s1", attempt, "control")
    assert found.refused_by == "proposal" and REJECT_CROSS_ROLE in str(found.reason)
    landed = GitChangeChecker(run, store, {"s1": "m1"}).check("s1", attempt, "sizing")
    assert landed.refused_by is None


def test_the_change_check_rejects_a_node_of_the_completion_owner(tmp_path: Path) -> None:
    store = _store(tmp_path / "store")
    written = node("integration.check", "integration", domain="control")
    run, attempt = _run(tmp_path, {"integration.check": written})
    found = GitChangeChecker(run, store, {"s1": "m1"}).check("s1", attempt, "integration")
    assert found.refused_by == "proposal"
    assert graph.COMPLETION_OWNER_NODE in str(found.reason)


def test_the_merge_reads_the_proposals_under_the_plan_s_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The proposals are read again from the checked commit when the attempt merges; the
    # rules hold there too, under the role the loop passes from the plan.
    _sizing(monkeypatch)
    store = _store(tmp_path / "store")
    cross = node("sizing.motor_right", "sizing")
    run, attempt = _run(tmp_path, {"sizing.motor_right": cross})
    keeper = StoreKeeper(run, store)
    try:
        (read,) = keeper.proposals("s1", attempt, "sizing")
        assert read["id"] == "sizing.motor_right"
        with pytest.raises(ProposalRefusedError) as refused:
            keeper.proposals("s1", attempt, "control")
        assert refused.value.reason == REJECT_CROSS_ROLE
    finally:
        keeper.close()
