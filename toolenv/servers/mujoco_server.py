"""A tool server for MuJoCo: load a model, step it, read its state, reset it. No viewer.

A model comes from a file under the root the server was started with (the session's worktree)
or from an XML string. A path that leads outside the root, by ``..`` or through a link, is
refused before anything is read; what the model file itself names in turn (an included file, a
mesh) is held by the sandbox the server runs in, not by this check. The server never opens a
window or renders. Every quantity it answers is a value with its unit, joint by joint. It is a
working aid: nothing it answers stands behind a reported number.

Run on the tool environment's interpreter: ``python -I mujoco_server.py --root <worktree>``.
It imports nothing of the harness, and MuJoCo only inside a tool.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_stdio import RefusedError, Server, quantity  # noqa: E402 - the line above finds it

NOTE = "A working aid: nothing here is evidence. Simulate in a module script and record it."
#: The most steps one call may take.
MAX_STEPS = 100_000
#: The longest model text taken inline or read from a file.
MAX_XML = 1 << 19
#: The most bytes of asset files one model may read.
MAX_ASSETS = 64 << 20
#: The elements whose ``file`` the server reads for MuJoCo, from under the root only.
_ASSET_ELEMENTS = {"mesh", "hfield", "texture", "skin"}
#: Elements that name further models, files or native code the server does not vet.
_REFUSED_ELEMENTS = {"include", "model", "plugin", "extension", "instance"}
#: Attributes that move where MuJoCo looks for every file the model names.
_DIRECTORIES = {"meshdir", "texturedir", "assetdir"}
#: A name an asset may be given: a plain relative path, nothing MuJoCo could read otherwise.
_PLAIN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*")
#: How a library's error is shown: one line, its paths replaced, bounded.
MAX_ERROR = 300

#: How each kind of joint's position and velocity coordinates split, with their units.
_JOINTS = {
    0: ("free", [("position", 3, "m"), ("orientation", 4, "dimensionless")],
        [("linear_velocity", 3, "m/s"), ("angular_velocity", 3, "rad/s")]),
    1: ("ball", [("orientation", 4, "dimensionless")], [("angular_velocity", 3, "rad/s")]),
    2: ("slide", [("position", 1, "m")], [("velocity", 1, "m/s")]),
    3: ("hinge", [("angle", 1, "rad")], [("angular_velocity", 1, "rad/s")]),
}  # fmt: skip


def _opened_path(fd: int) -> str:
    """The path an open file has now, as the system reports it."""
    if sys.platform == "darwin":
        import fcntl

        found = fcntl.fcntl(fd, getattr(fcntl, "F_GETPATH", 50), b"\0" * 1024)
        return os.fsdecode(found.split(b"\0", 1)[0])
    return os.readlink(f"/proc/self/fd/{fd}")


class Simulation:
    """The one model this server holds, and its data."""

    def __init__(self, root: str) -> None:
        """Models are read from under ``root`` only."""
        self.root = os.path.realpath(root)
        self.model: Any = None
        self.data: Any = None

    def _inside(self, given: str, base: str | None = None) -> str:
        start = base or self.root
        path = given if os.path.isabs(given) else os.path.join(start, given)
        real = os.path.realpath(path)
        if not self._under_root(real):
            raise RefusedError("the model path leads outside the worktree")
        return real

    def _under_root(self, real: str) -> bool:
        return real == self.root or real.startswith(self.root + os.sep)

    def _read(self, given: str, base: str | None, limit: int) -> bytes:
        """A file under the root, opened once and judged by what was opened, not by its name.

        The final name may not be a link, and the path the open file actually has must lie
        under the root, so a link swapped in after the name was judged is refused too.
        """
        real = self._inside(given, base)
        try:
            fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            raise RefusedError(f"the file {os.path.basename(real)!r} cannot be opened") from exc
        try:
            found = os.fstat(fd)
            if not stat.S_ISREG(found.st_mode):
                raise RefusedError("a model or asset must be a regular file")
            if not self._under_root(os.path.realpath(_opened_path(fd))):
                raise RefusedError("the model path leads outside the worktree")
            if found.st_size > limit:
                raise RefusedError(f"a model or asset holds at most {limit} bytes")
            with os.fdopen(os.dup(fd), "rb") as handle:
                return handle.read(limit + 1)[:limit]
        finally:
            os.close(fd)

    def _vetted(self, text: str, base: str) -> tuple[str, dict[str, bytes]]:
        """The model rewritten to name only files the server read for it, and those files.

        Each asset's name must be a plain relative path, read from under the root; it is then
        renamed in the model to a flat name of the server's, the key it is handed to MuJoCo
        under, so MuJoCo's lookup and the server's read cannot name different files. The
        directory attributes that would prefix those names are refused, not resolved.
        """
        upper = text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise RefusedError("a model may not declare a document type or entities")
        try:
            tree = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            line = exc.position[0] if exc.position else 0
            raise RefusedError(f"the model is not well-formed XML (line {line})") from None
        assets: dict[str, bytes] = {}
        renamed: dict[str, str] = {}
        for element in tree.iter():
            tag = element.tag if isinstance(element.tag, str) else ""
            if tag in _REFUSED_ELEMENTS:
                raise RefusedError(
                    f"a model may not use <{tag}>: it names what the server does not vet"
                )
            for name, value in list(element.attrib.items()):
                if name == "file" and tag in _ASSET_ELEMENTS:
                    if not _PLAIN.fullmatch(value) or any(
                        p in (".", "..") for p in value.split("/")
                    ):
                        raise RefusedError(
                            f"a model may not name an asset {value[:60]!r}: plain relative paths"
                        )
                    if value not in renamed:
                        renamed[value] = f"asset{len(renamed)}{os.path.splitext(value)[1].lower()}"
                        assets[renamed[value]] = self._read(value, base, MAX_ASSETS)
                        if sum(map(len, assets.values())) > MAX_ASSETS:
                            raise RefusedError(f"a model's assets hold at most {MAX_ASSETS} bytes")
                    element.set("file", renamed[value])
                elif name.startswith("file") or name in _DIRECTORIES:
                    raise RefusedError(f"a model may not name files through <{tag} {name}>")
        return ElementTree.tostring(tree, encoding="unicode"), assets

    def _redacted(self, error: Exception) -> str:
        line = (str(error).strip().splitlines() or [type(error).__name__])[0]

        def shown(match: re.Match[str]) -> str:
            real = os.path.realpath(match.group(0))
            return "<worktree>" + real[len(self.root) :] if self._under_root(real) else "<path>"

        line = re.sub(r"/[^\s'\"]+", shown, line)
        return "".join(c if c.isprintable() else " " for c in line)[:MAX_ERROR]

    def _need(self) -> None:
        if self.model is None:
            raise RefusedError("no model is loaded; call load_model first")

    def _info(self) -> dict[str, Any]:
        import mujoco

        m = self.model
        return {
            "joints": m.njnt,
            "bodies": m.nbody,
            "actuators": m.nu,
            "position_coordinates": m.nq,
            "velocity_coordinates": m.nv,
            "timestep": quantity(float(m.opt.timestep), "s"),
            "integrator": mujoco.mjtIntegrator(m.opt.integrator).name,
            "gravity": quantity([float(g) for g in m.opt.gravity], "m/s^2"),
            "note": NOTE,
        }

    def _state(self) -> dict[str, Any]:
        import mujoco

        m, d = self.model, self.data
        joints = []
        for j in range(m.njnt):
            kind, positions, velocities = _JOINTS[int(m.jnt_type[j])]
            qp, qv = int(m.jnt_qposadr[j]), int(m.jnt_dofadr[j])
            entry: dict[str, Any] = {
                "name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint {j}",
                "type": kind,
            }
            for parts, start, values in ((positions, qp, d.qpos), (velocities, qv, d.qvel)):
                for label, size, unit in parts:
                    entry[label] = quantity([float(v) for v in values[start : start + size]], unit)
                    start += size
            joints.append(entry)
        return {
            "time": quantity(float(d.time), "s"),
            "joints": joints,
            "controls": [float(u) for u in d.ctrl],
            "note": NOTE,
        }

    def load_model(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Load a model from a worktree path or from XML text; it replaces any loaded one."""
        given = [name for name in ("path", "xml") if name in arguments]
        if len(given) != 1:
            raise RefusedError("a model is given as exactly one of path or xml")
        if "path" in arguments:
            real = self._inside(arguments["path"])
            raw = self._read(arguments["path"], None, MAX_XML)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise RefusedError("the model file is not UTF-8 text") from None
            base = os.path.dirname(real)
        else:
            text, base = arguments["xml"], self.root
        # MuJoCo is handed the text and the vetted files only, so it opens nothing itself.
        text, assets = self._vetted(text, base)
        import mujoco

        # From an empty directory: a name MuJoCo looked up outside the assets handed to it
        # would find no file there either.
        here = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="mujoco-load-") as empty:
            os.chdir(empty)
            try:
                model = mujoco.MjModel.from_xml_string(text, assets)
            except Exception as exc:  # noqa: BLE001 - the library's refusal, shown bounded
                raise RefusedError(f"MuJoCo refused the model: {self._redacted(exc)}") from None
            finally:
                os.chdir(here)
        self.model, self.data = model, mujoco.MjData(model)
        return self._info()

    def step(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Advance the loaded model, with the controls given held for every step."""
        self._need()
        import mujoco

        controls = arguments.get("controls")
        if controls is not None:
            if len(controls) != self.model.nu:
                raise RefusedError(f"the model has {self.model.nu} actuators")
            self.data.ctrl[:] = controls
        for _ in range(arguments["steps"]):
            mujoco.mj_step(self.model, self.data)
        return self._state()

    def state(self, arguments: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002 - takes none
        """The loaded model's time and joint states."""
        self._need()
        return self._state()

    def reset(self, arguments: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002 - takes none
        """Reset the loaded model's data to its initial state."""
        self._need()
        import mujoco

        mujoco.mj_resetData(self.model, self.data)
        return self._state()

    def model_info(self, arguments: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002 - takes none
        """What the loaded model holds: counts, timestep, integrator, gravity."""
        self._need()
        return self._info()


def tools(simulation: Simulation) -> dict[str, Any]:
    """The server's tools, bound to one simulation."""
    none = {"type": "object", "additionalProperties": False, "properties": {}}
    model = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "maxLength": 4096,
                "description": "An MJCF file in the worktree, relative to it or absolute.",
            },
            "xml": {"type": "string", "maxLength": MAX_XML, "x-lines": True,
                    "description": "MJCF text."},
        },
    }  # fmt: skip
    step = {
        "type": "object",
        "additionalProperties": False,
        "required": ["steps"],
        "properties": {
            "steps": {"type": "integer", "minimum": 1, "maximum": MAX_STEPS,
                      "description": "How many timesteps to advance."},
            "controls": {"type": "array", "items": {"type": "number"}, "maxItems": 64,
                         "description": "One control per actuator, in the actuator's unit."},
        },
    }  # fmt: skip
    return {
        "load_model": ("Load an MJCF model from a worktree path or from text.", model,
                       simulation.load_model),
        "step": ("Advance the loaded model a number of timesteps; joint states by unit.", step,
                 simulation.step),
        "state": ("The loaded model's time and joint states.", none, simulation.state),
        "reset": ("Reset the loaded model to its initial state.", none, simulation.reset),
        "model_info": ("The loaded model's counts, timestep, integrator and gravity.", none,
                       simulation.model_info),
    }  # fmt: skip


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", required=True, help="the only tree a model path may lie in")
    args = parser.parse_args()
    Server("mujoco", "1", tools(Simulation(args.root))).serve()
