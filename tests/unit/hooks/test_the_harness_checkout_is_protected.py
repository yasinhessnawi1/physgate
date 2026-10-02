"""The checkout the orchestrator runs from is out of reach of a session in another worktree.

A role session runs in the target repository's worktree. The orchestrator's own
checkout is somewhere else, and holds what judges that session: the physics
gate's source, the curated library and its bounds tables, the frozen
experiments. Before this, nothing named that checkout, so a session could write
it by absolute path and the run noticed nothing (found live with a scripted
session, zero tokens). Now the whole checkout is refused before a write, and the
trees a run trusts are also put back after one by the sentinel.

The bypass suite (``tests/integration/hooks``) proves it against the real binary
through the tool, shell and interpreter paths; this is the fast, direct check of
the configuration and the matcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from physgate.hooks.paths import protection
from physgate.hooks.reasons import HARNESS_REASON
from physgate.hooks.settings import (
    HARNESS_REVERTED,
    InstallRequest,
    build_config,
    current_installation,
)


def _harness(tmp: Path) -> Path:
    harness = tmp / "harness"
    for rel in (
        "src/physgate/gate/runner.py",
        "knowledge/control/standards.md",
        "knowledge/electrical/bounds.toml",
        "knowledge/staging/candidate.md",
        "experiments/R-XX-01/CRITERIA.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-XX-01/runs/metrics.csv",
        "experiments/R-YY-02/criteria.md",
        "README.md",
        ".venv/lib/python3.12/site-packages/x.pth",
    ):
        path = harness / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("bytes\n")
    return harness


def _request(tmp: Path, **overrides: Any) -> InstallRequest:  # noqa: ANN401 - test fields
    worktree = tmp / "worktree"
    worktree.mkdir(exist_ok=True)
    fields: dict[str, Any] = {
        "profile": "role",
        "role": "control",
        "worktree": str(worktree),
        "own_branch": "subtask/c1",
        "store_root": str(tmp / "store"),
        "state_dir": str(tmp / "state"),
        "target_dir": str(tmp / "session"),
        "claude_config_dir": str(tmp / "claude-config"),
        "user_home": str(tmp / "home"),
        "token_ceiling": 4000,
    }
    fields.update(overrides)
    return InstallRequest(**fields)


def _roots(config: Any) -> dict[str, tuple[str, str, tuple[str, ...]]]:  # noqa: ANN401 - test helper
    return {r.path: (r.reason, r.watch, tuple(r.exceptions)) for r in config.protected_roots}


def test_the_whole_checkout_is_refused_and_its_trusted_trees_are_put_back(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    roots = _roots(config)
    assert roots[str(harness)] == (HARNESS_REASON, "none", ())
    for name in HARNESS_REVERTED:
        assert roots[str(harness / name)] == (HARNESS_REASON, "revert", ())
    for rel in (
        "experiments/R-XX-01/CRITERIA.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-YY-02/criteria.md",
    ):
        assert roots[str(harness / rel)] == (HARNESS_REASON, "revert", ()), rel
    # Put back by name, never the whole experiment directory: measured at 214 MB
    # copied at every session's start on the main checkout.
    assert str(harness / "experiments") not in roots
    assert str(harness / "experiments/R-XX-01") not in roots
    assert str(harness / ".venv") not in roots


@pytest.mark.parametrize(
    "rel",
    [
        "src/physgate/gate/runner.py",
        "src/physgate/gate/check_new.py",
        "knowledge/control/standards.md",
        "knowledge/control/planted.md",
        "knowledge/electrical/bounds.toml",
        # The harness's own staging is not an exception for a session elsewhere:
        # that session's staging is in its own worktree.
        "knowledge/staging/candidate.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-XX-01/runs/metrics.csv",
        "README.md",
        ".venv/lib/python3.12/site-packages/x.pth",
        "a/path/that/does/not/exist/yet.py",
    ],
)
def test_every_write_into_the_checkout_is_refused(tmp_path: Path, rel: str) -> None:
    harness = _harness(tmp_path)
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    assert protection(str(harness / rel), str(worktree), config, writing=True) == HARNESS_REASON


def test_reading_the_checkout_is_not_refused(tmp_path: Path) -> None:
    # Refusing reads is the held-out tier's and the answer keys' job, not this one's.
    harness = _harness(tmp_path)
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    target = str(harness / "knowledge/control/standards.md")
    assert protection(target, str(tmp_path / "worktree"), config, writing=False) is None


def test_without_a_harness_nothing_changes(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with_none = _roots(build_config(_request(tmp_path), current_installation()))
    assert not [p for p in with_none if p.startswith(str(harness))]


def test_a_worktree_inside_the_checkout_is_refused_at_install(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    inside = harness / "runs" / "worktree"
    inside.mkdir(parents=True)
    with pytest.raises(ValueError, match="contains the worktree"):
        build_config(
            _request(tmp_path, worktree=str(inside), harness_root=str(harness)),
            current_installation(),
        )


def test_the_orchestrators_startup_files_are_watched_and_nothing_else_in_its_environment(
    tmp_path: Path,
) -> None:
    from physgate.hooks.settings import _startup_watch

    harness = _harness(tmp_path)
    site = harness / ".venv/lib/python3.12/site-packages"
    for rel in ("_editable.pth", "typing_extensions.py", "pkg/__init__.py", "big.so"):
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text("x\n")
    config = build_config(
        _request(tmp_path, harness_root=str(harness), harness_site_packages=(str(site),)),
        current_installation(),
    )
    reason, watch, exceptions = _roots(config)[str(site)]
    assert (reason, watch) == (HARNESS_REASON, "revert")
    assert exceptions == _startup_watch(site)
    assert {Path(e).name for e in exceptions} == {"typing_extensions.py", "pkg", "big.so"}
    # A new startup file of any name, and an existing one, are refused before a write.
    for rel in ("zz_new.pth", "sitecustomize.py", "usercustomize.py", "x.pth"):
        assert protection(str(site / rel), str(tmp_path / "worktree"), config, writing=True)
