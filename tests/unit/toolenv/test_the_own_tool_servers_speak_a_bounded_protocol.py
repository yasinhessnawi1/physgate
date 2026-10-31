"""The repository's own tool servers speak a small, bounded protocol, and import nothing of ours.

The control and MuJoCo servers are standalone scripts that run on the tool environment's
interpreter. Their protocol layer is the standard library only, and the libraries they compute
with are imported inside each tool, so everything here runs them on the harness's own
interpreter, which has none of those libraries: what is tested is the framing, the limits and
the argument checks, which never reach a library. What they compute is the integration test's.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
SERVERS = REPO / "toolenv" / "servers"

#: The tools each server offers, and nothing else.
TOOLS = {
    "control_server.py": {"margins", "step_response", "frequency_response", "poles_zeros"},
    "mujoco_server.py": {"load_model", "step", "state", "reset", "model_info"},
}
#: What the pinned binary sends in its opening request.
OPENING = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "0"},
}
#: A transfer function every control tool accepts.
PLANT = {"transfer_function": {"numerator": [4, 4], "denominator": [1, 2, 1, 0]}}


class Server:
    """One server process, spoken to a line at a time."""

    def __init__(self, script: str, *args: str) -> None:
        path = SERVERS / script
        assert path.is_file(), f"no server {script}"
        self.process = subprocess.Popen(
            [sys.executable, "-I", str(path), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next = 0

    def send_raw(self, data: bytes) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def read(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        assert line, "the server closed its output"
        answer = json.loads(line)
        assert isinstance(answer, dict)
        return answer

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next, "method": method}
        if params is not None:
            message["params"] = params
        self.send_raw(json.dumps(message).encode() + b"\n")
        answer = self.read()
        assert answer.get("id") == self._next
        return answer

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": tool, "arguments": arguments})

    def close(self) -> int:
        assert self.process.stdin is not None
        self.process.stdin.close()
        return self.process.wait(timeout=30)


def _started(script: str, *args: str) -> Iterator[Server]:
    server = Server(script, *args)
    try:
        assert server.request("initialize", OPENING)["result"]["protocolVersion"] == "2025-06-18"
        server.send_raw(b'{"jsonrpc": "2.0", "method": "notifications/initialized"}\n')
        yield server
    finally:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait()


@pytest.fixture
def control() -> Iterator[Server]:
    yield from _started("control_server.py")


@pytest.fixture
def mujoco(tmp_path: Path) -> Iterator[Server]:
    yield from _started("mujoco_server.py", "--root", str(tmp_path))


def _refused(answer: dict[str, Any]) -> str:
    """The tool's refusal text: a result marked as an error, never a protocol failure."""
    result = answer.get("result")
    assert isinstance(result, dict), answer
    assert result.get("isError") is True, answer
    text = result["content"][0]["text"]
    assert isinstance(text, str) and text.isprintable()
    return text


# ---- the protocol ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", sorted(TOOLS))
def test_each_server_offers_exactly_its_tools_with_closed_schemas(script: str) -> None:
    for server in _started(script, *(("--root", "/") if "mujoco" in script else ())):
        tools = server.request("tools/list")["result"]["tools"]
        assert {tool["name"] for tool in tools} == TOOLS[script]
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert not {"oneOf", "anyOf", "allOf"} & set(schema), tool["name"]
            assert tool["description"].strip()
        assert server.close() == 0


@pytest.mark.parametrize("version", ["2025-11-25", "2025-06-18", "2025-03-26"])
def test_a_known_protocol_version_is_answered_with_itself(version: str) -> None:
    server = Server("control_server.py")
    try:
        answer = server.request("initialize", {**OPENING, "protocolVersion": version})
        assert answer["result"]["protocolVersion"] == version
        assert answer["result"]["capabilities"] == {"tools": {}}
        assert answer["result"]["serverInfo"]["name"] == "control"
    finally:
        server.close()


def test_an_unknown_method_and_a_malformed_line_are_answered_and_the_server_goes_on(
    control: Server,
) -> None:
    assert control.request("resources/list")["error"]["code"] == -32601
    control.send_raw(b"{not json\n")
    assert control.read()["error"]["code"] == -32700
    control.send_raw(b"[" * 100_000 + b"\n")
    assert control.read()["error"]["code"] == -32700
    control.send_raw(b'{"jsonrpc": "2.0", "method": "notifications/cancelled"}\n')
    assert control.request("ping")["result"] == {}


def test_a_ten_megabyte_line_is_refused_unread_and_the_server_goes_on(control: Server) -> None:
    big = {"jsonrpc": "2.0", "id": 99, "method": "tools/call",
           "params": {"name": "margins", "arguments": {"note": "x" * (10 << 20)}}}  # fmt: skip
    control.send_raw(json.dumps(big).encode() + b"\n")
    answer = control.read()
    assert answer["error"]["code"] == -32600
    assert answer["id"] is None
    assert "error" not in control.request("tools/list")


def test_an_unknown_tool_is_a_protocol_error(control: Server) -> None:
    assert control.call("upload_firmware", {})["error"]["code"] == -32602


# ---- the arguments --------------------------------------------------------------------------


def test_an_argument_the_schema_does_not_name_is_refused(control: Server) -> None:
    assert "not_a_field" in _refused(control.call("margins", {"system": PLANT, "not_a_field": 1}))


def test_a_missing_or_wrongly_typed_argument_is_refused(control: Server) -> None:
    assert "system" in _refused(control.call("margins", {}))
    bad = {"transfer_function": {"numerator": ["4"], "denominator": [1, 2, 1, 0]}}
    assert "number" in _refused(control.call("margins", {"system": bad}))
    both = {**PLANT, "state_space": {"A": [[0]], "B": [[1]], "C": [[1]], "D": [[0]]}}
    assert "exactly one" in _refused(control.call("poles_zeros", {"system": both}))


def test_a_value_that_is_not_finite_or_too_long_is_refused(control: Server) -> None:
    long = {"transfer_function": {"numerator": [1] * 1000, "denominator": [1, 1]}}
    assert "at most" in _refused(control.call("poles_zeros", {"system": long}))
    grid = {"value": [0.1] * 100_000, "unit": "rad/s"}
    assert "at most" in _refused(
        control.call("frequency_response", {"system": PLANT, "omega": grid})
    )
    control.send_raw(
        b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"margins",'
        b'"arguments":{"system":{"transfer_function":{"numerator":[NaN],"denominator":[1]}}}}}\n'
    )
    assert "finite" in _refused(control.read())


def test_a_quantity_in_a_unit_the_tool_does_not_take_is_refused(control: Server) -> None:
    grid = {"value": [0.1, 1.0], "unit": "rpm"}
    assert "unit" in _refused(control.call("frequency_response", {"system": PLANT, "omega": grid}))


def test_a_model_path_outside_the_root_is_refused_before_any_file_is_read(
    mujoco: Server, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "elsewhere.xml"
    assert "outside" in _refused(mujoco.call("load_model", {"path": str(outside)}))
    assert "outside" in _refused(mujoco.call("load_model", {"path": "../elsewhere.xml"}))
    link = tmp_path / "link.xml"
    link.symlink_to(outside)
    assert "outside" in _refused(mujoco.call("load_model", {"path": "link.xml"}))


def test_a_control_character_in_a_text_argument_is_refused(mujoco: Server) -> None:
    assert "control character" in _refused(mujoco.call("load_model", {"path": "a\x1b[2J.xml"}))
    assert "control character" in _refused(mujoco.call("load_model", {"xml": "<mujoco/>\x00"}))


def test_stepping_before_a_model_is_loaded_is_refused(mujoco: Server) -> None:
    assert "no model" in _refused(mujoco.call("step", {"steps": 1}))


# ---- what the scripts may depend on ---------------------------------------------------------


def _imports(path: Path) -> list[tuple[str, bool]]:
    """Every module a file imports, and whether the import is at the top level."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = set(map(id, tree.body))
    found: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, id(node) in top) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, id(node) in top))
    return found


def test_no_server_imports_the_harness_and_none_needs_a_library_to_start() -> None:
    scripts = sorted(SERVERS.glob("*.py"))
    assert {p.name for p in scripts} >= set(TOOLS)
    local = {p.stem for p in scripts}
    for path in scripts:
        found = _imports(path)
        assert found, path
        for module, at_top in found:
            root = module.split(".")[0]
            assert root != "physgate", (path.name, module)
            if at_top:
                assert root in sys.stdlib_module_names or root in local, (path.name, module)
