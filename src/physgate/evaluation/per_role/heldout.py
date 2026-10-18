"""Before a run: proof that no session it will start can read the held-out tier.

Three things are checked, and a run with any problem is refused before anything starts:

- **the parameters:** the run names the held-out root, and names it as it really is (a
  root reached through a link would be protected under one spelling and read under the
  other);
- **the places:** no place a session works in or reads (the run directory, the target
  repository, the review root, the raw arm's work area, the hooks' installation, the
  interpreter sessions are given) is the held-out root, lies inside it or contains it,
  and none holds a link that resolves into it;
- **the sessions:** for each profile a session of the run is started under (a role, a
  reviewer, the raw agent), the configuration the hook installer would write names the
  root as held out, and the OS layer's policy denies it to the shell both ways.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "reviewer", "baseline")


def _relation(place: Path, root: Path) -> str | None:
    if place == root:
        return "is"
    if place.is_relative_to(root):
        return "lies inside"
    if root.is_relative_to(place):
        return "contains"
    return None


def _links_into(place: Path, root: Path) -> list[str]:
    found: list[str] = []
    for current, dirs, files in os.walk(place, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(current) / name
            if path.is_symlink():
                target = Path(os.path.realpath(path))
                if _relation(target, root) in ("is", "lies inside"):
                    found.append(str(path))
    return found


def _session_problems(root: Path, scratch: Path) -> list[str]:
    problems: list[str] = []
    for profile in PROFILES:
        work = scratch / profile
        request = InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(work / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(work / "state"),
            target_dir=str(work / "session"),
            claude_config_dir=str(work / "config"),
            user_home=str(work / "home"),
            token_ceiling=1,
            held_out=(str(root),),
            read_roots=(str(work / "worktree"),) if profile == "reviewer" else (),
        )
        config = build_config(request, current_installation())
        if str(root) not in config.held_out:
            problems.append(f"a {profile} session would not be configured with the root")
        if profile == "reviewer":
            continue  # a reviewer has no shell, so no OS layer
        policy = sandbox_policy(config, home=str(work / "home"), temp_dir="/tmp/pg-scan")
        filesystem = policy.settings["sandbox"]["filesystem"]
        for direction in ("denyRead", "denyWrite"):
            if str(root) not in filesystem[direction]:
                problems.append(f"a {profile} session's OS layer would not {direction} the root")
    return problems


def scan(
    held_out: Path, run_held_out: tuple[str, ...], places: Mapping[str, Path], scratch: Path
) -> list[str]:
    """Every reason a run with these parameters and places could expose ``held_out``.

    ``run_held_out`` is the run's ``held_out`` parameter; ``places`` names every directory
    a session of the run works in or reads; ``scratch`` is an empty directory outside the
    tier where the sessions' configurations are generated to be looked at.
    """
    problems: list[str] = []
    if str(held_out) not in run_held_out:
        problems.append("the run's parameters do not name the held-out root")
    if not held_out.is_absolute() or os.path.realpath(held_out) != str(held_out):
        problems.append("the held-out root is not given as its real, absolute path")
    for name, place in sorted(places.items()):
        real = Path(os.path.realpath(place))
        for spelling in {place, real}:
            relation = _relation(spelling, held_out)
            if relation is not None:
                problems.append(f"the {name} {relation} the held-out root")
        if place.exists():
            problems.extend(
                f"the {name} holds a link into the tier: {link}"
                for link in _links_into(place, held_out)
            )
    if _relation(scratch, held_out) is not None:
        problems.append("the scan's own scratch directory touches the held-out root")
    else:
        problems.extend(_session_problems(held_out, scratch))
    return sorted(set(problems))
