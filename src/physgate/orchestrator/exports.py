"""What a module's exports are: the files a tool writes for people and for later tools, as data.

A module keeps its exports (a part's STEP and STL files) in one folder of its own,
:data:`EXPORTS_DIR`, beside the script that wrote them. Such a file is not read as source:
shown as text it is thousands of lines of numbers, and a binary one is a single line longer
than any part of a review's diff may hold. So the review packet shows each export as one line
with its path, its size and its sha256 in place of its bytes (``reviewers.packet``); the
export of the attempt's commit still holds it whole.

The suffixes are data: adding a kind of export adds a suffix here, and the helpers in the tool
environment write the same folder and suffixes (a test holds the two to each other). A name
that holds a control character or any other character that does not print is never an export,
so a line naming one cannot be broken into two.
"""

from __future__ import annotations

from pathlib import PurePosixPath

#: The folder of a module that holds its exports, and nothing else.
EXPORTS_DIR = "exports"
#: What an export's name ends in, compared without regard to case.
EXPORT_SUFFIXES: tuple[str, ...] = (".step", ".stl")


def is_export(path: str) -> bool:
    """Whether ``path``, relative to the repository, names an export.

    That is a file directly inside a folder named :data:`EXPORTS_DIR`, its name ending in one
    of :data:`EXPORT_SUFFIXES`, and every character of the path printable. Whether the file is
    regular, and whether its folder is a module's own, are its readers' to check.
    """
    if not path.isprintable() or path.endswith("/"):
        return False
    pure = PurePosixPath(path)
    return (
        len(pure.parts) >= 2
        and pure.parent.name == EXPORTS_DIR
        and pure.name.casefold().endswith(EXPORT_SUFFIXES)
    )
