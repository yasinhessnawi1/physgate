"""Exports as build123d's pinned writer writes them, for the rows on the export rules.

The header of a binary STL file and the text of a STEP file's header are the writer's own, as
measured from the chassis fixtures' exports (the measure is recorded beside the writer's
vocabulary in ``physgate.orchestrator.export_writer``): a row that builds an export from these
holds no free text, and a row that adds some can say exactly how many bytes it added.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence

#: The 80-byte header the writer gives every binary STL file it writes.
WRITER_STL_HEADER = b"STL Exported by Open CASCADE Technology [dev.opencascade.org]".ljust(
    80, b"\0"
)

#: The header the writer gives a STEP file, with the time the design helper fixes.
WRITER_STEP_HEADER = (
    "FILE_DESCRIPTION(('Open CASCADE Model'),'2;1');\n"
    "FILE_NAME('Open CASCADE Shape Model','2000-01-01T00:00:00',('Author'),(\n"
    "    'Open CASCADE'),'Open CASCADE STEP processor 8.0','build123d',\n"
    "  'Unknown');\n"
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
)


def writer_step(
    data: str | None = None, *, header: str = WRITER_STEP_HEADER, entities: int = 3
) -> bytes:
    """A STEP file in the writer's words: its header, one data section of points, the end."""
    if data is None:
        data = "".join(
            f"#{n} = CARTESIAN_POINT('',(0.,0.,{n}.));\n" for n in range(1, entities + 1)
        )
    text = f"ISO-10303-21;\nHEADER;\n{header}ENDSEC;\nDATA;\n{data}ENDSEC;\nEND-ISO-10303-21;\n"
    return text.encode()


def writer_stl(
    corners: Sequence[tuple[float, float, float]],
    *,
    header: bytes = WRITER_STL_HEADER,
    attributes: Mapping[int, int] | None = None,
    count: int | None = None,
) -> bytes:
    """A binary STL file with the writer's header: the count, then 50 bytes a triangle."""
    triangles = [corners[i : i + 3] for i in range(0, len(corners), 3)]
    body = header + struct.pack("<I", len(triangles) if count is None else count)
    for n, triangle in enumerate(triangles):
        body += struct.pack("<3f", 0.0, 0.0, 1.0)
        for corner in triangle:
            body += struct.pack("<3f", *corner)
        body += struct.pack("<H", (attributes or {}).get(n, 0))
    return body
