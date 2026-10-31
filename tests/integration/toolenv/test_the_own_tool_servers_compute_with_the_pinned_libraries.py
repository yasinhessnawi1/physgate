"""The own tool servers, run from a provisioned tool environment, answer with the pinned libraries.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``). The
servers are run as provisioned, from its ``servers/`` directory on its interpreter, and asked
about a fixture loop whose answers are known in closed form or measured on the pinned
python-control: ``L(s) = 4(s + 1) / (s (s + 1)^2) = 4 / (s (s + 1))``. Then the pinned binary
connects to both through a generated tool-server configuration, lists their tools and calls
one, against the scripted endpoint.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.invocation import NO_TOOL_SERVERS, role_argv

pytestmark = pytest.mark.integration

NAMED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
ENV = Path(NAMED) if NAMED else None
needs_env = pytest.mark.skipif(ENV is None, reason="no provisioned tool environment named")
BINARY = os.environ.get("PHYSGATE_CLAUDE_BIN", "")

OPENING = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "t", "version": "0"},
}
LOOP = {"transfer_function": {"numerator": [4, 4], "denominator": [1, 2, 1, 0]}}
CLOSED = {"transfer_function": {"numerator": [4, 4], "denominator": [1, 2, 5, 4]}}
PENDULUM = """<mujoco><worldbody><body pos="0 0 1"><joint name="hinge" type="hinge" axis="0 1 0"/>
<geom type="capsule" size=".05" fromto="0 0 0 0 0 -0.5" mass="1"/></body></worldbody>
<actuator><motor joint="hinge" gear="1"/></actuator></mujoco>"""


def _command(script: str, *args: str) -> list[str]:
    assert ENV is not None
    path = ENV / "servers" / script
    assert path.is_file(), f"the environment holds no {script}"
    return [str(ENV / "venv" / "bin" / "python"), "-I", str(path), *args]


class Client:
    def __init__(self, argv: list[str], home: Path) -> None:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "MPLBACKEND": "Agg"}
        self.process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
        )
        self.n = 0
        assert self.request("initialize", OPENING)["result"]["serverInfo"]["version"] == "1"

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.n += 1
        line = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(line).encode() + b"\n")
        self.process.stdin.flush()
        answer = json.loads(self.process.stdout.readline())
        assert isinstance(answer, dict)
        return answer

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        result = self.request("tools/call", {"name": tool, "arguments": arguments})["result"]
        assert result["isError"] is False, result["content"][0]["text"]
        answer = result["structuredContent"]
        assert json.loads(result["content"][0]["text"]) == answer
        assert isinstance(answer, dict)
        return answer

    def refusal(self, tool: str, **arguments: Any) -> str:
        result = self.request("tools/call", {"name": tool, "arguments": arguments})["result"]
        assert result["isError"] is True
        return str(result["content"][0]["text"])

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0


@pytest.fixture
def control(tmp_path: Path) -> Iterator[Client]:
    client = Client(_command("control_server.py"), tmp_path)
    yield client
    client.close()


@pytest.fixture
def mujoco(tmp_path: Path) -> Iterator[tuple[Client, Path]]:
    root = tmp_path / "worktree"
    root.mkdir()
    client = Client(_command("mujoco_server.py", "--root", str(root)), tmp_path)
    yield client, root
    client.close()


@needs_env
def test_margins_are_the_pinned_library_s_with_their_units(control: Client) -> None:
    answer = control.call("margins", system=LOOP)
    assert answer["gain_margin"] == {"value": None, "unit": "dimensionless", "note": "infinite",
                                     "note_scale": "a ratio, not dB"}  # fmt: skip
    assert answer["phase_margin"]["unit"] == "deg"
    assert answer["phase_margin"]["value"] == pytest.approx(28.0202, abs=1e-3)
    assert answer["gain_crossover_frequency"]["unit"] == "rad/s"
    # |L(jw)| = 4 / (w sqrt(1 + w^2)) = 1 where w^2 = (sqrt(65) - 1) / 2.
    assert answer["gain_crossover_frequency"]["value"] == pytest.approx(
        math.sqrt((math.sqrt(65) - 1) / 2), rel=1e-6
    )
    assert answer["stability_margin"]["value"] == pytest.approx(0.43799, abs=1e-4)


@needs_env
def test_the_frequency_response_is_the_loop_s_on_the_grid_given(control: Client) -> None:
    answer = control.call(
        "frequency_response", system=LOOP, omega={"value": [1.0, 10.0], "unit": "rad/s"}
    )
    assert answer["omega"] == {"value": [1.0, 10.0], "unit": "rad/s"}
    assert answer["magnitude"]["value"][0] == pytest.approx(4 / math.sqrt(2), rel=1e-9)
    assert answer["phase"]["unit"] == "rad"
    assert answer["phase"]["value"][0] == pytest.approx(-3 * math.pi / 4, rel=1e-9)
    in_hertz = control.call(
        "frequency_response", system=LOOP, omega={"value": [1 / (2 * math.pi)], "unit": "Hz"}
    )
    assert in_hertz["omega"]["value"][0] == pytest.approx(1.0)


@needs_env
def test_the_closed_loop_step_and_its_poles(control: Client) -> None:
    times = [i * 0.05 for i in range(401)]
    step = control.call(
        "step_response", system=CLOSED, times={"value": times, "unit": "s"}, output_unit="rad"
    )
    assert step["time"]["unit"] == "s" and len(step["time"]["value"]) == 401
    assert step["output"]["unit"] == "rad"
    assert step["output"]["value"][-1] == pytest.approx(1.0, abs=0.02)
    assert step["overshoot"]["unit"] == "percent" and step["overshoot"]["value"] > 30
    assert step["settling_time"]["unit"] == "s"
    roots = control.call("poles_zeros", system=CLOSED)
    assert roots["plane"] == "s-plane"
    poles = sorted((p["real"]["value"], p["imaginary"]["value"]) for p in roots["poles"])
    expected = [(-1.0, 0.0), (-0.5, -math.sqrt(15) / 2), (-0.5, math.sqrt(15) / 2)]
    for found, wanted in zip(poles, expected, strict=True):
        assert found == pytest.approx(wanted, abs=1e-9)
    assert [z["real"]["value"] for z in roots["zeros"]] == pytest.approx([-1.0])
    sampled = control.call(
        "poles_zeros",
        system={"transfer_function": {"numerator": [1, 0], "denominator": [1, -0.5]},
                "sample_time": {"value": 0.01, "unit": "s"}},
    )  # fmt: skip
    assert sampled["plane"] == "z-plane"
    assert sampled["poles"][0]["real"] == {"value": 0.5, "unit": "dimensionless"}


@needs_env
def test_a_model_is_loaded_stepped_and_reset_with_every_state_in_its_unit(
    mujoco: tuple[Client, Path],
) -> None:
    client, root = mujoco
    (root / "models").mkdir()
    (root / "models" / "pendulum.xml").write_text(PENDULUM)
    info = client.call("load_model", path="models/pendulum.xml")
    assert info["timestep"] == {"value": 0.002, "unit": "s"}
    assert info["integrator"] == "mjINT_EULER"
    assert info["gravity"] == {"value": [0.0, 0.0, -9.81], "unit": "m/s^2"}
    stepped = client.call("step", steps=100, controls=[0.5])
    assert stepped["time"]["value"] == pytest.approx(0.2) and stepped["time"]["unit"] == "s"
    joint = stepped["joints"][0]
    assert joint["name"] == "hinge" and joint["type"] == "hinge"
    assert joint["angle"]["unit"] == "rad" and joint["angle"]["value"][0] != 0
    assert joint["angular_velocity"]["unit"] == "rad/s"
    assert client.call("reset")["time"]["value"] == 0.0
    assert "1 actuators" in client.refusal("step", steps=1, controls=[1.0, 2.0])
    inline = client.call("load_model", xml=PENDULUM)
    assert inline["actuators"] == 1
    outside = root.parent / "outside.xml"
    outside.write_text(PENDULUM)
    assert "outside" in client.refusal("load_model", path=str(outside))


@needs_env
@pytest.mark.skipif(not BINARY, reason="no pinned Claude Code binary named")
def test_the_pinned_binary_connects_to_both_servers_lists_their_tools_and_calls_one(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
    from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

    worktree, home, config = tmp_path / "wt", tmp_path / "home", tmp_path / "config"
    for directory in (worktree, home, config):
        directory.mkdir()
    servers = {
        "control": {"type": "stdio", "command": _command("control_server.py")[0],
                    "args": _command("control_server.py")[1:]},
        "mujoco": {"type": "stdio", "command": _command("mujoco_server.py")[0],
                   "args": _command("mujoco_server.py", "--root", str(worktree))[1:]},
    }  # fmt: skip
    argv = role_argv(
        BINARY,
        prompt="compute the margins",
        spawn_args=("--setting-sources", ""),
        model="claude-sonnet-5",
        session_id="44444444-4444-4444-8444-444444444444",
        max_turns=3,
        effort="low",
        thinking_display="omitted",
    )
    argv[argv.index(NO_TOOL_SERVERS)] = json.dumps({"mcpServers": servers})
    script = Script(main=[tool("mcp__control__margins", system=LOOP), text("done")])
    with serving(script) as (api, url):
        done = subprocess.run(
            argv,
            env={
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                "TERM": "dumb",
                "CLAUDE_CONFIG_DIR": str(config),
                "CLAUDE_CODE_MAX_RETRIES": "0",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "DISABLE_TELEMETRY": "1",
                "MAX_MCP_OUTPUT_TOKENS": "25000",
                "ANTHROPIC_BASE_URL": url,
                "ANTHROPIC_API_KEY": DUMMY_KEY,
            },  # fmt: skip
            cwd=worktree,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    init = next(json.loads(line) for line in done.stdout.splitlines() if '"subtype":"init"' in line)
    assert {s["name"]: s["status"] for s in init["mcp_servers"]} == {
        "control": "connected",
        "mujoco": "connected",
    }
    offered = {name for request in api.requests for name in request.offered_tools}
    assert {n for n in offered if n.startswith("mcp__")} == {
        "mcp__control__margins", "mcp__control__step_response", "mcp__control__frequency_response",
        "mcp__control__poles_zeros", "mcp__mujoco__load_model", "mcp__mujoco__step",
        "mcp__mujoco__state", "mcp__mujoco__reset", "mcp__mujoco__model_info",
    }  # fmt: skip
    assert api.failures == []
    answered = api.requests[-1].last_user
    assert '"phase_margin"' in answered and "28.020" in answered


def _tetrahedron() -> bytes:
    """A binary STL of a small tetrahedron: the least mesh MuJoCo loads."""
    import struct

    v = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, 0.1)]
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    out = b"\0" * 80 + struct.pack("<I", len(faces))
    for face in faces:
        out += struct.pack("<3f", 0, 0, 0)
        for index in face:
            out += struct.pack("<3f", *v[index])
        out += b"\0\0"
    return out


@needs_env
def test_a_mesh_under_the_worktree_is_read_for_mujoco_and_one_outside_is_not(
    mujoco: tuple[Client, Path],
) -> None:
    client, root = mujoco
    (root / "models" / "meshes").mkdir(parents=True)
    (root / "models" / "meshes" / "tetra.stl").write_bytes(_tetrahedron())
    model = (
        '<mujoco><asset><mesh name="t" file="meshes/tetra.stl"/></asset><worldbody><body>'
        '<freejoint/><geom type="mesh" mesh="t"/></body></worldbody></mujoco>'
    )
    (root / "models" / "robot.xml").write_text(model)
    loaded = client.call("load_model", path="models/robot.xml")
    assert loaded["bodies"] == 2
    free = client.call("step", steps=10)["joints"][0]
    assert free["type"] == "free" and free["position"]["unit"] == "m"
    (root.parent / "outside.stl").write_bytes(_tetrahedron())
    escaping = model.replace("meshes/tetra.stl", "../../outside.stl")
    assert "outside the worktree" in client.refusal("load_model", xml=escaping)


@needs_env
def test_mujoco_s_own_refusal_is_one_bounded_line_with_no_path_of_the_machine(
    mujoco: tuple[Client, Path],
) -> None:
    client, root = mujoco
    (root / "broken.xml").write_text(
        '<mujoco><worldbody><geom type="mesh" mesh="none"/></worldbody></mujoco>'
    )
    text = client.refusal("load_model", path="broken.xml")
    assert text.startswith('{"error": "MuJoCo refused the model: ')
    assert len(text) < 400 and "\\n" not in text
    assert str(root) not in text and os.path.realpath(root) not in text
