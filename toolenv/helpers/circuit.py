"""KiCad's rules check and exports of a schematic, as the tool's own report, counted and bounded.

A module's script names its schematic (``.kicad_sch``, written by hand or generated) and gets:

- :func:`rules_check`: KiCad's electrical rules check run over the schematic, its JSON report
  written to ``<module>/exports/<name>.erc.json``, and an answer that carries the program's exit
  code as the number it was, the findings counted by severity and by type, and each finding's
  type, severity and texts, cut to a bound; the report itself is the evidence;
- :func:`exports`: the netlist (``<name>.net``, KiCad's S-expression) and the parts list
  (``<name>.csv``, a fixed list of fields), each by name, size and sha256; and a PDF of the
  schematic for the session's own reading, written into the session's temporary directory and
  never into the module: a reviewer is not shown a PDF's text, so a role commits none.

The program is given a copy of the schematic alone, in a folder made new for the call and
removed after it: a project file beside the schematic, which would set the rules' severities,
is never read, so every report is made with the release's own rules, and the commit check that
regenerates the exports from the committed schematic (``python circuit.py regenerate``) gets
the same bytes. A schematic that draws on a sub-sheet is refused: one sheet per schematic.

The report's one date and the netlist's one date are set to a fixed time and the netlist's
source to the schematic's path in the module, so one platform repeats a text export's bytes.
Nothing here says whether a schematic is good: no field judges, no limit is taken, and a finding
is reported as KiCad words it. Whether a finding matters is the reviewer's to say.

``kicad-cli`` is found on the search path a session is given. This file runs on the tool
environment's interpreter, needs the standard library only, and imports nothing of the harness.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import SCHEMA, HelperRefusedError, checked, quantity  # noqa: E402

#: A name the exports are written under: as a part's name.
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
#: The module's folder the exports are written into.
EXPORTS = "exports"
#: The program, found on the session's search path.
PROGRAM = "kicad-cli"
#: The time the reports' dates are set to.
FIXED_DATE = "2000-01-01T00:00:00"
#: How long one run of the program may take.
TIMEOUT_S = 600
#: The most of a report that is read, and of a text kept from it.
MAX_REPORT_BYTES = 2_000_000
MAX_TEXT = 200
#: The most findings an answer lists one by one; the counts are over all of them.
MAX_FINDINGS = 1000
#: The parts list's fields, as KiCad names them, and the header each is given.
PARTS_FIELDS = ("Reference", "Value", "Footprint", "${QUANTITY}", "${DNP}")
PARTS_LABELS = ("Reference", "Value", "Footprint", "Quantity", "DNP")

#: The one date of a report, and the netlist's date and source, each as the group replaced.
_DATE_JSON = re.compile(rb'^\s*"date"\s*:\s*("[^"\n]*")', re.MULTILINE)
_DATE_NET = re.compile(rb'\(date ("[^"\n]*")\)')
_SOURCE_NET = re.compile(rb'\(source ("[^"\n]*")\)')
#: A sheet symbol: the schematic draws on a sub-sheet, another file.
_SUB_SHEET = re.compile(rb"\(\s*sheet\s")
#: The exit code ``regenerate`` ends with when the schematic draws on a sub-sheet.
SUB_SHEET_EXIT = 3


class SubSheetRefusedError(HelperRefusedError):
    """The schematic draws on a sub-sheet; the helper works on one sheet per schematic."""


def _name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise HelperRefusedError(
            "an export's name is lower-case letters, digits, - and _, at most 64 characters"
        )
    return name


def _places(schematic: str | os.PathLike[str], module: str | os.PathLike[str]) -> tuple[str, str]:
    path, folder = os.fspath(schematic), os.fspath(module)
    if not path.endswith(".kicad_sch") or not os.path.isfile(path):
        raise HelperRefusedError("a schematic is an existing file named <something>.kicad_sch")
    if not os.path.isdir(folder):
        raise HelperRefusedError("the module is an existing folder")
    with open(path, "rb") as handle:
        if _SUB_SHEET.search(handle.read()):
            raise SubSheetRefusedError(
                "the schematic draws on a sub-sheet; one sheet per schematic is checked and "
                "exported: draw the circuit in one sheet"
            )
    os.makedirs(os.path.join(folder, EXPORTS), exist_ok=True)
    return path, folder


def _alone(path: str) -> str:
    """A copy of the schematic alone, in a folder made new for this call: the copy's path."""
    folder = tempfile.mkdtemp(prefix="circuit-copy-")
    copy = os.path.join(folder, os.path.basename(path))
    shutil.copyfile(path, copy)
    return copy


def _program() -> str:
    found = shutil.which(PROGRAM)
    if found is None:
        raise HelperRefusedError(f"{PROGRAM} is not on the search path")
    return found


def _run(argv: list[str], cwd: str) -> int:
    done = subprocess.run(  # noqa: S603 - the pinned program, with arguments built here
        argv, cwd=cwd, capture_output=True, timeout=TIMEOUT_S, check=False
    )
    return done.returncode


def version() -> str:
    """The program's own version, as it prints it."""
    done = subprocess.run(  # noqa: S603 - the pinned program, asked its version
        [_program(), "--version"], capture_output=True, text=True, timeout=60, check=False
    )
    return done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""


def file_entry(path: str, name: str) -> dict[str, Any]:
    """A written file as a result names it: its name in the module, its size and its sha256."""
    with open(path, "rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"file": name, "size": quantity(os.path.getsize(path), "byte"), "sha256": digest}


def _fixed(path: str, pattern: re.Pattern[bytes], replacement: bytes) -> None:
    """Put ``replacement`` in place of the first match of ``pattern``'s last group in ``path``."""
    with open(path, "rb") as handle:
        body = handle.read()
    found = pattern.search(body)
    if found is not None:
        start, end = found.span(found.lastindex or 0)
        body = body[:start] + replacement + body[end:]
    with open(path, "wb") as handle:
        handle.write(body)


def _cut(text: Any) -> str:  # noqa: ANN401 - a field of the tool's report
    return "".join(ch if ch.isprintable() else " " for ch in str(text))[:MAX_TEXT]


def _sheet_findings(sheet: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """A sheet's findings, read by their shape: each list of objects with a severity and a type.

    Not by the key the tool files them under, which is a judgement's word this helper does not
    write (``result_file.JUDGEMENT_WORDS``).
    """
    return [
        item
        for value in sheet.values()
        if isinstance(value, list)
        for item in value
        if isinstance(item, Mapping) and "severity" in item and "type" in item
    ]


def findings_of(report: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The counts by severity and by type, and the findings listed, of a parsed report."""
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    listed: list[dict[str, Any]] = []
    total = 0
    for sheet in report.get("sheets", []) or []:
        if not isinstance(sheet, Mapping):
            continue
        for found in _sheet_findings(sheet):
            total += 1
            severity, kind = _cut(found.get("severity", "")), _cut(found.get("type", ""))
            by_severity[severity] = by_severity.get(severity, 0) + 1
            by_type[kind] = by_type.get(kind, 0) + 1
            if len(listed) < MAX_FINDINGS:
                items = found.get("items", []) or []
                listed.append(
                    {
                        "sheet": _cut(sheet.get("path", "")),
                        "type": kind,
                        "severity": severity,
                        "description": _cut(found.get("description", "")),
                        "items": [
                            _cut(item.get("description", ""))
                            for item in items[:16]
                            if isinstance(item, Mapping)
                        ],
                    }
                )
    counts = {
        "total": quantity(total, "1"),
        "listed": quantity(len(listed), "1"),
        "by_severity": {key: quantity(n, "1") for key, n in sorted(by_severity.items())},
        "by_type": {key: quantity(n, "1") for key, n in sorted(by_type.items())},
    }
    return counts, listed


def rules_check(
    schematic: str | os.PathLike[str], module: str | os.PathLike[str], name: str
) -> dict[str, Any]:
    """Run the rules check on ``schematic``, its report to ``<module>/exports/<name>.erc.json``.

    Raises:
        HelperRefusedError: the name, the schematic or the module is not one, the program is
            not on the search path, or it wrote no report a JSON reader can read.
    """
    path, folder = _places(schematic, module)
    report = os.path.join(folder, EXPORTS, f"{_name(name)}.erc.json")
    argv = [_program(), "sch", "erc", "--format", "json", "--severity-all"]
    copy = _alone(path)
    try:
        code = _run([*argv, "--exit-code-violations", "-o", report, copy], os.path.dirname(copy))
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    if not os.path.isfile(report) or os.path.getsize(report) > MAX_REPORT_BYTES:
        raise HelperRefusedError("the rules check wrote no report, or one past the bound")
    _fixed(report, _DATE_JSON, json.dumps(FIXED_DATE).encode())
    try:
        with open(report, encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (ValueError, RecursionError):
        raise HelperRefusedError("the rules check's report is not JSON text") from None
    if not isinstance(parsed, Mapping):
        raise HelperRefusedError("the rules check's report is not a JSON object")
    counts, listed = findings_of(parsed)
    return checked(
        {
            "schema": SCHEMA,
            "kind": "rules_check",
            "schematic": os.path.relpath(path, folder),
            "report": file_entry(report, os.path.relpath(report, folder)),
            "exit_code": code,
            "counts": counts,
            "findings": listed,
            "tool": {PROGRAM: version(), "report_version": _cut(parsed.get("kicad_version", ""))},
        }
    )


def exports(
    schematic: str | os.PathLike[str],
    module: str | os.PathLike[str],
    name: str,
    *,
    reading: bool = True,
) -> dict[str, Any]:
    """Write ``<module>/exports/<name>.net`` and ``.csv`` from ``schematic``, and a PDF of it.

    The PDF goes into a folder made new for the call in the session's temporary directory
    (``<temp>/circuit-<random>/<name>.pdf``), named in the answer by its full path, size and
    sha256. With ``reading`` false no PDF is made and the answer names none.

    Raises:
        HelperRefusedError: the name, the schematic or the module is not one, the program is
            not on the search path, or an export was not written.
    """
    path, folder = _places(schematic, module)
    stem = os.path.join(folder, EXPORTS, _name(name))
    cli = _program()
    copy = _alone(path)
    try:
        codes, pdf = _exported(cli, copy, stem, name, reading=reading)
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    written = [f"{stem}.net", f"{stem}.csv"]
    if not all(os.path.isfile(file) for file in [*written, *([pdf] if pdf else [])]):
        raise HelperRefusedError(f"an export was not written; the program's exit codes: {codes}")
    _fixed(f"{stem}.net", _DATE_NET, json.dumps(FIXED_DATE).encode())
    source = os.path.relpath(path, folder).replace(os.sep, "/")
    _fixed(f"{stem}.net", _SOURCE_NET, json.dumps(source, ensure_ascii=False).encode())
    answer: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "ecad_exports",
        "schematic": os.path.relpath(path, folder),
        "exports": [file_entry(file, os.path.relpath(file, folder)) for file in written],
        "exit_codes": codes,
        "tool": {PROGRAM: version()},
    }
    if pdf:
        answer["pdf"] = file_entry(pdf, pdf)
    return checked(answer)


def _exported(
    cli: str, path: str, stem: str, name: str, *, reading: bool
) -> tuple[dict[str, int], str | None]:
    """Run the netlist, the parts list and, when ``reading``, the PDF on the copy at ``path``."""
    folder = os.path.dirname(path)
    pdf = None
    if reading:
        # A folder made new for this call, never a fixed place a link could already stand at.
        pdf = os.path.join(tempfile.mkdtemp(prefix="circuit-"), f"{name}.pdf")
    codes = {
        "netlist": _run(
            [cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", f"{stem}.net", path],
            folder,
        ),
        "parts_list": _run(
            [
                cli,
                "sch",
                "export",
                "bom",
                "--fields",
                ",".join(PARTS_FIELDS),
                "--labels",
                ",".join(PARTS_LABELS),
                "--group-by",
                "Value,Footprint",
                "--sort-field",
                "Reference",
                "-o",
                f"{stem}.csv",
                path,
            ],
            folder,
        ),  # fmt: skip
    }
    if pdf is not None:
        codes["pdf"] = _run([cli, "sch", "export", "pdf", "-o", pdf, path], folder)
    return codes, pdf


def regenerate(
    schematic: str | os.PathLike[str], module: str | os.PathLike[str], name: str
) -> None:
    """Write the three text exports of ``schematic`` as a session's calls write them; no PDF."""
    rules_check(schematic, module, name)
    exports(schematic, module, name, reading=False)


def main(argv: list[str]) -> int:
    """``regenerate <schematic> <module> <name>``: the commit check's call; its exit code."""
    if len(argv) != len(("regenerate", "schematic", "module", "name")) or argv[0] != "regenerate":
        print("usage: circuit.py regenerate <schematic> <module> <name>", file=sys.stderr)
        return 2
    try:
        regenerate(argv[1], argv[2], argv[3])
    except SubSheetRefusedError as exc:
        print(exc, file=sys.stderr)
        return SUB_SHEET_EXIT
    except HelperRefusedError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
