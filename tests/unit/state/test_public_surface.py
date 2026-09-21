"""Everything the package exports is importable and is what it claims to be.

A re-export that names a symbol which no longer exists is the kind of thing that
only fails when something else needs it, which is usually much later.
"""

from __future__ import annotations

import physgate.state as state


def test_every_exported_name_exists() -> None:
    assert state.__all__, "the package exports nothing"
    missing = [name for name in state.__all__ if not hasattr(state, name)]
    assert missing == []


def test_the_export_list_has_no_duplicates() -> None:
    assert len(state.__all__) == len(set(state.__all__))


def test_the_readme_is_beside_the_package() -> None:
    """The package docstring points at it, so it has to be there."""
    from pathlib import Path

    readme = Path(state.__file__).resolve().parent / "README.md"
    assert readme.is_file()
    assert readme.read_text().strip(), "the readme is empty"


def test_the_readme_says_what_the_package_does_not_own() -> None:
    from pathlib import Path

    readme = (Path(state.__file__).resolve().parent / "README.md").read_text()
    assert "does not own" in readme
    assert "view as of open" in readme
