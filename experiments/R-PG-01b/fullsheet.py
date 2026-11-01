"""R-PG-01b, CRITERIA.md §2.5: arm F's corpus, made from v1 and its authors' table.

Usage, through ``make_sheet.sh`` only, on ``master`` at the converter's commit or later::

    uv run --frozen python -I experiments/R-PG-01b/fullsheet.py make

What it does, in order, refusing at the first fact that is not the frozen file's:

1. holds v1's manifest and its table (``parts_sheet.md``) to their digests;
2. copies the table to ``experiments/R-PG-01b/sheet/parts_sheet.md`` with the one edit: row
   R6.05's note, its one word "answered" read as "responded", and nothing else; the table, the
   row's line and its note are held to their before-and-after digests;
3. runs the converter (``scripts/parts_sheet_sources.py``) on that copy, in keep mode with v1's
   sheet, dropping the prose, into ``corpora/injected-errors/v1-fullsheet/sources.json``;
4. copies v1's base, artefacts, ``README.md`` and the unedited table byte for byte beside it, and
   writes the corpus's new manifest (format 1, the authors' model, :data:`LABEL`);
5. holds the result to §2.5's measured table: the sheet's digest, size and lines, its rows and
   their numbers, values, notes and remarks; every number row of v1 unchanged; the base and
   artefacts byte-identical to v1's; the corpus loading under its manifest.

It prints counts and digests only, never a row's content. Nothing is written over: an existing
output directory refuses the run before anything is written.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

#: Arm F's corpus label, written into its new manifest (§2.5; recorded at "sheet filled").
LABEL = (
    "injected-errors v1-fullsheet: v1's base design and 40 artefacts, byte for byte, with the "
    "complete parts sheet converted from the authors' table"
)
SHEET_DIRNAME = "experiments/R-PG-01b/sheet"
CONVERTER = "scripts/parts_sheet_sources.py"
#: v1's files arm F copies byte for byte (§2.5); the sheet and the manifest are its own.
COPIED = ("base.json", "README.md", C.TABLE_NAME)


class Refused(Exception):
    """A fact is not the one CRITERIA.md §2.5 states."""


@dataclass(frozen=True)
class Edit:
    """The one edit (§2.5): a word of one row's note, read as another."""

    row: str
    old: str
    new: str


#: §2.5's edit.
R605 = Edit(row="R6.05", old="answered", new="responded")

#: §2.5's measured facts, the frozen file's.
PINS: dict[str, Any] = {
    "table_before": C.TABLE_SHA256,
    "table_before_bytes": 30_998,
    "table_after": "0573ef044ebdcee9ff184eec2789e1a10b31fef6f32947735f9005ea8b0daedc",
    "table_after_bytes": 30_999,
    "line_before": "e2a58b268972a03fbd710be37df6ce3992209f336c03238efd3c405089bb0368",
    "line_after": "9976c090b279fa6d74c3a49dac455bed9d25cea40d3a3d59adc49a26b39e13de",
    "note_before": "7aa9c88bbf959fb64e136e8abe9e6007e6d4faf365d7eb1f1671d85820612af2",
    "note_after": "46a0698bb1dc51349623245a2f01a4af34995b21e5b1147d6f6e7e119d16c56d",
    "v1_manifest": C.ARM_I_MANIFEST_SHA256,
    "v1_sheet": C.ARM_I_SHEET_SHA256,
    "sheet": C.ARM_F_SHEET_SHA256,
    "sheet_bytes": 40_095,
    "sheet_lines": 1_224,
    "rows": 163,
    "rows_with_a_number": 101,
    "rows_with_given": 111,
    "rows_with_neither": 0,
    "notes": 130,
    "prose_lines": 9,
    "artefacts": 40,
}


def _cells(line: str) -> list[str]:
    """A table line's cells, as the converter reads them (an escaped pipe kept in its cell)."""
    inner = line.strip().removeprefix("|")
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]


def edit_table(table: bytes, edit: Edit) -> tuple[bytes, dict[str, Any]]:
    """The table with ``edit`` made, and the digests of the table, the row's line and its note.

    Raises:
        Refused: the row is not on exactly one line; the word is not in its note exactly once
            as a whole word, or is anywhere else in the table.
    """
    text = table.decode("utf-8")
    lines = text.split("\n")
    lead = re.compile(rf"^\|\s*{re.escape(edit.row)}\s*\|")
    where = [i for i, line in enumerate(lines) if lead.match(line)]
    if len(where) != 1:
        raise Refused(f"row {edit.row} is on {len(where)} lines of the table, not one")
    line = lines[where[0]]
    cells = _cells(line)
    if len(cells) != 7:
        raise Refused(f"row {edit.row} has {len(cells)} cells, not seven")
    note = cells[6]
    word = re.compile(rf"\b{re.escape(edit.old)}\b")
    if len(word.findall(note)) != 1 or len(word.findall(text)) != 1:
        raise Refused(f"the word is not in row {edit.row}'s note exactly once, and nowhere else")
    edited_line = word.sub(edit.new, line, count=1)
    edited_note = _cells(edited_line)[6]
    lines[where[0]] = edited_line
    after = "\n".join(lines).encode("utf-8")
    differ = sum(a != b for a, b in zip(text.split("\n"), lines, strict=True))
    facts = {
        "table_before": C.sha256_bytes(table),
        "table_before_bytes": len(table),
        "table_after": C.sha256_bytes(after),
        "table_after_bytes": len(after),
        "line_before": C.sha256_bytes(line.encode()),
        "line_after": C.sha256_bytes(edited_line.encode()),
        "note_before": C.sha256_bytes(note.encode()),
        "note_after": C.sha256_bytes(edited_note.encode()),
        "lines_differing": differ,
    }
    return after, facts


def _hold(found: dict[str, Any], pins: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if found[key] != pins[key]:
            raise Refused(f"{key} is {found[key]}, not {pins[key]}")


def sheet_counts(sheet: bytes) -> dict[str, Any]:
    """The measures of §2.5's table for a converted sheet."""
    data = json.loads(sheet)
    rows = data["rows"].values()
    return {
        "sheet": C.sha256_bytes(sheet),
        "sheet_bytes": len(sheet),
        "sheet_lines": sheet.count(b"\n"),
        "rows": len(data["rows"]),
        "rows_with_a_number": sum(r["value"] is not None for r in rows),
        "rows_with_given": sum("given" in r for r in rows),
        "rows_with_neither": sum(r["value"] is None and "given" not in r for r in rows),
        "notes": sum("note" in r for r in rows),
        "remarks": "remarks" in data,
    }


def kept_whole(earlier: bytes, sheet: bytes) -> int:
    """How many of the earlier sheet's fields the new sheet changed: every one must be kept."""
    before, after = json.loads(earlier), json.loads(sheet)
    changed = int(before["label"] != after["label"]) + int(
        list(before["rows"]) != list(after["rows"])
    )
    for row_id, row in before["rows"].items():
        new = after["rows"].get(row_id, {})
        changed += sum(json.dumps(new.get(k)) != json.dumps(v) for k, v in row.items())
        changed += sum(k not in (*row, "given", "note") for k in new)
    return changed


def make(
    repo: Path,
    v1: Path,
    out: Path,
    sheet_dir: Path,
    pins: dict[str, Any],
    label: str = LABEL,
    edit: Edit = R605,
    python: str = sys.executable,
) -> dict[str, Any]:
    """Make arm F's corpus at ``out`` and the edited table copy in ``sheet_dir``; its facts.

    Raises:
        Refused: any fact of §2.5 does not hold, or an output exists.
    """
    from physgate.evaluation.inject.corpus import load_corpus, manifest_for, write_manifest

    for p in (out, sheet_dir):
        if p.exists():
            raise Refused(f"{p} exists: nothing is written over")
    if C.sha256_file(v1 / "MANIFEST.json") != pins["v1_manifest"]:
        raise Refused("v1's manifest is not the one §2.2 pins")
    corpus = load_corpus(v1)  # every v1 file held to its manifest
    if C.sha256_bytes(corpus.parts_sheet) != pins["v1_sheet"]:
        raise Refused("v1's sheet is not the one §2.2 pins")
    table = (v1 / C.TABLE_NAME).read_bytes()
    edited, facts = edit_table(table, edit)
    _hold(facts, pins, (
        "table_before", "table_before_bytes", "table_after", "table_after_bytes",
        "line_before", "line_after", "note_before", "note_after",
    ))  # fmt: skip
    if facts["lines_differing"] != 1:
        raise Refused("the edit changed more than one line")
    sheet_dir.mkdir(parents=True)
    (sheet_dir / C.TABLE_NAME).write_bytes(edited)
    out.mkdir(parents=True)
    done = subprocess.run(
        [
            python, "-I", str(repo / CONVERTER), str(sheet_dir / C.TABLE_NAME),
            str(out / "sources.json"),
            "--keep-values-from", str(v1 / "sources.json"), "--prose", "drop",
        ],
        capture_output=True, text=True, check=False, cwd=repo,
    )  # fmt: skip
    if done.returncode != 0:
        raise Refused(f"the converter refused: {done.stderr.strip()[-300:]}")
    converter_said = done.stdout.split()
    said = dict(zip(converter_said[::2], converter_said[1::2], strict=False))
    if said.get("prose-dropped") != str(pins["prose_lines"]):
        raise Refused(f"the converter dropped {said.get('prose-dropped')} prose lines")
    if said.get("changed") != "0":
        raise Refused("the converter changed a field of v1's sheet")
    for name in COPIED:
        shutil.copyfile(v1 / name, out / name)
    (out / "artefacts").mkdir()
    for src in sorted((v1 / "artefacts").glob("*.json")):
        shutil.copyfile(src, out / "artefacts" / src.name)
    write_manifest(out, manifest_for(out, label=label, author_model=C.AUTHOR_MODEL))
    sheet = (out / "sources.json").read_bytes()
    counts = sheet_counts(sheet)
    _hold(counts, pins, (
        "sheet", "sheet_bytes", "sheet_lines", "rows", "rows_with_a_number",
        "rows_with_given", "rows_with_neither", "notes",
    ))  # fmt: skip
    if counts["remarks"]:
        raise Refused("the sheet carries remarks; the prose was to be dropped")
    if kept_whole(corpus.parts_sheet, sheet) != 0:
        raise Refused("a field of v1's sheet is not kept byte for byte")
    loaded = load_corpus(out)
    same = all(
        C.sha256_file(out / rel) == C.sha256_file(v1 / rel)
        for rel in loaded.manifest.files
        if rel != "sources.json"
    )
    if not same or set(loaded.manifest.files) != set(corpus.manifest.files):
        raise Refused("arm F's base, artefacts or documentation are not v1's, byte for byte")
    if len(loaded.artefacts) != pins["artefacts"]:
        raise Refused(f"arm F holds {len(loaded.artefacts)} artefacts")
    return {
        **{k: v for k, v in facts.items()},
        **{k: v for k, v in counts.items()},
        "prose_dropped": int(said["prose-dropped"]),
        "converter": " ".join(converter_said),
        "edited_copy": C.sha256_file(sheet_dir / C.TABLE_NAME),
        "manifest": C.sha256_file(out / "MANIFEST.json"),
        "label": label,
        "files": len(loaded.manifest.files),
        "copied_byte_for_byte": len(loaded.manifest.files) - 1,
    }


def main(argv: list[str]) -> int:
    """``make``: arm F's corpus in this checkout, at the frozen pins; prints its facts."""
    if argv != ["make"]:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        found = make(
            C.REPO,
            C.REPO / C.ARM_I_CORPUS,
            C.REPO / C.ARM_F_CORPUS,
            C.REPO / SHEET_DIRNAME,
            PINS,
        )
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(json.dumps(found, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
