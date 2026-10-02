"""A fixture curated library, for runs the suite decomposes.

At decomposition the orchestrator copies each planned role's curated files from
the checkout it runs from into the target's run branch. The suite plans roles,
``electrical`` above all, that the real library does not carry yet, so every test
decomposes against this library instead (``conftest`` names it through the one
seam the command reads; nothing on a command line can). A test that seeds its
target with curated content writes these same bytes, so the copy finds them
identical and leaves them.
"""

from __future__ import annotations

from pathlib import Path

from physgate.knowledge import loader

#: Every role the suite plans, with cross's standards, which every role reads.
FIXTURE_ROLES = ("cross", "electrical", "mechanical", "control", "firmware")


def fixture_text(relative: Path) -> str:
    """The one fixture body for a curated file, the same wherever it is written."""
    return f"# {relative.name}\n\nFixture content for the test suite.\n"


def write_fixture(root: Path, roles: tuple[str, ...] = FIXTURE_ROLES) -> list[Path]:
    """Write every always-loaded file of ``roles`` under ``root``; return their paths."""
    written = []
    for relative in sorted({p for role in roles for p in loader.always_loaded(role)}):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fixture_text(relative))
        written.append(path)
    return written


def build_fixture_library(root: Path) -> Path:
    """A library root holding the fixture content of every role the suite plans."""
    write_fixture(root)
    return root
