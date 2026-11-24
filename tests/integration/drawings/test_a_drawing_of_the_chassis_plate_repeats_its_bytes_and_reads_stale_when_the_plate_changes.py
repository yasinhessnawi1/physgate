"""A drawing of the chassis plate, made by the CAD kernel, repeats its bytes and goes stale.

The command is run as a person runs it, on a provisioned tool environment: the chassis
fixture's plate is written into a module, its drawing is made twice, checked, and the plate is
then made 10 mm longer, after which the same drawing reads stale; made again, it passes. What
was written is read: the SVG, the record and the projection, byte for byte.

Two more cases need the kernel. The plate made at lengths just around a half tenth of a
millimetre is drawn with its length written by the one rounding the checker judges it by, and
its fresh drawing passes. And a part that is not symmetric (a block with a step cut from the top
of its +x end and a hole near its -x, +y corner) is drawn with each feature where first-angle
placement and the stated directions put it, so a view seen from the other side, or mirrored,
fails here even though the plate, symmetric in x and y, cannot show it.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network once (``PHYSGATE_TOOLENV_CACHE`` keeps
the downloads).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from design_fixtures import GEOMETRY_HASH

from physgate.build.drawings.check import EXIT_PASSES, EXIT_STALE
from physgate.build.drawings.kernel import run_script
from physgate.cli import main
from physgate.toolenv.manifest import scan

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
FILES = ("plate.svg", "plate.drawing.json", "plate.projection.json")


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "toolenv_provision_for_drawings", REPO / "toolenv" / "provision.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _writable(root: Path) -> None:
    for directory, dirs, _ in os.walk(root):
        for name in [".", *dirs]:
            path = Path(directory, name)
            if not path.is_symlink():
                path.chmod(0o755)


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if NAMED:
        yield Path(NAMED)
        return
    built = tmp_path_factory.mktemp("built") / "env"
    kept = os.environ.get("PHYSGATE_TOOLENV_CACHE")
    cache = Path(kept) if kept else tmp_path_factory.mktemp("toolenv-cache")
    _provision().provision(built, cache)
    yield built
    _writable(built)


def _run(*argv: str) -> int:
    return main(list(argv))


def _bytes(folder: Path) -> dict[str, bytes]:
    return {name: (folder / name).read_bytes() for name in FILES}


def _module_files(module: Path) -> dict[str, str]:
    return {
        str(p.relative_to(module)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(module.rglob("*"))
        if p.is_file()
    }


class Made:
    """The plate written once into a module, and its drawing made twice from it."""

    def __init__(self, env: Path, root: Path) -> None:
        self.env = env
        self.module = root / "modules" / "chassis"
        self.first, self.second = root / "drawings-1", root / "drawings-2"
        tree = ("--tool-environment", str(env))
        assert _run("drawing", "example-part", str(self.module), *tree) == EXIT_PASSES
        self.part = self.module / "plate.result.json"
        self.before_env = scan([env])
        self.module_before = _module_files(self.module)
        for out in (self.first, self.second):
            status = _run("drawing", "make", str(self.part), "--out", str(out), *tree)
            assert status == EXIT_PASSES
        self.after_env = scan([env])
        self.record = json.loads((self.first / "plate.drawing.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def made(env: Path, tmp_path_factory: pytest.TempPathFactory) -> Made:
    return Made(env, tmp_path_factory.mktemp("plate"))


def test_the_example_part_is_the_chassis_fixture_s_plate(made: Made) -> None:
    part = json.loads(made.part.read_text(encoding="utf-8"))
    assert part["geometry_hash"] == GEOMETRY_HASH["plate"]
    assert sorted(_module_files(made.module)) == [
        "exports/plate.step",
        "exports/plate.stl",
        "plate.result.json",
    ]


def test_a_drawing_made_twice_from_the_same_part_is_the_same_bytes(made: Made) -> None:
    assert _bytes(made.first) == _bytes(made.second)
    assert sorted(p.name for p in made.first.iterdir()) == sorted(FILES)


def test_the_drawing_s_record_names_the_part_s_hash_the_views_and_its_files(made: Made) -> None:
    record = made.record
    assert record["geometry_hash"] == GEOMETRY_HASH["plate"]
    assert record["drawn_from"]["file"] == "exports/plate.step"
    assert [view["name"] for view in record["views"]] == ["front", "top", "side", "isometric"]
    for view in record["views"]:
        assert view["visible_paths"]["value"] >= 4, view["name"]
    # The plate's holes are behind its faces in the front and side views.
    assert {v["name"]: v["hidden_paths"]["value"] > 0 for v in record["views"]}["front"]
    assert record["overall"] == {
        "length_x": {"value": 110.0, "unit": "mm"},
        "width_y": {"value": 60.0, "unit": "mm"},
        "height_z": {"value": 3.0, "unit": "mm"},
    }
    assert record["scale"] == {"value": 1.0, "unit": "1", "shown_as": "1:1"}
    assert record["libraries"] == {"build123d": "0.13.0", "cadquery-ocp-novtk": "8.0.1.1.0"}
    for name, kind in (("svg", "plate.svg"), ("projection", "plate.projection.json")):
        data = (made.first / kind).read_bytes()
        assert record["files"][name] == {
            "file": kind,
            "size": {"value": len(data), "unit": "byte"},
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    text = (made.first / "plate.drawing.json").read_text(encoding="utf-8")
    assert str(made.module) not in text and str(made.env) not in text


def test_a_fresh_drawing_passes_every_check(made: Made, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    record = made.first / "plate.drawing.json"
    assert _run("drawing", "check", str(record), str(made.part), "--json") == EXIT_PASSES
    told = json.loads(capsys.readouterr().out)
    assert [(c["check"], c["verdict"]) for c in told["checks"]] == [
        ("part", "passes"),
        ("file", "passes"),
        ("views", "passes"),
        ("title block", "passes"),
        ("dimensions", "passes"),
    ]


def test_making_a_drawing_changes_neither_the_tool_environment_nor_the_module(made: Made) -> None:
    assert made.after_env == made.before_env
    assert _module_files(made.module) == made.module_before


def test_a_longer_plate_makes_the_drawing_stale_and_a_drawing_made_again_passes(
    env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, out = tmp_path / "modules" / "chassis", tmp_path / "drawings"
    tree = ("--tool-environment", str(env))
    assert _run("drawing", "example-part", str(module), *tree) == EXIT_PASSES
    part = module / "plate.result.json"
    assert _run("drawing", "make", str(part), "--out", str(out), *tree) == EXIT_PASSES
    record = out / "plate.drawing.json"
    made_from = json.loads(record.read_text(encoding="utf-8"))["geometry_hash"]

    assert _run("drawing", "example-part", str(module), "--length", "120", *tree) == EXIT_PASSES
    longer = json.loads(part.read_text(encoding="utf-8"))["geometry_hash"]
    assert longer != made_from
    capsys.readouterr()
    assert _run("drawing", "check", str(record), str(part)) == EXIT_STALE
    said = capsys.readouterr().out
    line = next(ln for ln in said.splitlines() if ln.startswith("part "))
    assert "STALE" in line and made_from in line and longer in line
    # Every other check still passes but the dimensions: the plate is 10 mm longer.
    assert _run("drawing", "check", str(record), str(part), "--json") == EXIT_STALE
    told = json.loads(capsys.readouterr().out)
    assert {c["check"]: c["verdict"] for c in told["checks"]} == {
        "part": "stale",
        "file": "passes",
        "views": "passes",
        "title block": "passes",
        "dimensions": "fails",
    }

    assert _run("drawing", "make", str(part), "--out", str(out), *tree) == EXIT_PASSES
    again = json.loads(record.read_text(encoding="utf-8"))
    assert again["geometry_hash"] == longer
    assert again["overall"]["length_x"] == {"value": 120.0, "unit": "mm"}
    assert _run("drawing", "check", str(record), str(part)) == EXIT_PASSES


# --- one rounding, at lengths around a half tenth ---------------------------------------------


@pytest.mark.parametrize(
    ("length", "written"),
    [("112.3496", "112.3"), ("112.35", "112.4"), ("112.3504", "112.4"), ("112.3506", "112.4")],
)
def test_the_plate_s_length_is_written_by_the_checker_s_rounding_and_its_drawing_passes(
    env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], length: str, written: str
) -> None:
    module, out = tmp_path / "modules" / "chassis", tmp_path / "drawings"
    tree = ("--tool-environment", str(env))
    assert _run("drawing", "example-part", str(module), "--length", length, *tree) == EXIT_PASSES
    part = module / "plate.result.json"
    assert _run("drawing", "make", str(part), "--out", str(out), *tree) == EXIT_PASSES
    svg = (out / "plate.svg").read_text(encoding="utf-8")
    shown = re.search(r'data-quantity="length_x"[^>]*>([^<]*)</text>', svg)
    assert shown is not None and shown.group(1) == written
    record = json.loads((out / "plate.drawing.json").read_text(encoding="utf-8"))
    assert record["overall"]["length_x"] == {"value": float(written), "unit": "mm"}
    capsys.readouterr()
    assert _run("drawing", "check", str(out / "plate.drawing.json"), str(part)) == EXIT_PASSES


# --- an asymmetric part, drawn unmirrored -----------------------------------------------------

#: A 100 by 60 by 20 mm block, the top 10 mm of its +x end (x from 30 to 50) cut away, and a
#: 10 mm hole through it at x -30, y +20; recorded with the tool environment's geometry helper.
BRACKET = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
module = sys.argv[2]
import geometry, result_file
from build123d import Box, BuildPart, Cylinder, Locations, Mode
with BuildPart() as built:
    Box(100, 60, 20)
    with Locations((40, 0, 5)):
        Box(20, 60, 10, mode=Mode.SUBTRACT)
    with Locations((-30, 20, 0)):
        Cylinder(5, 20, mode=Mode.SUBTRACT)
exports = geometry.export(built.part, module, "bracket")
result = geometry.geometry_result(
    "bracket", built.part, density={"value": 1240, "unit": "kg/m**3"},
    density_source="a figure for the row only", exports=exports)
result_file.write(os.path.join(module, "bracket.result.json"), result)
print("BRACKET " + json.dumps({"geometry_hash": result["geometry_hash"]}))
"""

_STEP = re.compile(r"[ML](-?[0-9.]+) (-?[0-9.]+)")


def _view(svg: str, name: str, scale: float) -> list[tuple[str, list[tuple[float, float]]]]:
    """A view's lines, each point in mm from the view's top left, as the sheet shows it."""
    group = re.search(rf'<g id="view-{name}"[^>]*>(.*?)</g>', svg, re.S)
    assert group is not None, name
    lines = [
        (kind, [(float(x), float(y)) for x, y in _STEP.findall(d)])
        for kind, d in re.findall(r'<path class="(visible|hidden)" d="([^"]+)"', group.group(1))
    ]
    left = min(x for _, points in lines for x, _ in points)
    top = min(y for _, points in lines for _, y in points)
    return [
        (kind, [((x - left) / scale, (y - top) / scale) for x, y in points])
        for kind, points in lines
    ]


def _near(points: list[tuple[float, float]], at: tuple[float, float]) -> bool:
    return any(abs(x - at[0]) < 0.5 and abs(y - at[1]) < 0.5 for x, y in points)  # noqa: PLR2004


def _xs(lines: list[tuple[str, list[tuple[float, float]]]], kind: str) -> list[float]:
    return [x for k, points in lines if k == kind for x, _ in points]


def test_an_asymmetric_part_is_drawn_with_each_feature_where_first_angle_puts_it(
    env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module, out = tmp_path / "modules" / "bracket", tmp_path / "drawings"
    module.mkdir(parents=True)
    told = run_script(env, BRACKET, "BRACKET", str(module))
    part = module / "bracket.result.json"
    assert json.loads(part.read_text(encoding="utf-8"))["geometry_hash"] == told["geometry_hash"]
    tree = ("--tool-environment", str(env))
    assert _run("drawing", "make", str(part), "--out", str(out), *tree) == EXIT_PASSES
    capsys.readouterr()
    assert _run("drawing", "check", str(out / "bracket.drawing.json"), str(part)) == EXIT_PASSES
    svg = (out / "bracket.svg").read_text(encoding="utf-8")
    scale = json.loads((out / "bracket.drawing.json").read_text(encoding="utf-8"))["scale"]["value"]

    # The front, seen from -y with +z up: +x to the right, so the step is at the top right.
    front = _view(svg, "front", scale)
    visible = [p for kind, points in front if kind == "visible" for p in points]
    assert _near(visible, (80.0, 0.0)) and _near(visible, (100.0, 10.0))
    assert not _near(visible, (100.0, 0.0)) and not _near(visible, (0.0, 10.0))

    # The view from above, from +z with +y up: the hole (x -30, y +20) is 20 mm from the left
    # and 10 mm from the top.
    top = _view(svg, "top", scale)
    # The hole's edges are the view's only curves, however many pieces the kernel cuts them in.
    curved = [p for _, points in top if len(points) > 3 for p in points]  # noqa: PLR2004
    assert curved, "the view from above draws no hole"
    xs, ys = [x for x, _ in curved], [y for _, y in curved]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    assert _near([centre], (20.0, 10.0)), centre
    assert abs(max(xs) - min(xs) - 10.0) < 0.5, (min(xs), max(xs))  # noqa: PLR2004

    # The view from the left, from -x with +z up: -y is to the right, so the hole (y +20) is
    # behind the face 5 to 15 mm from the left, and the step is behind it too, 10 mm down.
    side = _view(svg, "side", scale)
    hidden = _xs(side, "hidden")
    assert any(abs(x - 5.0) < 0.5 for x in hidden) and any(abs(x - 15.0) < 0.5 for x in hidden)  # noqa: PLR2004
    assert not any(abs(x - 45.0) < 0.5 or abs(x - 55.0) < 0.5 for x in hidden)  # noqa: PLR2004
    hidden_points = [p for kind, points in side if kind == "hidden" for p in points]
    assert _near(hidden_points, (0.0, 10.0)) and _near(hidden_points, (60.0, 10.0))
