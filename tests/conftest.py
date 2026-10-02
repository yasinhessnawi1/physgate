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
