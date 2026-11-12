"""A brief, the plan one decomposition call submitted for it, and the call's sealed stream.

The plan is of a run with the integration role, so it carries both lists the harness checks:
the consumers of each interface and the system requirements allocated to integration. Each
module's name differs from its role, so a rendering that prints one where it means the other is
seen. The stream is the call's as the binary writes it: an assistant message from the
decomposition's model and its one structured submission, then the result.

The plan packet's module is looked up when a test asks for it, so a test of it fails on an
assertion, not at collection, in a tree without it.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from physgate.orchestrator.plan import IntegratedPlan, Plan, plan_sha256
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.rubric import Rubric, load_rubric

#: The harness checkout: its ``knowledge/`` holds the design rubric and library as promoted.
REPO = Path(__file__).resolve().parents[3]
DECOMPOSITION = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
SESSION = "decomposition-session-1"

BRIEF = (
    "Build a two-wheeled balancing robot.\n\n"
    "## Acceptance criteria\n\n"
    "1. It stands upright for 60 s.\n"
    "2. It recovers from a 5 N push.\n"
)
DRIVE_SPEC = (
    "Close the balance loop.\n\n## Acceptance criteria\n\n1. The tilt stays within 2 deg.\n"
)
FW_SPEC = "Read the IMU.\n\n## Acceptance criteria\n\n1. The IMU is read at 100 Hz.\n"


def module(name: str) -> ModuleType:
    """``physgate.reviewers.<name>``, asserted to exist."""
    full = f"physgate.reviewers.{name}"
    assert importlib.util.find_spec(full) is not None, f"{full} does not exist"
    return importlib.import_module(full)


def plan_answer() -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": "iface.drive",
        "kind": "interface",
        "domain": "control",
        "owner_role": "control",
        "quantities": {
            "v_bus": {"value": 12, "unit": "V", "source": "brief", "written_by": "control"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-23T00:00:00Z",
    }
    return {
        "modules": [
            {"name": "drive", "role": "control", "module_dir": "modules/drive", "spec": DRIVE_SPEC},
            {"name": "imu-fw", "role": "firmware", "module_dir": "modules/fw", "spec": FW_SPEC},
        ],
        "interface_nodes": [node],
        "interface_consumers": [{"interface": "iface.drive", "consumers": ["imu-fw"]}],
        "system_requirements": [
            {
                "requirement": "2",
                "contributing": [
                    {"module": "drive", "criterion": "1"},
                    {"module": "imu-fw", "criterion": "1"},
                ],
            }
        ],
    }


def integrated_plan() -> IntegratedPlan:
    return IntegratedPlan.model_validate_json(json.dumps(plan_answer()))


def base_plan() -> Plan:
    answer = plan_answer()
    del answer["interface_consumers"], answer["system_requirements"]
    return Plan.model_validate_json(json.dumps(answer))


def stream_text(model: str = DECOMPOSITION) -> str:
    events = [
        {"type": "system", "subtype": "init", "model": model, "cwd": "/w", "tools": []},
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "model": model,
                "content": [
                    {"type": "thinking", "thinking": "Two modules share the drive interface."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "StructuredOutput",
                        "input": plan_answer(),
                    },
                ],
            },
        },
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1},
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


def write_stream(root: Path, text: str | None = None) -> Path:
    path = root / "decomposition" / "stdout.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stream_text() if text is None else text)
    return path


def under_review(root: Path, **overrides: Any) -> Any:  # noqa: ANN401 - built from the module
    """The plan under review, its stream written under ``root`` and sealed as it stands."""
    stream = write_stream(root, overrides.pop("stream_text", None))
    plan = overrides.pop("plan", None) or integrated_plan()
    fields: dict[str, Any] = {
        "brief": BRIEF,
        "brief_sha256": hashlib.sha256(BRIEF.encode()).hexdigest(),
        "plan": plan,
        "plan_sha256": plan_sha256(plan),
        "stream": str(stream),
        "stream_seal": seal(stream.read_bytes()),
        "decomposition_model": DECOMPOSITION,
        "decomposition_session_id": SESSION,
    }
    fields.update(overrides)
    return module("plan_packet").PlanUnderReview(**fields)


def design_rubric() -> Rubric:
    return load_rubric(REPO / "knowledge", "design")
