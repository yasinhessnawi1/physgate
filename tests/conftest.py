"""Fixtures shared across the suite.

This file anchors module-name resolution for the tests and, from the state
package onwards, holds the fixtures more than one test directory needs. It is
the only conftest in the tree on purpose: a second one in a subdirectory
collides with this one under the strict type checker, because the test tree
carries no package markers.
"""

from __future__ import annotations

import math
import os
import secrets
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness_pin import measured_harness
from knowledge_fixture import build_fixture_library
from stand_in_roles import stand_in_roles

from physgate import roles
from physgate.orchestrator.cli import _harness_root
from physgate.orchestrator.git import harness_git
from physgate.orchestrator.run_config import HarnessState, harness_state
from physgate.oslayer.placement import machine_writable, placement_refusal
from physgate.state.store import Store

#: The variable naming where integration tests make their trees; ``~/.cache/pg-tests`` where
#: it is unset. It must lie outside every place the OS layer makes writable, and its path
#: must hold no word a reviewer's packet may not show (a test's name may: none is used).
TEST_ROOT_VARIABLE = "PHYSGATE_TEST_ROOT"

_FAILED = pytest.StashKey[bool]()


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """How many workers ``-n auto`` starts: the CPUs this process may actually use.

    The plugin's own count is the cores the machine shows. In a container held to a CPU
    quota that is far more than it may use: the shared server shows 96 cores to a
    workspace allowed 6, and 96 workers there would each import and collect the whole
    suite only to queue for the same six. ``PYTEST_XDIST_AUTO_NUM_WORKERS`` still wins,
    as it does in the plugin.
    """
    named = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", "")
    if named.isdigit() and int(named) > 0:
        return int(named)
    usable = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    count = usable or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
    except (OSError, ValueError):
        return count
    if quota == "max":
        return count
    return max(1, min(count, math.ceil(int(quota) / int(period))))


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """An open design-state store on an empty directory, closed afterwards."""
    opened = Store(tmp_path / "graph")
    yield opened
    opened.close()


@pytest.fixture(scope="session")
def fixture_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture curated library, built once."""
    return build_fixture_library(tmp_path_factory.mktemp("library"))


@pytest.fixture(autouse=True)
def _decompose_against_the_fixture_library(
    fixture_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every decomposition in the suite copies from the fixture library, not this checkout.

    The real library carries no ``electrical`` content yet, and the suite plans
    that role throughout. A test of the real library asks for it explicitly.
    """
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: fixture_library)


@pytest.fixture(scope="session", autouse=True)
def _the_suite_s_stand_in_roles_are_registered() -> Iterator[None]:
    """The suite plans ``electrical`` and ``mechanical`` stand-ins; register both, test-only.

    The shipped role register holds control and firmware alone, and a run refuses any
    other role at its start. The stand-ins are registered for the whole session, so the
    runs session-scoped fixtures build see them too; a test of the register itself takes
    them out again.
    """
    with pytest.MonkeyPatch.context() as patch:
        for name, stand_in in stand_in_roles().items():
            patch.setitem(roles.ROLES, name, stand_in)
        yield


@pytest.fixture(scope="session", autouse=True)
def _git_resolved_once_at_the_start() -> None:
    """The harness's git, resolved from the suite's own PATH before any test changes it.

    The harness resolves its git once per process, at the first git command. Resolving it
    here makes every test see the same binary whatever order they run in, including tests
    that empty PATH to hide the Claude Code binary. A test of the resolution itself calls
    ``resolve_git`` with a PATH of its own, or clears the cache and restores it. The harness
    checkout is measured here too, with that git, before any test can change PATH.
    """
    harness_git()
    measured_harness()


@pytest.fixture(autouse=True)
def _the_harness_checkout_is_measured_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The commands see this suite's checkout as it was measured once, at the first call.

    Any other checkout, such as a test's own repository standing in for the harness, is
    measured live as before. A test of a moved harness patches the measurement itself, over
    this one.
    """
    real = _harness_root()

    def measured(root: Path | None) -> HarnessState:
        return measured_harness() if root == real else harness_state(root)

    monkeypatch.setattr("physgate.orchestrator.cli.harness_state", measured)
    monkeypatch.setattr("physgate.evaluation.observe.rerun.harness_state", measured)


def outside_writable_root() -> Path:
    """Where integration tests make their trees: outside every place the OS layer makes writable.

    A sandboxed session's worktree inside one (the shared temporary directories, where
    pytest's own temporary directories are) shares the placeholders the Linux sandbox lays
    in its ancestors with every other session there, and their commands abort each other's;
    the dispatcher and the hook installer refuse such a worktree.
    """
    named = os.environ.get(TEST_ROOT_VARIABLE)
    root = Path(named) if named else Path.home() / ".cache" / "pg-tests"
    refused = placement_refusal(root, machine_writable())
    if refused is not None:
        pytest.fail(f"{TEST_ROOT_VARIABLE}: {refused}")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Iterator[None]:
    """Mark a test that failed, so its tree outside the temporary directories is kept."""
    report = yield
    if getattr(report, "failed", False):
        item.stash[_FAILED] = True
    return report


def _made_outside(request: pytest.FixtureRequest) -> Path:
    # A random name alone: a test's name can hold a word a review root may not.
    made = outside_writable_root() / f"t-{secrets.token_hex(6)}"
    made.mkdir()
    return made


def _drop_unless_failed(made: Path, request: pytest.FixtureRequest) -> None:
    if not request.node.stash.get(_FAILED, False):
        shutil.rmtree(made, ignore_errors=True)


@pytest.fixture
def outside_tmp(request: pytest.FixtureRequest) -> Iterator[Path]:
    """A directory of the test's own outside every place the OS layer makes writable.

    For a test that installs a sandboxed session, which the hook installer refuses a
    worktree in pytest's own temporary directories. Removed after a test that passed.
    """
    made = _made_outside(request)
    yield made
    _drop_unless_failed(made, request)


@pytest.fixture
def tmp_path(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Path]:
    """An integration test's directory, outside every place the OS layer makes writable.

    Integration tests run real sessions, sandboxed where the layer runs; their trees are
    made under :func:`outside_writable_root`, one directory per test, removed after a test
    that passed and kept after one that failed. Every other test gets pytest's own.
    """
    if request.node.get_closest_marker("integration") is None:
        yield tmp_path
        return
    made = _made_outside(request)
    yield made
    _drop_unless_failed(made, request)
