"""The two scripts a drawing asks of the CAD kernel, run on a provisioned tool environment.

The kernel is not in the harness's environment: it lives in the provisioned tool environment
(``toolenv/provision.py``), with the geometry helper beside it. As provisioning's own self-check
and the chassis fixture do, a script is handed to the environment's interpreter in isolated mode
(``<tree>/venv/bin/python -I -c SCRIPT <tree>/helpers ...``), with a home, caches and a temporary
directory of its own that are removed afterwards, no display and a plain search path. It prints
one line of JSON, read here. Nothing of the harness is imported by a script, and nothing of the
kernel by this module.

- :data:`EXAMPLE_PART`: the chassis fixture's plate (110 by 60 by 3 mm with four 3.2 mm holes),
  with its length a parameter, built, exported and recorded with the environment's own geometry
  helper exactly as a part script records a part.
- :data:`PROJECTION`: a part's STEP file read back, hashed with the helper's ``geometry_hash``,
  and projected onto each view by the kernel's own hidden-line projection (``project_to_viewport``,
  orthographic). Each projected edge leaves as a polyline in the view's plane: a straight edge by
  its two ends, any other at evenly spaced parameters; every coordinate in millimetres rounded to
  :data:`DECIMALS` decimals, a negative zero written as zero; each polyline started from its
  smaller end, and the polylines sorted. So the projection's text does not depend on the order
  the kernel happens to list its edges in.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from physgate.build.drawings.record import VIEW_DIRECTIONS

#: The decimals of a millimetre a projected point keeps.
DECIMALS = 3
#: The segments a curved edge is drawn with.
SEGMENTS = 48
#: How long a script may take, in seconds.
TIMEOUT_S = 600.0
#: The variable that names a provisioned tool environment, when no option does.
ENVIRONMENT_VARIABLE = "PHYSGATE_TOOL_ENVIRONMENT"

EXAMPLE_PART = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
module, length = sys.argv[2], float(sys.argv[3])
import geometry, result_file
from build123d import Box, BuildPart, Cylinder, GridLocations, Mode


def plate(length, width=60.0, thick=3.0, hole=3.2):
    with BuildPart() as built:
        Box(length, width, thick)
        with GridLocations(length - 12, width - 12, 2, 2):
            Cylinder(hole / 2, thick, mode=Mode.SUBTRACT)
    return built.part


shape = plate(length)
exports = geometry.export(shape, module, "plate")
result = geometry.geometry_result(
    "plate", shape, density={"value": 1240, "unit": "kg/m**3"},
    density_source="a figure for the fixture only", exports=exports)
result_file.write(os.path.join(module, "plate.result.json"), result)
print("EXAMPLE-PART " + json.dumps({"geometry_hash": result["geometry_hash"]}))
"""

PROJECTION = """
import json, sys
sys.path.insert(0, sys.argv[1])
step, directions = sys.argv[2], json.loads(sys.argv[3])
decimals, segments = int(sys.argv[4]), int(sys.argv[5])
import geometry
from build123d import import_step


def rounded(number):
    kept = round(float(number), decimals)
    return 0.0 if kept == 0 else kept


def lines(edges):
    found = []
    for edge in edges:
        steps = 1 if edge.geom_type.name == "LINE" else segments
        points = []
        for i in range(steps + 1):
            at = edge.position_at(i / steps)
            point = [rounded(at.X), rounded(at.Y)]
            if not points or points[-1] != point:
                points.append(point)
        if len(points) >= 2:
            found.append(min(points, points[::-1]))
    return sorted(found)


shape = import_step(step)
measured = geometry.measure(shape)
box = [float(number) for number in measured["box"]]
centre = tuple((box[i] + box[i + 3]) / 2 for i in range(3))
views = {}
for name, (toward, up) in directions.items():
    origin = tuple(centre[i] + 1000.0 * toward[i] for i in range(3))
    visible, hidden = shape.project_to_viewport(origin, tuple(up), look_at=centre)
    views[name] = {"visible": lines(visible), "hidden": lines(hidden)}
told = {
    "kind": "projection",
    "geometry_hash": geometry.hash_of(measured),
    "box_mm": [rounded(number) for number in box],
    "views": views,
    "libraries": geometry.library_versions(),
}
print("PROJECTION " + json.dumps(told, sort_keys=True))
"""


class KernelError(RuntimeError):
    """The tool environment cannot be used, or a script it ran did not answer."""


def interpreter_and_helpers(tree: Path) -> tuple[Path, Path]:
    """The tool environment's interpreter and its helpers' directory.

    Raises:
        KernelError: ``tree`` is not a provisioned tool environment.
    """
    interpreter, helpers = tree / "venv" / "bin" / "python", tree / "helpers"
    if not (tree / "provisioned.json").is_file():
        msg = f"{tree} is not a provisioned tool environment: it holds no provisioned.json"
        raise KernelError(msg)
    if not interpreter.exists() or not (helpers / "geometry.py").is_file():
        msg = f"{tree} holds no interpreter at venv/bin/python or no geometry helper"
        raise KernelError(msg)
    return interpreter, helpers


def _quiet(work: Path) -> dict[str, str]:
    """What a script is given: a home, caches and a temporary directory of its own, no display."""
    home, temp = work / "home", work / "tmp"
    home.mkdir()
    temp.mkdir()
    return {
        "PATH": f"/usr/bin{os.pathsep}/bin",
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
        "MPLBACKEND": "Agg",
        "LANG": "C.UTF-8",
        "TMPDIR": str(temp),
    }


def _last_line(said: str) -> str:
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    return lines[-1][:400] if lines else "(nothing on its error stream)"


def run_script(tree: Path, script: str, marker: str, *arguments: str) -> Any:  # noqa: ANN401 - JSON
    """Run ``script`` on the environment's interpreter; the JSON it printed after ``marker``.

    Raises:
        KernelError: the environment cannot be used, the script failed or ran out of time, or
            it printed no line starting with ``marker``.
    """
    interpreter, helpers = interpreter_and_helpers(tree)
    with tempfile.TemporaryDirectory(prefix="physgate-drawing-") as scratch:
        work = Path(scratch)
        try:
            done = subprocess.run(  # noqa: S603 - the environment's own interpreter, no shell
                [str(interpreter), "-I", "-c", script, str(helpers), *arguments],
                cwd=work,
                env=_quiet(work),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"the kernel's script ran out of its {TIMEOUT_S:g} s"
            raise KernelError(msg) from exc
    if done.returncode != 0:
        msg = f"the kernel's script failed ({done.returncode}): {_last_line(done.stderr)}"
        raise KernelError(msg)
    prefix = marker + " "
    told = next((ln for ln in done.stdout.splitlines() if ln.startswith(prefix)), None)
    if told is None:
        msg = f"the kernel's script printed no {marker} line"
        raise KernelError(msg)
    return json.loads(told[len(prefix) :])


def example_part(tree: Path, module: Path, length_mm: float) -> str:
    """Write the chassis fixture's plate into ``module``; return its geometry hash.

    Raises:
        KernelError: as :func:`run_script`.
    """
    module.mkdir(parents=True, exist_ok=True)
    told = run_script(tree, EXAMPLE_PART, "EXAMPLE-PART", str(module.resolve()), repr(length_mm))
    return str(told["geometry_hash"])


def project(tree: Path, step: Path) -> Any:  # noqa: ANN401 - the projection as JSON, read later
    """The kernel's projection of the shape in ``step`` onto the four views, as it printed it.

    Raises:
        KernelError: as :func:`run_script`.
    """
    directions = json.dumps(VIEW_DIRECTIONS, sort_keys=False)
    return run_script(
        tree,
        PROJECTION,
        "PROJECTION",
        str(step.resolve()),
        directions,
        str(DECIMALS),
        str(SEGMENTS),
    )
