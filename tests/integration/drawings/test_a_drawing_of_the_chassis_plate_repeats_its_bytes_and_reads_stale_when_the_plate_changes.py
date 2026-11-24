"""A drawing of the chassis plate, made by the CAD kernel, repeats its bytes and goes stale.

The command is run as a person runs it, on a provisioned tool environment: the chassis
fixture's plate is written into a module, its drawing is made twice, checked, and the plate is
then made 10 mm longer, after which the same drawing reads stale; made again, it passes. What
was written is read: the SVG, the record and the projection, byte for byte.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``); with
none named one is built here, which needs the network once (``PHYSGATE_TOOLENV_CACHE`` keeps
the downloads).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from design_fixtures import GEOMETRY_HASH

from physgate.build.drawings.check import EXIT_PASSES, EXIT_STALE
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
