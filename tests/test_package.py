"""The package imports and reports the version the toolchain was built around."""

from __future__ import annotations

import physgate


def test_package_imports_and_reports_its_version() -> None:
    assert physgate.__version__ == "0.0.0"
