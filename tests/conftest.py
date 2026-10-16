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
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness_pin import measured_harness
from knowledge_fixture import build_fixture_library

from physgate.orchestrator.cli import _harness_root
from physgate.orchestrator.git import harness_git
from physgate.orchestrator.run_config import HarnessState, harness_state
from physgate.state.store import Store


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
