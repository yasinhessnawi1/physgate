"""Fixtures shared across the suite.

This file anchors module-name resolution for the tests and, from the state
package onwards, holds the fixtures more than one test directory needs. It is
the only conftest in the tree on purpose: a second one in a subdirectory
collides with this one under the strict type checker, because the test tree
carries no package markers.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from knowledge_fixture import build_fixture_library

from physgate.orchestrator.git import harness_git
from physgate.state.store import Store


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
    ``resolve_git`` with a PATH of its own, or clears the cache and restores it.
    """
    harness_git()
