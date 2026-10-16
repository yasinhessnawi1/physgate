"""The protected-root table the settings generator makes for a request touching every kind of root.

Paths are written relative to the request's base directory and the installation's own, so the
table of one version can be compared with another's byte for byte.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation


def config(base: Path) -> SessionConfig:
    """The configuration for the fixed request, beneath ``base``."""
    wt = base / "run" / "worktrees" / "control-1"
    harness = base / "harness"
    for d in (wt, harness / "experiments" / "R-X-01", base / "sp"):
        d.mkdir(parents=True, exist_ok=True)
    (harness / "experiments" / "R-X-01" / "CRITERIA.md").write_text("c\n")
    (base / "sp" / "keep.pth").write_text("")
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(wt),
        own_branch="b",
        store_root=str(base / "run" / "store"),
        state_dir=str(base / "state"),
        target_dir=str(base / "target"),
        claude_config_dir=str(base / "config"),
        user_home=str(base / "home"),
        token_ceiling=40960,
        held_out=(str(base / "heldout"),),
        answer_keys=(str(base / "keys"),),
        extra_protected=(str(base / "run" / "events.jsonl"),),
        extra_protected_refuse_only=(str(base / "run" / "sessions"),),
        harness_root=str(harness),
        harness_site_packages=(str(base / "sp"),),
    )
    return build_config(request, current_installation())


def table(base: Path) -> list[dict[str, object]]:
    """The configuration's protected roots, with every machine-specific path written as a name."""
    installation = current_installation()
    out: list[dict[str, object]] = []
    for r in config(base).protected_roots:
        path = r.path
        named = (
            ("<install-package>", installation.package_dir),
            ("<install-env>", installation.environment_root),
            ("<install-base>", installation.base_prefix),
        )
        for name, value in named:
            if path == value:
                path = name
        if path.startswith(str(base)):
            path = "<base>" + path[len(str(base)) :]
        out.append(
            {
                "path": path,
                "reason": r.reason,
                "watch": r.watch,
                "exceptions": [e.replace(str(base), "<base>") for e in r.exceptions],
            }
        )
    return out


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        print(json.dumps(table(Path(os.path.realpath(d))), indent=1, sort_keys=True))
