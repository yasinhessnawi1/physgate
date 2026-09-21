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

from physgate.state.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """An open design-state store on an empty directory, closed afterwards."""
    opened = Store(tmp_path / "graph")
    yield opened
    opened.close()
