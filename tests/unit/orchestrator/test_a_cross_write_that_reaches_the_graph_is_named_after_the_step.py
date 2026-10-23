"""After every step, the graph's changes are held to the duties the role register names.

The loop's check after a step (``StoreKeeper.divergences``) names every node the step
changed that its role did not own. It also names every change that breaks a cross-cutting
duty, with the owners looked up in the register by what they own, on every call, through
the lookup that counts the owners itself: one owner, none, or two, each answered as the
hook and the apply step answer it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from physgate import roles
from physgate.orchestrator.apply import StoreKeeper
from physgate.orchestrator.merge import RunGit
from physgate.roles import CrossCuttingRole
from physgate.state.divergence import COMPLETION_OWNER_NODE, CROSS_NODE, INTERFACE_CREATION
from physgate.state.store import Store

BALLAST = CrossCuttingRole(name="ballast", architecture="ARCH-051", owns="cross_nodes")
CLOSER = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")


def node(node_id: str, owner: str, domain: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    base: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            "stall_current": {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-22T00:00:00Z",
    }
    base.update(fields)
    return base


def _after_a_step(tmp_path: Path, role: str, *payloads: dict[str, Any]) -> tuple[str, ...]:
    """What the loop's check names after a ``role`` step wrote ``payloads`` into the graph."""
    root = tmp_path / "graph"
    store = Store(root)
    assert store.write_node(node("control.loop", "control", "control"), "control").accepted
    since = store.head_revision()
    for payload in payloads:
        assert store.write_node(payload, role).accepted
    store.close()
    keeper = StoreKeeper(RunGit(repo=tmp_path, run_dir=tmp_path / "run", run_id="r1"), root)
    try:
        return keeper.divergences(since, role)
    finally:
        keeper.close()


def test_the_check_names_a_domain_role_s_cross_write_by_the_register_s_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    (found,) = _after_a_step(tmp_path, "control", node("control.motor_current", "control", "cross"))
    assert "control.motor_current" in found and CROSS_NODE in found
    assert "only the sizing role writes" in found


def test_the_check_lets_the_owner_s_cross_write_stand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    assert _after_a_step(tmp_path, "sizing", node("sizing.motor_right", "sizing", "cross")) == ()


def test_as_shipped_no_role_owns_the_cross_nodes_and_every_cross_write_is_named(
    tmp_path: Path,
) -> None:
    (found,) = _after_a_step(tmp_path, "sizing", node("sizing.motor_right", "sizing", "cross"))
    assert CROSS_NODE in found and "no registered role owns the cross nodes" in found


def test_the_owner_is_found_by_what_it_owns_not_by_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
    assert _after_a_step(tmp_path / "a", "ballast", node("ballast.mass", "ballast", "cross")) == ()
    (found,) = _after_a_step(
        tmp_path / "b", "sizing", node("sizing.motor_right", "sizing", "cross")
    )
    assert "only the ballast role writes" in found


def test_a_register_with_two_owners_of_the_cross_nodes_names_every_write_but_an_interface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Patched past the check the register makes when it is built, as a stand-in role is.
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
    (found,) = _after_a_step(tmp_path, "control", node("control.gain", "control", "control"))
    assert CROSS_NODE in found and "ballast,sizing" in found


def test_the_check_names_an_interface_created_in_the_step(tmp_path: Path) -> None:
    created = node("iface.control.p09", "control", "cross", kind="interface", quantities={})
    (found,) = _after_a_step(tmp_path, "control", created)
    assert INTERFACE_CREATION in found


def test_the_check_names_a_node_the_completion_owner_wrote(tmp_path: Path) -> None:
    (found,) = _after_a_step(
        tmp_path, "integration", node("integration.check", "integration", "control")
    )
    assert COMPLETION_OWNER_NODE in found and "integration" in found


def test_the_completion_owner_is_found_by_what_it_owns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(roles.ROLES, roles.INTEGRATION.name)
    monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)
    payload = node("integration.check", "integration", "control")
    assert _after_a_step(tmp_path / "a", "integration", payload) == ()
    (found,) = _after_a_step(tmp_path / "b", "closer", node("closer.check", "closer", "control"))
    assert COMPLETION_OWNER_NODE in found


def test_a_register_with_two_owners_of_completion_names_every_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)
    (found,) = _after_a_step(tmp_path, "control", node("control.gain", "control", "control"))
    assert COMPLETION_OWNER_NODE in found and "closer,integration" in found


def test_an_unexpected_error_in_the_owner_lookup_is_never_a_clean_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(duty: str) -> tuple[str, ...]:
        msg = "the register could not be read"
        raise RuntimeError(msg)

    monkeypatch.setattr(roles, "owners_of", broken)
    with pytest.raises(RuntimeError, match="could not be read"):
        _after_a_step(tmp_path, "control", node("control.gain", "control", "control"))


def test_an_unexpected_error_in_the_completion_owner_lookup_is_never_a_clean_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The completion side, reached: the cross nodes' owners are answered, and only the
    # completion lookup fails. The check must not read the failure as "no owner".
    real = roles.owners_of
    asked: list[str] = []

    def broken(duty: str) -> tuple[str, ...]:
        asked.append(duty)
        if duty != "completion":
            return real(duty)  # type: ignore[arg-type]
        msg = "the register could not be read"
        raise RuntimeError(msg)

    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setattr(roles, "owners_of", broken)
    with pytest.raises(RuntimeError, match="could not be read"):
        _after_a_step(tmp_path, "control", node("control.gain", "control", "control"))
    assert "completion" in asked


def test_one_keeper_asks_the_register_again_on_every_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One keeper, held across steps as the loop holds it, and the register changed between
    # two checks of the same step: each check answers the register as it stands then.
    root = tmp_path / "graph"
    store = Store(root)
    assert store.write_node(node("control.loop", "control", "control"), "control").accepted
    since = store.head_revision()
    assert store.write_node(node("sizing.motor_right", "sizing", "cross"), "sizing").accepted
    store.close()
    keeper = StoreKeeper(RunGit(repo=tmp_path, run_dir=tmp_path / "run", run_id="r1"), root)
    try:
        (unowned,) = keeper.divergences(since, "sizing")
        assert CROSS_NODE in unowned and "no registered role owns the cross nodes" in unowned
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        assert keeper.divergences(since, "sizing") == ()
        monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
        (contested,) = keeper.divergences(since, "sizing")
        assert "(ballast,sizing)" in contested
        monkeypatch.delitem(roles.ROLES, roles.SIZING.name)
        (other,) = keeper.divergences(since, "sizing")
        assert "only the ballast role writes" in other
    finally:
        keeper.close()


def test_the_check_counts_the_owners_itself_and_reads_no_error_s_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The keeper asks the register for the list of owners; it never asks the one-owner
    # lookup and reads the owners back out of the error that raises.
    def one_owner(duty: str) -> str:
        msg = "the check asked the one-owner lookup"
        raise AssertionError(msg)

    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setitem(roles.ROLES, BALLAST.name, BALLAST)
    monkeypatch.setattr(roles, "owner_of", one_owner)
    (found,) = _after_a_step(tmp_path, "control", node("control.gain", "control", "control"))
    assert CROSS_NODE in found and "(ballast,sizing)" in found
