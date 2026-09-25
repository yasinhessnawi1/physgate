"""Session configurations and event descriptions for the hook tests.

Named apart from the state tests' helper module on purpose: the test tree has no
package markers, so two modules with one name would shadow each other.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from physgate.hooks.config import SessionConfig, digest

SESSION = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def config_dict(tmp: Path, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401 - test fields
    """A complete, valid session configuration rooted in ``tmp``."""
    worktree = tmp / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    base: dict[str, Any] = {
        "profile": "role",
        "role": "electrical",
        "worktree": str(worktree),
        "own_branch": "subtask/electrical-1",
        "store_root": str(tmp / "store"),
        "state_dir": str(tmp / "state"),
        "protected_roots": [
            {
                "path": str(worktree / "src" / "physgate" / "gate"),
                "reason": "it holds the gate",
                "watch": "revert",
            }
        ],
        "experiments": [],
        "held_out": [],
        "required_reading": [],
        "always_loaded": [],
        "token_ceiling": 1000,
        "tools_allowed": ["Read", "Write", "Edit", "NotebookEdit", "Bash"],
        "installation": {
            "interpreter": sys.executable,
            "package_dir": str(Path(__file__).resolve().parents[3] / "src" / "physgate"),
            "environment_root": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "watchdog_seconds": 5,
        "hook_timeout_seconds": 30,
    }
    base.update(overrides)
    return base


def write_config(tmp: Path, **overrides: Any) -> tuple[Path, str, SessionConfig]:  # noqa: ANN401
    """Write a configuration file; return its path, its digest and the parsed model."""
    data = json.dumps(config_dict(tmp, **overrides), sort_keys=True).encode()
    path = tmp / "session-config.json"
    path.write_bytes(data)
    return path, digest(data), SessionConfig.model_validate_json(data)


def event(name: str = "PreToolUse", **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """An event description as Claude Code sends it."""
    base: dict[str, Any] = {"session_id": SESSION, "cwd": "/tmp", "hook_event_name": name}
    base.update(fields)
    return base


def bash(command: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    """A PreToolUse event for a Bash call."""
    return event(tool_name="Bash", tool_input={"command": command, "description": "x"}, **fields)


def node(
    node_id: str = "electrical.motor", owner: str = "electrical", **fields: Any
) -> dict[str, Any]:  # noqa: ANN401
    """A complete, legal graph node."""
    base: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": owner
        if owner in ("mechanical", "electrical", "control", "firmware")
        else "cross",
        "owner_role": owner,
        "quantities": {
            "stall_current": {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-25T00:00:00Z",
    }
    base.update(fields)
    return base


def make_store(root: Path, *nodes: dict[str, Any]) -> None:
    """A real graph store at ``root``, written by the store itself."""
    from physgate.state.store import Store

    store = Store(root)
    try:
        for payload in nodes or (node(),):
            result = store.write_node(payload, payload["owner_role"])
            assert result.accepted, result.reason
    finally:
        store.close()


def volume_is_case_insensitive(directory: Path) -> bool:
    """True if ``directory`` is on a volume where a case variant names the same file.

    The case-variant attempts depend on the volume, not on the operating system:
    macOS can mount a case-sensitive volume, and CI ran one on Linux. So the
    condition is probed where the test actually runs.
    """
    probe = directory / "Case-Probe"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("")
    try:
        return (directory / "case-probe").exists()
    finally:
        probe.unlink()
