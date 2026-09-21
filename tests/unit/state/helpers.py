"""Shared node payloads and the open-store fixture for the store tests."""

from __future__ import annotations

from typing import Any


def quantity(value: float = 2.4, unit: str = "A", writer: str = "sizing") -> dict[str, Any]:
    """A well-formed quantity."""
    return {"value": value, "unit": unit, "source": "datasheet", "written_by": writer}


def node(
    node_id: str = "electrical.motor_left",
    *,
    kind: str = "component",
    owner_role: str = "electrical",
    constrains: list[str] | None = None,
    updated: str = "2026-09-21T10:02:11Z",
    quantities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A complete, legal node payload.

    The domain follows the frozen generator's rule: for an interface node the
    domain is the *second* dotted part, because the first is the marker. Writing
    it the other way gave ``iface`` as a domain, which the closed domain set now
    refuses -- and which nothing noticed while the field was a free string.
    """
    parts = node_id.split(".")
    return {
        "id": node_id,
        "kind": kind,
        "domain": parts[1] if parts[0] == "iface" else parts[0],
        "owner_role": owner_role,
        "quantities": {"stall_current": quantity()} if quantities is None else quantities,
        "requirements": ["REQ-014"],
        "constrains": [] if constrains is None else constrains,
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": updated,
    }
