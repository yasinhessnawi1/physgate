"""Write ``physgate/orchestrator/default_ignorable.py`` from the Unicode data it is pinned to.

Usage: ``python scripts/generate_default_ignorable.py <DerivedCoreProperties.txt>``

The file is the Unicode Character Database's ``DerivedCoreProperties.txt`` for the version the
pinned interpreter's ``unicodedata`` carries, fetched from :data:`SOURCE_URL`. It is refused
unless its sha256 is :data:`SOURCE_SHA256`, so the generated ranges are the published ones and
nothing typed by hand.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

UNICODE_VERSION = "15.0.0"
SOURCE_URL = f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/DerivedCoreProperties.txt"
SOURCE_SHA256 = "d367290bc0867e6b484c68370530bdd1a08b6b32404601b8c7accaf83e05628d"
TARGET = Path(__file__).resolve().parents[1] / "src/physgate/orchestrator/default_ignorable.py"
_LINE = re.compile(r"^([0-9A-F]{4,6})(?:\.\.([0-9A-F]{4,6}))?\s*;\s*Default_Ignorable_Code_Point\b")


def ranges(text: str) -> list[tuple[int, int]]:
    """The property's ranges, in the file's order, adjacent ones merged."""
    found: list[tuple[int, int]] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m is None:
            continue
        lo = int(m.group(1), 16)
        hi = int(m.group(2) or m.group(1), 16)
        if found and found[-1][1] + 1 == lo:
            found[-1] = (found[-1][0], hi)
        else:
            found.append((lo, hi))
    return found


def render(found: list[tuple[int, int]]) -> str:
    """The generated module's text."""
    rows = "\n".join(f"    (0x{lo:04X}, 0x{hi:04X})," for lo, hi in found)
    return f'''"""The Unicode Default_Ignorable_Code_Point set. Generated; do not edit.

Written by ``scripts/generate_default_ignorable.py`` from the Unicode Character Database's
``DerivedCoreProperties.txt``, version {UNICODE_VERSION} (the version the pinned interpreter's
``unicodedata`` carries), held to its sha256.
"""

UNICODE_VERSION = "{UNICODE_VERSION}"
SOURCE_URL = "{SOURCE_URL}"
SOURCE_SHA256 = "{SOURCE_SHA256}"

#: Inclusive code point ranges, ascending.
RANGES: tuple[tuple[int, int], ...] = (
{rows}
)
'''


def main(source: str) -> None:
    """Check ``source`` against the pinned digest and write the module from it."""
    data = Path(source).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        msg = f"{source} has sha256 {digest}, not the pinned {SOURCE_SHA256}"
        raise SystemExit(msg)
    found = ranges(data.decode("utf-8"))
    TARGET.write_text(render(found))
    print(f"{len(found)} ranges, {sum(hi - lo + 1 for lo, hi in found)} code points -> {TARGET}")


if __name__ == "__main__":
    main(sys.argv[1])
