"""KiCad checks and exports a schematic offline, through the circuit helper, in a wired session.

A session is wired to both roots as the tool layer wires it (``toolenv.session.wire``): the
environment's interpreter and ``kicad-cli`` on its search path, KiCad's configuration in the
session's own temporary directory with the release's library tables linked in. The network is
taken away. Read here, on the pinned release:

- a hand-written schematic built from the pinned symbols, every pin joined: the rules check's
  exit code and counts; the same with two pins left open: the open pins counted by type;
- the netlist holds the nets and parts, the parts list one row per part; the PDF, one page,
  is in the session's temporary directory and not in the module;
- a second run gives the same bytes for the three text exports, and so does a session wired
  anew with its module at another path (each set's time printed: a measurement);
- a SKiDL script generates a schematic from the pinned libraries with tags set, and the rules
  check runs on it and its findings are reported, not judged (two runs place the parts apart
  even with a seed and fixed hashing: no repeat is held);
- nothing is written into either root, and in the test's own folder nothing outside the
  session's temporary directory, its home and the module.
- at commit, the three exports are regenerated from the committed schematic inside the tool
  containment (bubblewrap on Linux): an honest set passes, a hand-edited clean report and stale
  exports are refused, a project file that silences a rule changes nothing in the report, and
  a schematic that draws on a sub-sheet is refused in words that say so.

``PHYSGATE_KICAD_ROOT`` and ``PHYSGATE_TOOL_ENVIRONMENT`` name the two provisioned roots
(``toolenv/provision.py --dest ... --kicad-dest ...``) at this commit; without both, the rows
skip and say so.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from design_fixtures import offline_prefix

from physgate.orchestrator import exports
from physgate.toolenv.manifest import scan
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import wire

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
HELPERS = REPO / "toolenv" / "helpers"
NAMED_ROOT = os.environ.get("PHYSGATE_KICAD_ROOT", "")
NAMED_ENVIRONMENT = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
LINUX = sys.platform.startswith("linux")
SHARE = "app/share/kicad" if LINUX else "app/KiCad.app/Contents/SharedSupport"
TEXT_EXPORTS = (".erc.json", ".net", ".csv")


@dataclass(frozen=True)
class Session:
    """A wired session: its environment, its temporary directory, home and module."""

    env: dict[str, str]
    temp: Path
    home: Path
    module: Path
    roots: tuple[Path, Path]
    prefix: list[str]


def _roots() -> tuple[Path, Path]:
    if not (NAMED_ROOT and NAMED_ENVIRONMENT):
        pytest.skip("PHYSGATE_KICAD_ROOT and PHYSGATE_TOOL_ENVIRONMENT name no provisioned roots")
    return Path(NAMED_ENVIRONMENT), Path(NAMED_ROOT)


def _recorded(env: Path, kicad: Path) -> ToolEnvironment:
    python = env / "venv" / "bin" / "python"
    return ToolEnvironment(
        interpreter=str(python),
        resolved=str(python.resolve()),
        python_version="3.12.9",
        prefix=str(env / "venv"),
        distributions=(),
        native_tools=(),
        roots=(str(env), str(kicad)),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    yield _session_at(Path(os.path.realpath(tmp_path)), Path("repo") / "modules" / "board")


def _session_at(place: Path, module_at: Path) -> Session:
    """A session wired anew beneath ``place``, its module at ``module_at`` there."""
    env_root, kicad_root = _roots()
    temp, home, module = place / "temp", place / "home", place / module_at
    for folder in (temp, home, module):
        folder.mkdir(parents=True)
    taken = ("PATH", "HOME", "TMPDIR", "LANG")
    variables = wire(_recorded(env_root, kicad_root), bin_dir=place / "bin", temp=temp, taken=taken)
    env = {
        "PATH": f"{place / 'bin'}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(home),
        "TMPDIR": str(temp),
        "LANG": "C.UTF-8",
        **variables,
    }
    return Session(env, temp, home, module, (env_root, kicad_root), offline_prefix())


# ---- a schematic written by hand from the pinned symbols ---------------------------------------


def _expression(text: str, start: int) -> str:
    """The balanced expression that opens at ``start``, strings read as KiCad writes them."""
    depth, index, quoted = 0, start, False
    while True:
        char = text[index]
        if quoted:
            if char == "\\":
                index += 1
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
        index += 1


def _symbol(kicad: Path, library: str, name: str) -> tuple[str, dict[str, tuple[float, float]]]:
    """A pinned symbol as a schematic embeds it, and where each of its pins ends."""
    text = (kicad / SHARE / "symbols" / f"{library}.kicad_symdir" / f"{name}.kicad_sym").read_text(
        encoding="utf-8"
    )
    body = _expression(text, text.index(f'(symbol "{name}"'))
    pins = {
        found.group(4): (float(found.group(1)), float(found.group(2)))
        for found in re.finditer(
            r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\).*?\(number "([^"]+)"', body, re.S
        )
    }
    return body.replace(f'(symbol "{name}"', f'(symbol "{library}:{name}"', 1), pins


def _uid(number: int) -> str:
    return str(uuid.UUID(int=number))


ROOT_SHEET = _uid(1)
SCHEMATIC_VERSION = "20250114"


def _placed(lib_id: str, ref: str, value: str, footprint: str, at: tuple[float, float], n: int,
            pins: dict[str, tuple[float, float]]) -> str:  # fmt: skip
    x, y = at

    def field(key: str, text: str, dy: float, hide: str = "") -> str:
        return (
            f'\n    (property "{key}" "{text}" (at {x + 2.54} {y + dy} 0) '
            f"(effects (font (size 1.27 1.27)) (justify left){hide}))"
        )

    pin_lines = "".join(
        f'\n    (pin "{pin}" (uuid "{_uid(n * 100 + k)}"))' for k, pin in enumerate(sorted(pins), 1)
    )
    return (
        f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (exclude_from_sim no) '
        f"(in_bom yes) (on_board yes) (dnp no)\n"
        f'    (uuid "{_uid(n)}")'
        + field("Reference", ref, -1.27)
        + field("Value", value, 1.27)
        + field("Footprint", footprint, 0, " (hide yes)")
        + field("Datasheet", "~", 0, " (hide yes)")
        + field("Description", "", 0, " (hide yes)")
        + pin_lines
        + f'\n    (instances (project "board" (path "/{ROOT_SHEET}" (reference "{ref}") '
        "(unit 1)))))\n"
    )


def _label(name: str, at: tuple[float, float], n: int) -> str:
    return (
        f'  (label "{name}" (at {at[0]} {at[1]} 0) (effects (font (size 1.27 1.27)) '
        f'(justify left bottom)) (uuid "{_uid(n)}"))\n'
    )


def hand_written(kicad: Path, *, open_pins: bool) -> str:
    """A resistor across a two-pin connector; with ``open_pins``, its second pins left unjoined."""
    resistor, resistor_pins = _symbol(kicad, "Device", "R")
    connector, connector_pins = _symbol(kicad, "Connector_Generic", "Conn_01x02")
    r_at, j_at = (101.6, 101.6), (76.2, 101.6)
    r_end = {k: (r_at[0] + v[0], r_at[1] - v[1]) for k, v in resistor_pins.items()}
    j_end = {k: (j_at[0] + v[0], j_at[1] - v[1]) for k, v in connector_pins.items()}
    labels = _label("A", j_end["1"], 900) + _label("A", r_end["1"], 901)
    if not open_pins:
        labels += _label("B", j_end["2"], 902) + _label("B", r_end["2"], 903)
    return (
        f'(kicad_sch\n  (version {SCHEMATIC_VERSION})\n  (generator "physgate_fixture")\n'
        f'  (generator_version "1")\n  (uuid "{ROOT_SHEET}")\n  (paper "A4")\n'
        f"  (lib_symbols\n{resistor}\n{connector}\n  )\n"
        + labels
        + _placed(
            "Device:R", "R1", "10k", "Resistor_SMD:R_0603_1608Metric", r_at, 10, resistor_pins
        )  # fmt: skip
        + _placed(
            "Connector_Generic:Conn_01x02",
            "J1",
            "Conn_01x02",
            "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            j_at,
            20,
            connector_pins,
        )
        + '  (sheet_instances (path "/" (page "1")))\n)\n'
    )


# ---- running the helper in the session ---------------------------------------------------------

CALL = """
import json, sys
sys.path.insert(0, sys.argv[1])
import circuit
what, schematic, module, name = sys.argv[2:6]
print(json.dumps(getattr(circuit, what)(schematic, module, name), sort_keys=True))
"""


def _helper(session: Session, what: str, schematic: Path, name: str) -> dict[str, object]:
    done = subprocess.run(
        [
            *session.prefix,
            "python3",
            "-I",
            "-c",
            CALL,
            str(HELPERS),
            what,
            str(schematic),
            str(session.module),
            name,
        ],  # fmt: skip
        cwd=session.module,
        env=session.env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert done.returncode == 0, (what, done.stderr[-3000:])
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert isinstance(found, dict)
    return found


def _schematic(session: Session, *, open_pins: bool) -> Path:
    path = session.module / "board.kicad_sch"
    path.write_text(hand_written(session.roots[1], open_pins=open_pins), encoding="utf-8")
    return path


def _value(quantity: object) -> object:
    assert isinstance(quantity, dict) and set(quantity) == {"value", "unit"}, quantity
    return quantity["value"]


def test_a_sound_schematic_s_rules_check_reports_no_finding_and_exit_code_zero(
    session: Session,
) -> None:
    found = _helper(session, "rules_check", _schematic(session, open_pins=False), "board")
    counts = found["counts"]
    assert isinstance(counts, dict)
    assert (found["exit_code"], _value(counts["total"])) == (0, 0), found["findings"]
    report = json.loads((session.module / "exports" / "board.erc.json").read_text("utf-8"))
    assert report["kicad_version"].startswith("10.0.8"), report["kicad_version"]
    assert report["date"] == "2000-01-01T00:00:00"


def test_two_open_pins_are_counted_by_type_and_the_exit_code_is_the_program_s(
    session: Session,
) -> None:
    found = _helper(session, "rules_check", _schematic(session, open_pins=True), "board")
    counts = found["counts"]
    assert isinstance(counts, dict)
    assert found["exit_code"] != 0
    by_type = counts["by_type"]
    assert isinstance(by_type, dict)
    assert _value(by_type["pin_not_connected"]) == 2, by_type
    findings = found["findings"]
    assert isinstance(findings, list)
    described = " ".join(str(item) for finding in findings for item in finding["items"])
    assert "R1" in described and "J1" in described, findings


def test_the_netlist_parts_list_and_pdf_hold_the_circuit(session: Session) -> None:
    found = _helper(session, "exports", _schematic(session, open_pins=False), "board")
    names = [entry["file"] for entry in found["exports"]]  # type: ignore[attr-defined]
    assert names == ["exports/board.net", "exports/board.csv"]
    netlist = (session.module / "exports" / "board.net").read_text(encoding="utf-8")
    assert netlist.startswith("(export")
    for net in ('(name "/A")', '(name "/B")'):
        assert net in netlist, net
    for ref in ('(ref "R1")', '(ref "J1")'):
        assert ref in netlist, ref
    assert '(date "2000-01-01T00:00:00")' in netlist
    assert '(source "board.kicad_sch")' in netlist
    rows = (session.module / "exports" / "board.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == '"Reference","Value","Footprint","Quantity","DNP"'
    assert sorted(row.split(",")[0] for row in rows[1:]) == ['"J1"', '"R1"']
    told = found["pdf"]
    assert isinstance(told, dict)
    place = Path(told["file"])
    assert place.name == "board.pdf" and place.parent.parent == session.temp, place
    pdf = Path(told["file"]).read_bytes()
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf)) == 1


@pytest.mark.parametrize("open_pins", [False, True])
def test_the_helper_s_real_exports_are_the_kinds_the_commit_time_rule_admits_under_their_caps(
    session: Session, open_pins: bool
) -> None:
    schematic = _schematic(session, open_pins=open_pins)
    _helper(session, "rules_check", schematic, "board")
    _helper(session, "exports", schematic, "board")
    for suffix in TEXT_EXPORTS:
        body = (session.module / "exports" / f"board{suffix}").read_bytes()
        path = f"modules/board/exports/board{suffix}"
        assert exports.is_export(path), suffix
        assert exports.summary(path, body) is not None, (suffix, body[:300])
        assert len(body) <= exports.EXPORT_CAPS[suffix], (suffix, len(body))


def test_a_second_run_gives_the_same_bytes_for_the_three_text_exports(session: Session) -> None:
    schematic = _schematic(session, open_pins=True)
    kept: dict[str, bytes] = {}
    for _ in range(2):
        _helper(session, "rules_check", schematic, "board")
        _helper(session, "exports", schematic, "board")
        for suffix in TEXT_EXPORTS:
            body = (session.module / "exports" / f"board{suffix}").read_bytes()
            assert kept.setdefault(suffix, body) == body, suffix


@pytest.mark.parametrize("open_pins", [False, True])
def test_a_session_wired_anew_elsewhere_gives_the_same_bytes_for_the_three_text_exports(
    session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str], open_pins: bool
) -> None:
    # A measurement for holding committed exports to their schematic: the same schematic in a
    # second session, wired anew (its own temporary directory, home and KiCad configuration,
    # first used here) with its module at another path at another depth, as a commit-time
    # regeneration would be. The time of each set (the rules check, then the exports) is
    # printed with the result.
    elsewhere = _session_at(
        Path(os.path.realpath(tmp_path)) / "elsewhere", Path("x") / "checkout" / "modules" / "board"
    )
    text = hand_written(session.roots[1], open_pins=open_pins)
    made: list[dict[str, bytes]] = []
    times: list[float] = []
    for each in (session, elsewhere):
        schematic = each.module / "board.kicad_sch"
        schematic.write_text(text, encoding="utf-8")
        started = time.monotonic()
        _helper(each, "rules_check", schematic, "board")
        _helper(each, "exports", schematic, "board")
        times.append(time.monotonic() - started)
        made.append(
            {s: (each.module / "exports" / f"board{s}").read_bytes() for s in TEXT_EXPORTS}
        )
    with capsys.disabled():
        sizes = {s: len(made[0][s]) for s in TEXT_EXPORTS}
        print(f"\n[measure] open_pins={open_pins} seconds per set {times} sizes {sizes}")
    for suffix in TEXT_EXPORTS:
        assert made[0][suffix] == made[1][suffix], (suffix, made[0][suffix], made[1][suffix])


SKIDL = """
import sys
import time
from skidl import KICAD10, Net, Part, generate_schematic, set_default_tool
set_default_tool(KICAD10)
resistor = "Resistor_SMD:R_0603_1608Metric"
r1 = Part("Device", "R", value="10k", footprint=resistor, tag="r1")
r2 = Part("Device", "R", value="4k7", footprint=resistor, tag="r2")
j1 = Part("Connector_Generic", "Conn_01x03", tag="j1",
          footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
vin, out, gnd = Net("VIN"), Net("OUT"), Net("GND")
vin += j1[1], r1[1]
out += r1[2], r2[1], j1[2]
gnd += r2[2], j1[3]
generate_schematic(filepath=sys.argv[1], top_name="divider", title="divider", seed=1)
"""


def _generated(session: Session, script: Path, out: Path, more: dict[str, str]) -> bytes:
    out.mkdir()
    done = subprocess.run(
        [*session.prefix, "python3", "-I", str(script), str(out)],
        cwd=session.module,
        env=session.env | more,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    schematics = sorted(out.rglob("*.kicad_sch"))
    assert len(schematics) == 1, schematics
    return schematics[0].read_bytes()


def test_a_skidl_script_generates_a_schematic_from_the_pinned_libraries_that_is_checked(
    session: Session,
) -> None:
    script = session.module / "divider.py"
    script.write_text(SKIDL, encoding="utf-8")
    # Measured on CI (Linux): two runs place the parts apart even with tags, the placement seed
    # and the interpreter's string hashing all fixed, so no repeat of a generated file is held
    # here; the committed schematic is the record. Each run's file is read by the check.
    fixed = {"PYTHONHASHSEED": "0"}
    for n in (1, 2):
        body = _generated(session, script, session.module / f"gen{n}", fixed)
        for ref in (b'"R1"', b'"R2"', b'"J1"'):
            assert ref in body, (n, ref)
        schematic = next((session.module / f"gen{n}").rglob("*.kicad_sch"))
        found = _helper(session, "rules_check", schematic, f"divider-{n}")
        counts = found["counts"]
        assert isinstance(counts, dict)
        assert isinstance(_value(counts["total"]), int)
        assert found["kind"] == "rules_check"


def test_nothing_is_written_into_either_root_or_outside_the_session_s_places(
    session: Session, tmp_path: Path
) -> None:
    before = scan(list(session.roots))
    place = Path(os.path.realpath(tmp_path))
    outside_before = {p for p in place.rglob("*")} - _inside(session, place)
    schematic = _schematic(session, open_pins=True)
    _helper(session, "rules_check", schematic, "board")
    _helper(session, "exports", schematic, "board")
    assert scan(list(session.roots)) == before
    outside_after = {p for p in place.rglob("*")} - _inside(session, place)
    assert outside_after == outside_before
    assert sorted(p.name for p in (session.module / "exports").iterdir()) == [
        "board.csv",
        "board.erc.json",
        "board.net",
    ]


def _inside(session: Session, place: Path) -> set[Path]:
    return {
        p
        for p in place.rglob("*")
        if any(
            p == top or p.is_relative_to(top)
            for top in (session.temp, session.home, session.module)
        )  # fmt: skip
    }


# ---- the commit check regenerates the committed exports inside the containment ----------------

try:
    from physgate.orchestrator import derived
except ImportError:  # each row below fails on its first assertion
    derived = None  # type: ignore[assignment]

_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
#: A project file that turns the rule the open pins break off; the helper never reads it.
SILENCING = json.dumps(
    {"erc": {"rule_severities": {"pin_not_connected": "ignore"}}, "meta": {"version": 1}}
)


def _commit(repo: Path, message: str) -> str:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=repo, env=_GIT_ENV, capture_output=True, text=True, check=True,
        )  # fmt: skip
        return done.stdout.strip()

    if not (repo / ".git").exists():
        git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "--allow-empty", "-m", message)
    return git("rev-parse", "HEAD")


def _made_in_session(session: Session, *, open_pins: bool) -> Path:
    schematic = _schematic(session, open_pins=open_pins)
    _helper(session, "rules_check", schematic, "board")
    _helper(session, "exports", schematic, "board")
    return schematic


def _held(session: Session, base: str, commit: str) -> object:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    repo = session.module.parents[1]
    recorded = _recorded(*session.roots)
    return derived.held_exports(
        repo, base, commit, "modules/board",
        environment=lambda: recorded, runner=derived.contained_runner(),
    )  # fmt: skip


def test_an_honest_set_is_regenerated_inside_the_containment_and_passes(
    session: Session,
) -> None:
    repo = session.module.parents[1]
    base = _commit(repo, "start")
    _made_in_session(session, open_pins=True)
    assert _held(session, base, _commit(repo, "honest")) is None


def test_a_project_file_that_silences_a_rule_changes_nothing_in_the_report(
    session: Session,
) -> None:
    repo = session.module.parents[1]
    base = _commit(repo, "start")
    _made_in_session(session, open_pins=True)
    plain = (session.module / "exports" / "board.erc.json").read_bytes()
    (session.module / "board.kicad_pro").write_text(SILENCING, encoding="utf-8")
    _made_in_session(session, open_pins=True)
    report = (session.module / "exports" / "board.erc.json").read_bytes()
    assert report == plain
    assert json.dumps(json.loads(report)).count("pin_not_connected") == 2
    assert _held(session, base, _commit(repo, "with a silencing project file")) is None


def test_a_hand_edited_clean_report_over_a_failing_schematic_is_refused_at_commit(
    session: Session,
) -> None:
    repo = session.module.parents[1]
    base = _commit(repo, "start")
    _made_in_session(session, open_pins=False)
    clean = (session.module / "exports" / "board.erc.json").read_bytes()
    _made_in_session(session, open_pins=True)
    (session.module / "exports" / "board.erc.json").write_bytes(clean)
    refusal = _held(session, base, _commit(repo, "forged"))
    assert refusal is not None
    assert refusal.subject == "modules/board/exports/board.erc.json"  # type: ignore[attr-defined]
    assert "regenerate" in refusal.reason  # type: ignore[attr-defined]


def test_a_changed_schematic_with_stale_exports_is_refused_at_commit(session: Session) -> None:
    repo = session.module.parents[1]
    _made_in_session(session, open_pins=False)
    base = _commit(repo, "sound")
    _schematic(session, open_pins=True)
    refusal = _held(session, base, _commit(repo, "stale"))
    assert refusal is not None
    assert refusal.subject == "modules/board/exports/board.erc.json"  # type: ignore[attr-defined]


def test_a_schematic_that_draws_on_a_sub_sheet_is_refused_in_words_at_commit(
    session: Session,
) -> None:
    repo = session.module.parents[1]
    _made_in_session(session, open_pins=False)
    base = _commit(repo, "sound")
    schematic = session.module / "board.kicad_sch"
    text = schematic.read_text(encoding="utf-8")
    sheet = '  (sheet (at 10 10) (size 20 10) (property "Sheetfile" "power.kicad_sch"))\n'
    schematic.write_text(text.replace("  (sheet_instances", sheet + "  (sheet_instances"), "utf-8")
    refusal = _held(session, base, _commit(repo, "sub-sheet"))
    assert refusal is not None
    assert "sub-sheet" in refusal.reason  # type: ignore[attr-defined]
