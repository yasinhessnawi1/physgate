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
import stat
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

    def projection(self, edit: Callable[[dict[str, Any]], None], *, restamp: bool = True) -> None:
        """Change the projection file; with ``restamp`` the record names the changed file."""
        path = self.root / "plate.projection.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        edit(data)
        text = json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        if restamp:
            written = path.read_bytes()

            def stamp(record: dict[str, Any]) -> None:
                record["files"]["projection"]["sha256"] = hashlib.sha256(written).hexdigest()
                record["files"]["projection"]["size"]["value"] = len(written)

            self.record(stamp)


def _edit_json(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def module_with_step(root: Path, step: bytes, named: bytes) -> Path:
    """A module holding ``step`` as the plate's STEP file and the plate's record naming ``named``.

    The record is the committed plate's, with its exports reduced to that one STEP file.
    """
    module = root / "module"
    (module / "exports").mkdir(parents=True)
    (module / "exports" / "plate.step").write_bytes(step)
    part = json.loads((FIXTURE / "plate.result.json").read_text(encoding="utf-8"))
    part["exports"] = [
        {
            "file": "exports/plate.step",
            "size": {"value": len(named), "unit": "byte"},
            "sha256": hashlib.sha256(named).hexdigest(),
        }
    ]
    path = module / "plate.result.json"
    path.write_text(json.dumps(part), encoding="utf-8")
    return path


def stand_in_tree(root: Path, said: str) -> Path:
    """A tool environment whose interpreter is a stand-in that prints ``said`` and nothing else.

    It holds what a provisioned environment is recognised by (``provisioned.json``,
    ``venv/bin/python`` and ``helpers/geometry.py``); its interpreter is a shell script that
    prints the text and ignores the script it is handed. No kernel is needed.
    """
    tree = root / "stand-in-tree"
    (tree / "venv" / "bin").mkdir(parents=True)
    (tree / "helpers").mkdir()
    (tree / "provisioned.json").write_text("{}\n", encoding="utf-8")
    (tree / "helpers" / "geometry.py").write_text("", encoding="utf-8")
    told = tree / "said.txt"
    told.write_text(said + "\n", encoding="utf-8")
    interpreter = tree / "venv" / "bin" / "python"
    interpreter.write_text(f"#!/bin/sh\nexec /bin/cat '{told}'\n", encoding="utf-8")
    interpreter.chmod(interpreter.stat().st_mode | stat.S_IXUSR)
    return tree


def projection_said() -> str:
    """What the kernel prints for the committed plate: its projection, after its marker."""
    return "PROJECTION " + (FIXTURE / "plate.projection.json").read_text(encoding="utf-8").strip()


def all_pass_but(**changed: str) -> dict[str, str]:
    """Every check's verdict ``passes``, except those named (``title_block``: the title block)."""
    held = {"part": "passes", "file": "passes", "views": "passes", "title block": "passes"}
    held["dimensions"] = "passes"
    for name, verdict in changed.items():
        held[name.replace("_", " ")] = verdict
    return held
