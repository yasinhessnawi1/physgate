"""The machine's state a measured round may be launched on, as one check a launch script calls.

A measured session reads every place no rule names (the OS layer allows each read it is not told
to deny; an allow-list for reads is not built, and that is a stated limit, the same in every arm).
So what lies in those places is a launch condition, checked here and printed by name:

- **no other run's material is readable** where a measured session may read: a directory that
  holds a run's, a raw trial's, a decomposition's, a round's or a review's own record, beneath
  the operator's home or the machine's other places a session reads, and not beneath a place
  every measured session is refused (the store, its registered run roots, the standing review
  root, the harness's and the sessions' temporary directories, the shared temporary ones);
- **the repository the trials are cloned from holds only what a trial may see**: one branch,
  no other reference (no tag, remote branch, stash or note), no linked worktree, and no object
  that branch does not reach, where an earlier run's work could lie;
- **no run that does not withhold the run roots is left beneath them**: a run's own sessions
  read whatever its run withholds not, and a run beneath the roots that withholds them not
  reads every measured run's material there.

Each finding is one line naming its kind and its place; the check never reads a record's content
but the run configuration's ``withheld_whole`` field, and never follows a link while it walks.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

#: The record files whose directory is a run's material: a harness run's configuration, a raw
#: trial's record, a decomposition's parameters, a harness round's and a baseline round's
#: records, and a review root's own record.
MATERIAL_NAMES = frozenset(
    {
        "run.json",
        "raw.json",
        "params_source.json",
        "round.json",
        "baseline.json",
        "review_root.json",
    }
)
#: How many entries the walk reads in all: past it the places are not established, which is a
#: finding of its own. A walk goes as deep as a place does.
MAX_ENTRIES = 2_000_000
#: Directories a walk does not enter: a package tree or a repository's object store holds no
#: run's records, and each holds more entries than everything else together.
NOT_ENTERED = frozenset({"node_modules", ".git", "__pycache__", ".venv", "site-packages"})
#: The machine's places beside the operator's home that every session reads and that hold what
#: other processes leave: ``/var/tmp`` (the shared temporary directories are refused to sessions).
MACHINE_PLACES: tuple[Path, ...] = (Path("/var/tmp"),)


@dataclass(frozen=True)
class Finding:
    """One thing the check found, by kind and place."""

    kind: str
    place: str
    detail: str = ""

    def line(self) -> str:
        """The finding as the check prints it."""
        tail = f": {self.detail}" if self.detail else ""
        return f"finding: {self.kind}: {self.place}{tail}"


def _under(path: str, roots: Iterable[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def _walk(
    top: str, refused: Sequence[str], budget: list[int]
) -> Iterator[tuple[str, tuple[str, ...] | None]]:
    """Each directory beneath ``top`` holding a material record, with every such record's name.

    Yields ``(top, None)`` once where the walk was cut short (its entries). Never follows a link;
    never enters a refused place, nor a directory that holds a record (a run's own tree).
    """
    stack = [top]
    while stack:
        directory = stack.pop()
        if _under(os.path.realpath(directory), refused):
            continue
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        budget[0] -= len(entries)
        if budget[0] < 0:
            yield top, None
            return
        names = {e.name for e in entries}
        held = tuple(sorted(names & MATERIAL_NAMES))
        if held:
            yield directory, held
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode) or entry.name in NOT_ENTERED:
                continue
            stack.append(entry.path)


def material_findings(places: Sequence[Path], refused: Sequence[Path]) -> list[Finding]:
    """Run material found beneath ``places``, outside every ``refused`` place."""
    real_refused = [os.path.realpath(p) for p in refused]
    found: list[Finding] = []
    budget = [MAX_ENTRIES]
    for place in places:
        if not place.is_dir():
            continue
        for directory, names in _walk(str(place), real_refused, budget):
            if names is None:
                found.append(
                    Finding("not_established", str(place), "the walk was cut short, too large")
                )
            else:
                held = ", ".join(names)
                found.append(Finding("run_material_readable", directory, f"it holds {held}"))
    return found


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    from physgate.orchestrator.git import NO_TRANSPORT, harness_git

    return subprocess.run(  # noqa: S603 - the harness's own git, its arguments ours
        [harness_git().path, *NO_TRANSPORT, "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


def source_findings(source: Path) -> list[Finding]:
    """What the repository the trials are cloned from holds beyond one branch's own work."""
    from physgate.orchestrator.exceptions import GitError
    from physgate.orchestrator.git import unreachable_from

    refs = _git(source, "for-each-ref", "--format=%(refname) %(objectname)")
    if refs.returncode != 0:
        return [Finding("source_unreadable", str(source), "git cannot list its references")]
    pairs = [line.split(" ", 1) for line in refs.stdout.splitlines() if line.strip()]
    found: list[Finding] = []
    branches = [(name, oid) for name, oid in pairs if name.startswith("refs/heads/")]
    if len(branches) != 1:
        found.append(
            Finding("source_branches", str(source), f"{len(branches)} branches, where one is all")
        )
    for name, _ in pairs:
        if not name.startswith("refs/heads/"):
            found.append(Finding("source_reference", str(source), f"it holds {name}"))
    worktrees = _git(source, "worktree", "list", "--porcelain")
    linked = [ln for ln in worktrees.stdout.splitlines() if ln.startswith("worktree ")][1:]
    if linked:
        found.append(Finding("source_worktrees", str(source), f"{len(linked)} linked worktrees"))
    if branches:
        try:
            loose = unreachable_from(source, [oid for _, oid in pairs])
        except GitError:
            found.append(Finding("source_unreadable", str(source), "its objects cannot be walked"))
        else:
            if loose:
                found.append(
                    Finding(
                        "source_objects",
                        str(source),
                        f"{len(loose)} objects no reference reaches (an earlier run's work can be "
                        "among them)",
                    )
                )
    return found


def withholding_findings(run_roots: Sequence[Path], registered: set[str]) -> list[Finding]:
    """Each run beneath the run roots whose configuration does not withhold every one of them."""
    from physgate.orchestrator.exceptions import OrchestratorError
    from physgate.orchestrator.run_config import load_run_config

    found: list[Finding] = []
    budget = [MAX_ENTRIES]
    for root in run_roots:
        if not root.is_dir():
            continue
        for directory, names in _walk(str(root), (), budget):
            if names is None:
                found.append(Finding("not_established", str(root), "the walk was cut short"))
                continue
            if "run.json" not in names:
                continue
            try:
                config = load_run_config(Path(directory) / "run.json")
            except (OrchestratorError, OSError, ValueError):
                found.append(Finding("run_unreadable", directory, "its run.json cannot be read"))
                continue
            named = {os.path.realpath(p) for p in config.withheld_whole}
            if not registered <= named:
                found.append(
                    Finding(
                        "run_not_withholding",
                        directory,
                        "a run beneath the run roots that does not withhold them all",
                    )
                )
    return found


def launch_findings(
    *, store: Path, source: Path, home: Path, also: Sequence[Path] = ()
) -> list[Finding]:
    """Every finding of the launch check, in the order the module's docstring names them."""
    from physgate.evaluation.tiers.exposure import ExposureError, run_roots
    from physgate.evaluation.tiers.task import Role
    from physgate.oslayer.harness_temp import harness_temps_root
    from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs
    from physgate.oslayer.session_temp import session_temps_root
    from physgate.reviewers.places import standing_root

    found: list[Finding] = []
    roots: list[Path] = []
    for role in get_args(Role):
        try:
            roots += run_roots(store, role)
        except ExposureError as exc:
            found.append(Finding("run_roots_unreadable", str(store), f"{role}: {exc}"))
    refused = [
        store,
        *roots,
        standing_root(home),
        Path(harness_temps_root()),
        Path(session_temps_root()),
        *map(Path, shared_temp_dirs()),
        *map(Path, claude_temp_dirs()),
    ]
    places = [home, *MACHINE_PLACES, *also]
    found += material_findings(places, refused)
    found += source_findings(source)
    found += withholding_findings(roots, {os.path.realpath(r) for r in roots})
    return found
