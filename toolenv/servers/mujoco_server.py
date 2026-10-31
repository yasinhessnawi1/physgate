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
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_stdio import RefusedError, Server, quantity  # noqa: E402 - the line above finds it

NOTE = "A working aid: nothing here is evidence. Simulate in a module script and record it."
#: The most steps one call may take.
MAX_STEPS = 100_000
#: The longest model text taken inline.
MAX_XML = 1 << 19

#: How each kind of joint's position and velocity coordinates split, with their units.
_JOINTS = {
    0: ("free", [("position", 3, "m"), ("orientation", 4, "dimensionless")],
        [("linear_velocity", 3, "m/s"), ("angular_velocity", 3, "rad/s")]),
    1: ("ball", [("orientation", 4, "dimensionless")], [("angular_velocity", 3, "rad/s")]),
    2: ("slide", [("position", 1, "m")], [("velocity", 1, "m/s")]),
    3: ("hinge", [("angle", 1, "rad")], [("angular_velocity", 1, "rad/s")]),
}  # fmt: skip


class Simulation:
    """The one model this server holds, and its data."""

    def __init__(self, root: str) -> None:
        """Models are read from under ``root`` only."""
        self.root = os.path.realpath(root)
        self.model: Any = None
        self.data: Any = None

    def _inside(self, given: str) -> str:
        path = given if os.path.isabs(given) else os.path.join(self.root, given)
        real = os.path.realpath(path)
        if not (real == self.root or real.startswith(self.root + os.sep)):
            raise RefusedError("the model path leads outside the worktree")
        return real

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
        path = self._inside(arguments["path"]) if "path" in arguments else None
        import mujoco

        if path is not None:
            model = mujoco.MjModel.from_xml_path(path)
        else:
            model = mujoco.MjModel.from_xml_string(arguments["xml"])
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
