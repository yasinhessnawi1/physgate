"""The circuit helper runs KiCad's rules check and exports, and answers with what the tool said.

The helper is loaded from its file as the tool environment's interpreter loads it, and given a
stand-in ``kicad-cli`` on its search path that writes what the real program writes (a JSON
report, a netlist with its date and source, a parts list, a PDF) and exits as told. Read here:
the program's exit code is the number it was; the findings are counted by severity and by type
over all of them and listed up to a bound, each text cut; the report's date, the netlist's date
and its source are set so one platform repeats the bytes; the parts list asks for the fixed
fields; every file is named by name, size and sha256; nothing in an answer is a truth value or
a judgement's name; and a missing program, a bad name or a file that is no schematic is refused.
The real program is the integration test's.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"


def _helper(name: str) -> ModuleType:
    path = HELPERS / f"{name}.py"
    if not path.is_file():
        # A missing helper fails each row on its first assertion, not at setup.
        return ModuleType(name)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _raised(call: Callable[[], object]) -> BaseException | None:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _finding(n: int, severity: str = "error", kind: str = "pin_not_connected") -> dict[str, Any]:
    return {
        "type": kind,
        "severity": severity,
        "description": f"Pin not connected {n}",
        "items": [{"description": "Pin 2 of R1", "pos": {"x": 1.0, "y": 2.0}, "uuid": "u"}],
    }


#: The stand-in program: it writes a canned output for each command and logs its arguments.
STAND_IN = r"""#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_PLACES") and args[:1] == ["sch"]:
    with open(os.environ["FAKE_PLACES"], "a") as places:
        seen = {"cwd": os.getcwd(), "schematic": args[-1],
                "beside": sorted(os.listdir(os.path.dirname(args[-1])))}
        places.write(json.dumps(seen) + "\n")
if args == ["--version"]:
    print("10.0.8"); sys.exit(0)
out = args[args.index("-o") + 1]
if args[:2] == ["sch", "erc"]:
    with open(out, "w") as f:
        f.write(open(os.environ["FAKE_REPORT"]).read())
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
if args[:3] == ["sch", "export", "netlist"]:
    with open(out, "w") as f:
        f.write('(export (version "E")\n  (design\n    (source "/abs/where/board.kicad_sch")\n'
                '    (date "Sun 15 Nov 2026 05:00:00 UTC")\n    (tool "Eeschema 10.0.8"))\n'
                '  (nets (net (code "1") (name "/VIN"))))\n')
elif args[:3] == ["sch", "export", "bom"]:
    with open(out, "w") as f:
        f.write('"Reference","Value","Footprint","Quantity","DNP"\n"R1","10k","R_0603","1",""\n')
elif args[:3] == ["sch", "export", "pdf"]:
    with open(out, "wb") as f:
        f.write(b"%PDF-1.5\n1 0 obj << /Type /Page >> endobj\n%%EOF\n")
sys.exit(0)
"""


@pytest.fixture
def circuit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    program = bin_dir / "kicad-cli"
    program.write_text(STAND_IN.replace("{python}", sys.executable), encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    yield _helper("circuit")


def _module(tmp_path: Path) -> tuple[Path, Path]:
    module = tmp_path / "modules" / "board"
    module.mkdir(parents=True)
    schematic = module / "board.kicad_sch"
    schematic.write_text("(kicad_sch (version 20250114))\n", encoding="utf-8")
    return module, schematic


def _canned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: str) -> None:
    """Have the stand-in write ``report``, through a file: a variable holds less than a report."""
    canned = tmp_path / "canned-report"
    canned.write_text(report, encoding="utf-8")
    monkeypatch.setenv("FAKE_REPORT", str(canned))


def _report(findings: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "$schema": "https://schemas.kicad.org/erc.v1.json",
            "coordinate_units": "mm",
            "date": "2026-11-15T05:00:00+0000",
            "kicad_version": "10.0.8",
            "sheets": [{"path": "/", "uuid_path": "/x", "violations": findings}],
            "source": "board.kicad_sch",
        },
        indent=2,
    )


def _truth_values(found: Any, where: str = "") -> list[str]:  # noqa: ANN401 - any part
    if isinstance(found, bool):
        return [where]
    if isinstance(found, dict):
        return [w for k, v in found.items() for w in _truth_values(v, f"{where}.{k}")]
    if isinstance(found, list):
        return [w for i, v in enumerate(found) for w in _truth_values(v, f"{where}[{i}]")]
    return []


def test_the_rules_check_reports_the_exit_code_counts_and_findings_as_the_tool_gave_them(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    findings = [_finding(1), _finding(2), _finding(3, "warning", "lib_symbol_mismatch")]
    _canned(monkeypatch, tmp_path, _report(findings))
    monkeypatch.setenv("FAKE_EXIT", "5")
    found = circuit.rules_check(schematic, module, "board")
    assert found["kind"] == "rules_check"
    assert found["exit_code"] == 5
    counts = found["counts"]
    assert counts["total"] == {"value": 3, "unit": "1"}
    assert counts["by_severity"] == {
        "error": {"value": 2, "unit": "1"},
        "warning": {"value": 1, "unit": "1"},
    }
    assert counts["by_type"]["pin_not_connected"] == {"value": 2, "unit": "1"}
    assert [f["description"] for f in found["findings"]] == [
        "Pin not connected 1",
        "Pin not connected 2",
        "Pin not connected 3",
    ]
    assert found["findings"][0]["items"] == ["Pin 2 of R1"]
    report = module / "exports" / "board.erc.json"
    assert found["report"]["file"] == "exports/board.erc.json"
    assert found["report"]["sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert json.loads(report.read_text())["date"] == "2000-01-01T00:00:00"
    assert found["tool"]["kicad-cli"] == "10.0.8"
    assert _truth_values(found) == []
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    erc = next(call for call in calls if call[:2] == ["sch", "erc"])
    assert {"--format", "json", "--severity-all", "--exit-code-violations"} <= set(erc)


def test_findings_past_the_bound_are_counted_but_not_listed_and_texts_are_cut(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    many = [_finding(n) for n in range(1205)]
    many[0]["description"] = "x" * 500 + "\x07"
    _canned(monkeypatch, tmp_path, _report(many))
    found = circuit.rules_check(schematic, module, "board")
    assert found["counts"]["total"]["value"] == 1205
    assert found["counts"]["listed"]["value"] == 1000
    assert len(found["findings"]) == 1000
    assert found["findings"][0]["description"] == "x" * 200


def test_the_exports_are_named_by_size_and_digest_with_dates_and_source_set(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    temp = tmp_path / "session-temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    found = circuit.exports(schematic, module, "board")
    assert found["kind"] == "ecad_exports"
    names = [entry["file"] for entry in found["exports"]]
    assert names == ["exports/board.net", "exports/board.csv"]
    # The PDF is the session's own reading, in its temporary directory: a role commits none.
    pdf = found["pdf"]
    place = Path(pdf["file"])
    assert place.name == "board.pdf" and place.parent.parent == temp, place
    assert place.parent.name.startswith("circuit-"), place
    body = Path(pdf["file"]).read_bytes()
    assert body.startswith(b"%PDF-")
    assert pdf["sha256"] == hashlib.sha256(body).hexdigest()
    assert sorted(p.name for p in (module / "exports").iterdir()) == ["board.csv", "board.net"]
    for entry in found["exports"]:
        body = (module / entry["file"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(body).hexdigest()
        assert entry["size"] == {"value": len(body), "unit": "byte"}
    netlist = (module / "exports" / "board.net").read_text()
    assert '(date "2000-01-01T00:00:00")' in netlist
    assert '(source "board.kicad_sch")' in netlist
    assert "/abs/where" not in netlist
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    bom = next(call for call in calls if call[:3] == ["sch", "export", "bom"])
    assert bom[bom.index("--fields") + 1] == "Reference,Value,Footprint,${QUANTITY},${DNP}"
    assert bom[bom.index("--labels") + 1] == "Reference,Value,Footprint,Quantity,DNP"
    assert _truth_values(found) == []


def test_a_link_at_a_fixed_place_in_the_temporary_directory_is_neither_followed_nor_written(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "exports"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    temp, elsewhere = tmp_path / "session-temp", tmp_path / "elsewhere"
    temp.mkdir()
    elsewhere.mkdir()
    # A folder and a file named as a fixed path would be, each a link out of the directory.
    (temp / "circuit").symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / "board.pdf").symlink_to(tmp_path / "victim")
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    found = [circuit.exports(schematic, module, "board")["pdf"]["file"] for _ in range(2)]
    assert not (tmp_path / "victim").exists()
    assert sorted(p.name for p in elsewhere.iterdir()) == ["board.pdf"]
    # Each call writes into a folder of its own, made new in the temporary directory.
    assert len({Path(file).parent for file in found}) == 2
    for file in found:
        parent = Path(file).parent
        assert parent.parent == temp and not parent.is_symlink(), file


def test_without_the_program_on_the_search_path_the_helper_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    circuit = _helper("circuit")
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    module, schematic = _module(tmp_path)
    raised = _raised(lambda: circuit.rules_check(schematic, module, "board"))
    assert type(raised).__name__ == "HelperRefusedError", raised
    assert "kicad-cli" in str(raised)


@pytest.mark.parametrize("name", ["Board", "../up", "", "a" * 65, "a b"])
def test_a_name_that_is_no_export_name_is_refused(
    circuit: ModuleType, tmp_path: Path, name: str
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    raised = _raised(lambda: circuit.exports(schematic, module, name))
    assert type(raised).__name__ == "HelperRefusedError", raised


def test_a_file_that_is_no_schematic_is_refused(circuit: ModuleType, tmp_path: Path) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, _ = _module(tmp_path)
    other = module / "board.txt"
    other.write_text("not a schematic", encoding="utf-8")
    raised = _raised(lambda: circuit.rules_check(other, module, "board"))
    assert type(raised).__name__ == "HelperRefusedError", raised


def test_a_report_that_is_no_json_is_refused(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    _canned(monkeypatch, tmp_path, "this is not JSON")
    raised = _raised(lambda: circuit.rules_check(schematic, module, "board"))
    assert type(raised).__name__ == "HelperRefusedError", raised


def test_a_result_with_a_judgement_added_is_refused(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    _canned(monkeypatch, tmp_path, _report([_finding(1)]))
    found = circuit.rules_check(schematic, module, "board")
    result_file = _helper("result_file")
    for field, value in (("clean", 1), ("violations", 1), ("findings", [{"ok": True}])):
        changed = dict(found) | {field: value}
        if field != "findings":
            changed.pop("findings")
            changed[field] = value
        raised = _raised(partial(result_file.checked, changed))
        assert type(raised).__name__ == "HelperRefusedError", (field, raised)


# ---- the schematic alone, as the commit check regenerates it -------------------------------------

#: A schematic that draws on a sub-sheet: a sheet symbol naming another schematic file.
WITH_SUB_SHEET = (
    "(kicad_sch (version 20250114)\n"
    '  (sheet (at 10 10) (size 20 10) (property "Sheetfile" "power.kicad_sch"))\n'
    '  (sheet_instances (path "/" (page "1"))))\n'
)


def test_the_program_is_given_a_copy_of_the_schematic_alone_in_a_folder_of_its_own(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    # A project file beside it, which would set the rules' severities: never read.
    (module / "board.kicad_pro").write_text('{"erc": {"rule_severities": {}}}', "utf-8")
    temp = tmp_path / "session-temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setenv("FAKE_PLACES", str(tmp_path / "places.log"))
    _canned(monkeypatch, tmp_path, _report([]))
    circuit.rules_check(schematic, module, "board")
    circuit.exports(schematic, module, "board")
    seen = [json.loads(line) for line in (tmp_path / "places.log").read_text().splitlines()]
    assert len(seen) == 4, seen
    for call in seen:
        copy = Path(call["schematic"])
        assert copy != schematic and not copy.is_relative_to(module), call
        assert copy.name == "board.kicad_sch" and call["beside"] == ["board.kicad_sch"], call
        assert Path(call["cwd"]) == copy.parent and copy.parent.parent == temp, call
        assert not copy.parent.exists(), call
    netlist = (module / "exports" / "board.net").read_text()
    assert '(source "board.kicad_sch")' in netlist


def test_a_schematic_that_draws_on_a_sub_sheet_is_refused_in_words_that_say_so(
    circuit: ModuleType, tmp_path: Path
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_text(WITH_SUB_SHEET, encoding="utf-8")
    for call in (circuit.rules_check, circuit.exports):
        raised = _raised(partial(call, schematic, module, "board"))
        assert isinstance(raised, circuit.HelperRefusedError), raised
        assert "sub-sheet" in str(raised), raised
    assert not (tmp_path / "calls.log").exists()


def _regenerate(tmp_path: Path, schematic: Path, module: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(HELPERS / "circuit.py"), "regenerate", "--", str(schematic),
         str(module), "board"],
        env={**os.environ, "TMPDIR": str(tmp_path)}, capture_output=True, text=True,
        timeout=120, check=False,
    )  # fmt: skip


def test_regenerate_writes_the_three_text_exports_and_no_pdf(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    _canned(monkeypatch, tmp_path, _report([_finding(1)]))
    done = _regenerate(tmp_path, schematic, module)
    assert done.returncode == 0, done.stderr[-2000:]
    assert (module / "exports").is_dir(), "regenerate wrote no exports"
    names = sorted(p.name for p in (module / "exports").iterdir())
    assert names == ["board.csv", "board.erc.json", "board.net"]
    calls = [json.loads(line) for line in (tmp_path / "calls.log").read_text().splitlines()]
    assert not [call for call in calls if call[:3] == ["sch", "export", "pdf"]], calls


def test_regenerate_exits_three_on_a_sub_sheet_and_writes_nothing(
    circuit: ModuleType, tmp_path: Path
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_text(WITH_SUB_SHEET, encoding="utf-8")
    done = _regenerate(tmp_path, schematic, module)
    assert done.returncode == 3, done.stderr[-2000:]
    assert "sub-sheet" in done.stderr, done.stderr[-2000:]
    exports = module / "exports"
    assert not exports.exists() or not list(exports.iterdir())


def test_provisioning_records_how_the_exports_are_regenerated() -> None:
    spec = importlib.util.spec_from_file_location("provision_t8", REPO / "toolenv" / "provision.py")
    assert spec is not None and spec.loader is not None
    provision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provision)
    assert hasattr(provision, "derivations"), "provisioning writes no derived.json"
    (entry,) = provision.derivations()["derivations"]
    assert entry["source"] == ".kicad_sch"
    assert entry["products"] == [".erc.json", ".net", ".csv"]
    assert entry["argv"] == [
        "{interpreter}", "-I", "{root}/helpers/circuit.py", "regenerate", "{source}", "{module}",
        "{name}",
    ]  # fmt: skip
    assert "sub-sheet" in entry["refusals"]["3"]


# ---- the schematic read as one s-expression: every form of a sheet symbol, and what is none ----

#: A sheet symbol as KiCad writes it, and as a reader that ends a word at a parenthesis or a quote
#: reads one: each draws on a sub-sheet.
SHEET_FORMS = {
    "spaced": '  (sheet (at 10 10) (size 20 10) (property "Sheetfile" "power.kicad_sch"))\n',
    "parenthesis": '  (sheet(at 10 10)(size 20 10)(property "Sheetfile" "power.kicad_sch"))\n',
    "quote": '  (sheet"x" (at 10 10) (property "Sheetfile" "power.kicad_sch"))\n',
    "new lines": "  (\n   sheet\n (at 10 10))\n",
    "capitals": "  (SHEET (at 10 10))\n",
    "quoted word": '  ("sheet" (at 10 10))\n',
}

#: Files that are no one s-expression of lists, strings and words: none is read as a schematic.
UNREADABLE = {
    "unclosed list": "(kicad_sch (version 20250114)\n",
    "list closed twice": "(kicad_sch (version 20250114)))\n",
    "unclosed string": '(kicad_sch (title "board))\n',
    "text after the list": "(kicad_sch (version 20250114))\n(version 1)\n",
    "a word outside every list": "kicad_sch\n",
    "empty": "",
    "a control byte outside a string": "(kicad_sch \x01(version 20250114))\n",
    "a byte past ASCII outside a string": "(kicad_sch (versión 20250114))\n",
    "a comment": "(kicad_sch\n# a comment\n (version 20250114))\n",
}

#: A schematic that names a sheet without drawing on one: its sheet instances, and words in a
#: string, escaped quotes and a letter past ASCII among them.
NO_SUB_SHEET = (
    "(kicad_sch (version 20250114)\n"
    '  (text "(sheet (at 0 0)) and a \\"quoted\\" (sheet word, é" (at 0 0 0))\n'
    '  (sheet_instances (path "/" (page "1"))))\n'
)


def _drawn(text: str) -> str:
    return (
        "(kicad_sch (version 20250114)\n" + text + '  (sheet_instances (path "/" (page "1"))))\n'
    )


@pytest.mark.parametrize("form", sorted(SHEET_FORMS))
def test_every_form_of_a_sheet_symbol_is_read_as_one_and_refused(
    circuit: ModuleType, tmp_path: Path, form: str
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_text(_drawn(SHEET_FORMS[form]), encoding="utf-8")
    for call in (circuit.rules_check, circuit.exports):
        raised = _raised(partial(call, schematic, module, "board"))
        assert isinstance(raised, circuit.SubSheetRefusedError), (form, raised)
    assert not (tmp_path / "calls.log").exists()


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_a_schematic_that_cannot_be_read_as_one_s_expression_is_refused_unrun(
    circuit: ModuleType, tmp_path: Path, case: str
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_bytes(UNREADABLE[case].encode())
    for call in (circuit.rules_check, circuit.exports):
        raised = _raised(partial(call, schematic, module, "board"))
        assert isinstance(raised, circuit.HelperRefusedError), (case, raised)
        assert not isinstance(raised, circuit.SubSheetRefusedError), (case, raised)
        assert "s-expression" in str(raised), raised
    assert not (tmp_path / "calls.log").exists()


def test_a_schematic_that_only_names_a_sheet_is_exported_in_session_and_regenerated(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_text(NO_SUB_SHEET, encoding="utf-8")
    _canned(monkeypatch, tmp_path, _report([]))
    for call in (circuit.rules_check, circuit.exports):
        raised = _raised(partial(call, schematic, module, "board"))
        assert raised is None, raised
    done = _regenerate(tmp_path, schematic, module)
    assert done.returncode == 0, done.stderr[-2000:]


@pytest.mark.parametrize(
    ("text", "code", "said"),
    [
        (_drawn(SHEET_FORMS["parenthesis"]), 3, "sub-sheet"),
        (_drawn(SHEET_FORMS["quote"]), 3, "sub-sheet"),
        (UNREADABLE["unclosed list"], 1, "s-expression"),
    ],
    ids=["parenthesis", "quote", "unreadable"],
)
def test_regenerate_refuses_what_the_session_refuses_with_its_exit_code(
    circuit: ModuleType, tmp_path: Path, text: str, code: int, said: str
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    schematic.write_text(text, encoding="utf-8")
    done = _regenerate(tmp_path, schematic, module)
    assert done.returncode == code, done.stderr[-2000:]
    assert said in done.stderr, done.stderr[-2000:]
    assert not (tmp_path / "calls.log").exists()


def test_regenerate_takes_its_paths_after_the_end_of_the_options(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    module, schematic = _module(tmp_path)
    _canned(monkeypatch, tmp_path, _report([]))
    bare = subprocess.run(
        [sys.executable, "-I", str(HELPERS / "circuit.py"), "regenerate", str(schematic),
         str(module), "board"],
        env={**os.environ, "TMPDIR": str(tmp_path)}, capture_output=True, text=True,
        timeout=120, check=False,
    )  # fmt: skip
    assert bare.returncode == 2, bare.stderr[-2000:]
    assert "usage" in bare.stderr, bare.stderr[-2000:]
    assert not (tmp_path / "calls.log").exists()


def test_the_program_s_output_is_never_held_in_memory(
    circuit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(circuit, "rules_check"), "the tool environment has no circuit helper"
    seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real = subprocess.run

    def recording(*args: Any, **given: Any) -> Any:  # noqa: ANN401
        seen.append((args, given))
        return real(*args, **given)

    module, schematic = _module(tmp_path)
    _canned(monkeypatch, tmp_path, _report([]))
    monkeypatch.setattr(circuit.subprocess, "run", recording)
    circuit.rules_check(schematic, module, "board")
    circuit.exports(schematic, module, "board")
    runs = [given for args, given in seen if list(args[0])[1:2] == ["sch"]]
    assert len(runs) == 4, seen
    for given in runs:
        assert not given.get("capture_output"), given
        assert given.get("stdout") == subprocess.DEVNULL, given
        assert given.get("stderr") == subprocess.DEVNULL, given
