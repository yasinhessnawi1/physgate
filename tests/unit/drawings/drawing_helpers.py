"""A real drawing of the chassis plate, copied for a row and doctored where the row needs it.

``plate_drawing`` holds the plate's record as the geometry helper wrote it on a provisioned tool
environment, and the drawing ``physgate drawing make`` composed from the kernel's projection of
its STEP file there: the SVG, the drawing's record and the projection. A row copies the four
files into a folder of its own and changes exactly what it tests.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from physgate.build.drawings.check import Finding, check_drawing

FIXTURE = Path(__file__).resolve().parent / "plate_drawing"
FILES = ("plate.result.json", "plate.svg", "plate.drawing.json", "plate.projection.json")
PLATE_HASH = "sha256:ff88fca266977bd1de7ea23c66e94b95492e4b3d1f976f49ca4521dac68dd151"


class Copy:
    """The fixture's four files in a folder of a row's own."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            shutil.copyfile(FIXTURE / name, root / name)
        self.root = root
        self.drawing = root / "plate.drawing.json"
        self.part = root / "plate.result.json"
        self.svg = root / "plate.svg"

    def check(self) -> tuple[Finding, ...]:
        return check_drawing(self.drawing, self.part)

    def verdicts(self) -> dict[str, str]:
        return {finding.check: finding.verdict for finding in self.check()}

    def message(self, check: str) -> str:
        return next(f.message for f in self.check() if f.check == check)

    def svg_text(self, edit: Callable[[str], str], *, restamp: bool = True) -> None:
        """Change the SVG; with ``restamp`` the record names the changed file, so it is current."""
        before = self.svg.read_text(encoding="utf-8")
        after = edit(before)
        assert after != before, "the edit changed nothing"
        self.svg.write_text(after, encoding="utf-8", newline="\n")
        if restamp:
            data = self.svg.read_bytes()

            def stamp(record: dict[str, Any]) -> None:
                record["files"]["svg"]["sha256"] = hashlib.sha256(data).hexdigest()
                record["files"]["svg"]["size"]["value"] = len(data)

            self.record(stamp)

    def record(self, edit: Callable[[dict[str, Any]], None]) -> None:
        _edit_json(self.drawing, edit)

    def part_record(self, edit: Callable[[dict[str, Any]], None]) -> None:
        _edit_json(self.part, edit)


def _edit_json(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def all_pass_but(**changed: str) -> dict[str, str]:
    """Every check's verdict ``passes``, except those named (``title_block``: the title block)."""
    held = {"part": "passes", "file": "passes", "views": "passes", "title block": "passes"}
    held["dimensions"] = "passes"
    for name, verdict in changed.items():
        held[name.replace("_", " ")] = verdict
    return held
