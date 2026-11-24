"""``physgate drawing``: one drawing made from one part, checked, and stale when the part changes.

- ``drawing example-part MODULE [--length MM]``: the chassis fixture's plate written into a
  module directory by the tool environment's geometry helper, as a part script records a part.
- ``drawing make PART_RECORD --out DIR``: the drawing of the part whose record is
  ``PART_RECORD`` (``<part>.result.json``), from the STEP file the record names, by the CAD
  kernel's own projection; written into ``DIR`` as ``<part>.svg``, ``<part>.drawing.json`` and
  ``<part>.projection.json``, each under a temporary name of its own in ``DIR`` and then renamed
  over its final name, so a file already there is replaced and never written through. A ``DIR``
  that is a symbolic link or not a directory, or a final name there that is a link or not a
  regular file, is refused before the kernel is asked. Nothing is written into the module.
- ``drawing check DRAWING_RECORD PART_RECORD``: the rules, one verdict per line; reads four
  files, runs nothing and needs no kernel.

The first two run the kernel, which lives in a provisioned tool environment
(``toolenv/provision.py``): ``--tool-environment`` names it, or the variable of the same name.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from physgate.build.drawings.check import (
    CHECKS,
    EXIT_FAILS,
    EXIT_PASSES,
    EXIT_REFUSED,
    EXIT_STALE,
    RECORDED_NOT_CHECKED,
    Finding,
    check_drawing,
    exit_status,
)
from physgate.build.drawings.kernel import (
    ENVIRONMENT_VARIABLE,
    KernelError,
    example_part,
    project,
)
from physgate.build.drawings.record import (
    RecordError,
    entry_of,
    load_part,
    parse_projection,
    render,
)
from physgate.build.drawings.sheet import LEFT_OUT, RULE, SHOWN, compose

#: The plate's lengths the example part may be given, in millimetres: room for its four holes,
#: and one sheet at the scales tried.
LENGTH_RANGE_MM = (20.0, 400.0)
EXAMPLE_LENGTH_MM = 110.0

DESCRIPTION = (
    "One drawing from one part, checked, and stale when the part changes. make: the standard "
    "views (front, top, side from the left, isometric) projected by the CAD kernel's own "
    "hidden-line projection, placed first-angle on one A3 sheet as SVG, with the overall "
    "dimensions and a title block that carries the part's name, the units, the scale and the "
    "part's geometry hash; a record beside it, every number a value with its unit. check: the "
    "drawing's hash against the part's current one (else STALE), every view present and drawn, "
    f"every title block field present and as recorded, and {RULE}. A drawing is made again "
    f"from the part, never patched. This is {SHOWN}; {LEFT_OUT}."
)
#: What check holds a drawing to, and what it does not: it redraws nothing.
CHECK_HOLDS = (
    "check reads four files (the drawing's record, the SVG and the projection beside it, and the "
    "part's record) and runs nothing. It catches a part that changed (STALE), an SVG edited "
    "without its record, a missing view or title field, and a dimension that does not match the "
    "part; and it holds every field of the drawing's record to the SVG, the projection file or "
    "the part's record, except what is "
    f"recorded and not checked: {RECORDED_NOT_CHECKED}. It does not redraw the views, so it "
    "does not catch a drawing and its record edited together and their digests written again, "
    "a view of another part with the same numbers of lines, or a label or a title that says "
    "another projection than the lines are drawn in."
)


def add_parser(subparsers: Any) -> None:  # noqa: ANN401 - argparse's private subparsers type
    """Register ``drawing example-part``, ``drawing make`` and ``drawing check``."""
    drawing = subparsers.add_parser(
        "drawing", help="one drawing from one part, checked, stale when the part changes"
    )
    actions = drawing.add_subparsers(dest="drawing_action", required=True)

    example = actions.add_parser(
        "example-part",
        help="write the chassis fixture's plate into a module directory (needs the kernel)",
        description=(
            "Write the chassis fixture's plate (60 by 3 mm, four 3.2 mm holes, its length as "
            "given) into MODULE: plate.result.json and exports/plate.step and .stl, by the tool "
            "environment's geometry helper. Run it again with another length to change the "
            f"part. A fixture for showing the drawing, not a design. This is {SHOWN}."
        ),
    )
    example.add_argument("module", type=Path, help="the module directory to write the part into")
    example.add_argument(
        "--length",
        type=float,
        default=EXAMPLE_LENGTH_MM,
        help=f"the plate's length in mm (default {EXAMPLE_LENGTH_MM:g})",
    )
    _tree_option(example)
    example.set_defaults(func=_example)

    make = actions.add_parser(
        "make",
        help="make the drawing of a part from its record (needs the kernel)",
        description=DESCRIPTION,
    )
    make.add_argument("part", type=Path, help="the part's record, <part>.result.json")
    make.add_argument("--out", type=Path, required=True, help="the directory to write into")
    _tree_option(make)
    make.set_defaults(func=_make)

    check = actions.add_parser(
        "check",
        help="check a drawing against the part's record (reads only; no kernel)",
        description=(
            f"{DESCRIPTION} {CHECK_HOLDS} Exit status: 0 every check passes, 3 the drawing is "
            "stale (make it "
            "again; the other lines say what no longer agrees), 1 it is not stale and a check "
            "fails, 2 refused."
        ),
    )
    check.add_argument("drawing", type=Path, help="the drawing's record, <part>.drawing.json")
    check.add_argument("part", type=Path, help="the part's record, <part>.result.json")
    check.add_argument("--json", action="store_true", help="print the same as data")
    check.set_defaults(func=_check)


def _tree_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tool-environment",
        type=Path,
        default=None,
        help=(
            "the provisioned tool environment the CAD kernel lives in "
            f"(default: the {ENVIRONMENT_VARIABLE} variable)"
        ),
    )


def _refuse(message: str) -> int:
    print(json.dumps({"error": message}, sort_keys=True), file=sys.stderr)
    return EXIT_REFUSED


def _tree(args: argparse.Namespace) -> Path | None:
    named: Path | None = args.tool_environment
    if named is None:
        found = os.environ.get(ENVIRONMENT_VARIABLE, "")
        named = Path(found) if found else None
    return None if named is None else named.resolve()


def _example(args: argparse.Namespace) -> int:
    tree = _tree(args)
    if tree is None:
        return _refuse(f"name the tool environment: --tool-environment or {ENVIRONMENT_VARIABLE}")
    low, high = LENGTH_RANGE_MM
    if not low <= args.length <= high:
        return _refuse(f"the plate's length is from {low:g} to {high:g} mm, not {args.length:g}")
    try:
        geometry_hash = example_part(tree, args.module, args.length)
    except KernelError as exc:
        return _refuse(str(exc))
    except OSError as exc:
        return _refuse(f"the part cannot be written into {args.module}: {exc.strerror or exc}")
    print(f"physgate drawing example-part: {SHOWN}.")
    print(f"part: plate, {args.length:g} by 60 by 3 mm, written into {args.module}")
    print(f"geometry hash: {geometry_hash}")
    return EXIT_PASSES


def _make(args: argparse.Namespace) -> int:
    tree = _tree(args)
    if tree is None:
        return _refuse(f"name the tool environment: --tool-environment or {ENVIRONMENT_VARIABLE}")
    part_path: Path = args.part
    out: Path = args.out
    try:
        part = load_part(part_path)
        name = part.part
        written = (f"{name}.projection.json", f"{name}.svg", f"{name}.drawing.json")
        unwritable = _unwritable(out, written)
        if unwritable is not None:
            return _refuse(unwritable)
        step = part.step()
        step_path = part_path.parent / step.file
        held = entry_of(step_path.read_bytes(), step.file)
        if held != step:
            return _refuse(
                f"{step.file} is not the file the part's record names: its sha256 is "
                f"{held.sha256}, and the record names {step.sha256}"
            )
        projection = parse_projection(project(tree, step_path))
        made = compose(projection, part, step)
    except OSError as exc:
        return _refuse(f"the part's STEP file cannot be read: {exc.strerror}")
    except (RecordError, KernelError) as exc:
        return _refuse(str(exc))
    try:
        _write(
            out, dict(zip(written, (made.projection, made.svg, render(made.record)), strict=True))
        )
    except OSError as exc:
        return _refuse(f"the drawing cannot be written into {out}: {exc.strerror or exc}")
    record = made.record
    print(f"physgate drawing make: {SHOWN}.")
    print(f"part: {name}, drawn from {step.file}")
    print(f"geometry hash: {record.geometry_hash}")
    print(f"views: {', '.join(v.name for v in record.views)}; scale {record.scale.shown_as}")
    print("overall: " + ", ".join(f"{q} {m.value:.1f} mm" for q, m in record.overall.items()))
    print(f"written: {out / (name + '.svg')}, {out / (name + '.drawing.json')}")
    print(LEFT_OUT[0].upper() + LEFT_OUT[1:] + ".")
    return EXIT_PASSES


def _unwritable(out: Path, names: tuple[str, ...]) -> str | None:
    """Why ``make`` will not write ``names`` into ``out``, or None when it will."""
    if out.is_symlink():
        return f"--out {out} is a symbolic link: name the directory itself"
    if out.exists() and not out.is_dir():
        return f"--out {out} is not a directory"
    for name in names:
        target = out / name
        if target.is_symlink():
            return f"{target} is a symbolic link: make replaces only files it wrote, never a link"
        if target.exists() and not target.is_file():
            return f"{target} is there and is not a regular file: make does not replace it"
    return None


def _write(out: Path, files: dict[str, str]) -> None:
    """Write each file under a temporary name of its own in ``out``, then rename it over its name.

    The temporary name is new (opened exclusively, never through a link), and a rename replaces
    whatever is at the final name rather than writing through it.
    """
    out.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for name, text in files.items():
        temporary = out / f".{name}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(temporary, flags, 0o666)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(text.encode("utf-8"))
            os.replace(temporary, out / name)
        finally:
            temporary.unlink(missing_ok=True)


def _check(args: argparse.Namespace) -> int:
    try:
        findings = check_drawing(args.drawing, args.part)
    except RecordError as exc:
        return _refuse(str(exc))
    status = exit_status(findings)
    if args.json:
        data = {
            "shown": SHOWN,
            "left_out": LEFT_OUT,
            "drawing": str(args.drawing),
            "part": str(args.part),
            "checks": [
                {"check": f.check, "verdict": f.verdict, "message": f.message} for f in findings
            ],
            "exit_status": status,
        }
        print(json.dumps(data, indent=1))
    else:
        print(_table(args.drawing, args.part, findings, status))
    return status


SUMMARY = {
    EXIT_PASSES: "every check passes",
    EXIT_FAILS: "a check fails",
    EXIT_STALE: "the drawing is STALE: the part changed after it was made; make it again",
}


def _table(drawing: Path, part: Path, findings: tuple[Finding, ...], status: int) -> str:
    width = max(len(name) for name in CHECKS)
    out = [
        f"physgate drawing check: {SHOWN}.",
        f"drawing: {drawing}",
        f"part's record (the part's current state): {part}",
        "",
    ]
    out += [f"{f.check.ljust(width)}  {f.verdict.upper().ljust(6)}  {f.message}" for f in findings]
    out += ["", f"{len(findings)} checks: {SUMMARY[status]}."]
    out.append(LEFT_OUT[0].upper() + LEFT_OUT[1:] + ".")
    return "\n".join(out)
