"""A small corpus for the instrument's own tests, and a fake reviewer. Neither is the measurement's.

The design is three electrical nodes: a driver, a motor that constrains it, and
an IMU with no edges. Two artefacts are written over it, one wrong in magnitude
and one wrong in propagation, each with a clean twin the gate passes. They are
written here, by the person who built the gate, so they test the apparatus and
nothing else.

**The fake reviewer is a fake.** Its verdict is a seeded coin per artefact id,
so both stamping paths run; it means nothing about any artefact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gate_fixtures

from physgate.evaluation.inject.corpus import (
    ARTEFACTS_DIRNAME,
    BASE_NAME,
    SOURCES_NAME,
    manifest_for,
    write_manifest,
)
from physgate.orchestrator.protocols import Artefact, MessageUsage, ReviewResult, Usage

AUTHOR = "claude-sonnet-5"
REVIEWER = "claude-opus-5-5"
LABEL = "a test design for the instrument's own tests, not the measurement's"

#: A source in the corpus's own form: the URL of the row a number was copied from.
SOURCE = "https://www.pololu.com/product/3575/specs"


def node(node_id: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401 - the fixture's own fields
    """The gate's fixture node, with every quantity sourced by URL as a corpus requires."""
    payload = gate_fixtures.node(node_id, **fields)
    for quantity in payload["quantities"].values():
        quantity["source"] = SOURCE
    return payload


DRIVER = node("electrical.driver", quantities={"current_limit": (3, "A")})
MOTOR = node(
    "electrical.motor_left",
    quantities={"stall_current": (2.4, "A")},
    constrains=["electrical.driver"],
)
IMU = node("electrical.imu", quantities={"sample_rate": (1000, "Hz")})
BASE_NODES = (DRIVER, MOTOR, IMU)


def with_quantity(payload: dict[str, Any], name: str, value: float, unit: str) -> dict[str, Any]:
    """``payload`` with one quantity set, everything else as it was."""
    quantity = {**payload["quantities"][name], "value": value, "unit": unit}
    return {**payload, "quantities": {**payload["quantities"], name: quantity}}


MAGNITUDE_ARTEFACT: dict[str, Any] = {
    "id": "m1",
    "error_class": "magnitude",
    "expected_check": "magnitude",
    "assigned_role": "electrical",
    "description": "the IMU is sampled at 50 kHz, above the fastest rate its register sets",
    "edge": None,
    "clean": {"nodes": [with_quantity(IMU, "sample_rate", 800, "Hz")]},
    "injected": {"nodes": [with_quantity(IMU, "sample_rate", 50_000, "Hz")]},
}
PROPAGATION_ARTEFACT: dict[str, Any] = {
    "id": "p1",
    "error_class": "propagation",
    "expected_check": "propagation",
    "assigned_role": "electrical",
    "description": "the motor's stall current rises and the driver's limit is not revisited",
    "edge": {"source": "electrical.motor_left", "target": "electrical.driver"},
    "clean": {
        "nodes": [
            with_quantity(MOTOR, "stall_current", 2.6, "A"),
            with_quantity(DRIVER, "current_limit", 3.2, "A"),
        ]
    },
    "injected": {"nodes": [with_quantity(MOTOR, "stall_current", 2.6, "A")]},
}
ARTEFACTS = (MAGNITUDE_ARTEFACT, PROPAGATION_ARTEFACT)


#: The parts sheet the test design's numbers may cite, by row.
SOURCE_ROWS: dict[str, dict[str, Any]] = {
    "R1.01": {"quantity": "stall current @ 6V", "value": 1.5, "unit": "A", "url": SOURCE},
    "R1.02": {"quantity": "mass (weight)", "value": 9.5, "unit": "g", "url": SOURCE},
    "R5.01": {"quantity": "cell nominal voltage", "value": 1.2, "unit": "V", "url": SOURCE},
    "R8.01": {"quantity": "gyroscope ODR options", "value": None, "unit": None, "url": SOURCE},
}


def write_corpus(
    root: Path,
    artefacts: tuple[dict[str, Any], ...] = ARTEFACTS,
    base_nodes: tuple[dict[str, Any], ...] = BASE_NODES,
    author: str = AUTHOR,
    rows: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Write a corpus at ``root`` with its parts sheet and manifest, and return ``root``."""
    (root / ARTEFACTS_DIRNAME).mkdir(parents=True)
    sheet = {"label": "a test parts sheet", "rows": SOURCE_ROWS if rows is None else rows}
    (root / SOURCES_NAME).write_text(json.dumps(sheet))
    (root / BASE_NAME).write_text(json.dumps({"label": LABEL, "nodes": list(base_nodes)}))
    for artefact in artefacts:
        (root / ARTEFACTS_DIRNAME / f"{artefact['id']}.json").write_text(json.dumps(artefact))
    (root / "README.md").write_text("A corpus for tests.\n")
    write_manifest(root, manifest_for(root, label=LABEL, author_model=author))
    return root


def coin(seed: int, subtask_id: str) -> bool:
    """The fake's seeded coin: whether it passes ``subtask_id``."""
    return hashlib.sha256(f"fake:{seed}:{subtask_id}".encode()).digest()[0] % 2 == 0


@dataclass
class SeededFakeReviewer:
    """A labelled fake reviewer: a seeded coin per artefact, zero tokens, no model call."""

    seed: int = 7
    model: str = REVIEWER
    reports_model: str | None = None
    seen: list[Artefact] = field(default_factory=list)
    before_verdict: Callable[[Artefact], None] | None = None

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact)
        if self.before_verdict is not None:
            self.before_verdict(artefact)
        passed = coin(self.seed, artefact.subtask_id)
        zero = Usage(
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return ReviewResult(
            verdict="pass" if passed else "fail",
            finding="fake verdict, seeded coin; it means nothing",
            reviewer_model=self.reports_model or self.model,
            session_id=f"fake-{len(self.seen)}",
            usage=(MessageUsage(message_id=f"fake-{len(self.seen)}", usage=zero),),
        )
