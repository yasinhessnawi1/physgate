"""A hook that exists but is never wired passes every other test and guards nothing.

So the package is walked: every module defining a ``HOOK`` must be in the
registry, and every registered hook must appear in the generated settings for
each event it handles.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import shlex
from pathlib import Path

import physgate.hooks
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install


def _hook_modules() -> dict[str, str]:
    found = {}
    for info in pkgutil.iter_modules(physgate.hooks.__path__, "physgate.hooks."):
        if info.name.endswith("__main__"):
            continue
        module = importlib.import_module(info.name)
        spec = getattr(module, "HOOK", None)
        if spec is not None:
            found[spec.name] = info.name
    return found


def test_every_module_defining_a_hook_is_registered() -> None:
    found = _hook_modules()
    assert found, "the walk found no hook modules at all"
    assert set(found) == set(REGISTRY)


def test_every_registered_hook_is_named_in_the_settings_for_each_of_its_events(
    tmp_path: Path,
) -> None:
    (tmp_path / "w").mkdir()
    done = install(
        InstallRequest(
            profile="role",
            role="control",
            worktree=str(tmp_path / "w"),
            own_branch=None,
            store_root=None,
            state_dir=str(tmp_path / "state"),
            target_dir=str(tmp_path / "session"),
            claude_config_dir=str(tmp_path / "cfg"),
            user_home=str(tmp_path / "home"),
            token_ceiling=1000,
        ),
        REGISTRY,
    )
    settings = json.loads(done.settings_path.read_text())
    wired: dict[str, set[str]] = {}
    for event, groups in settings["hooks"].items():
        argv = shlex.split(groups[0]["hooks"][0]["command"])
        wired[event] = set(argv[argv.index("--hooks") + 1].split(","))
    assert REGISTRY
    for name, spec in REGISTRY.items():
        for event in spec.handlers:
            assert name in wired.get(event, set()), f"{name} is not wired for {event}"
