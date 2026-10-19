"""The fixtures R-PG-02's script tests share: a small sourced set and real runs over it.

Nothing here is a set of the experiment. The set is the instrument's own test design (three
electrical nodes) with every number sourced to a row of a small parts sheet, so the source
check has something to find: the inertial sensor's rate cites a page whose only row is not a
number (``unresolved``, a listed sheet pair), and one driver limit cites a row the sheet calls
a continuous rating. The runs are real ``run_instrument`` runs with scripted stand-in reviewers:
each review's verdict and items are written here per item, and nothing is called.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for _p in (REPO / "tests", REPO / "tests" / "unit" / "evaluation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import instrument_corpus as ic  # noqa: E402

from physgate.evaluation.inject.corpus import load_corpus  # noqa: E402
from physgate.evaluation.inject.runner import control_id, review_id, run_instrument  # noqa: E402
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.protocols import (  # noqa: E402
    Artefact,
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)

MODEL = ic.REVIEWER
URL = ic.SOURCE
SENSOR_URL = "https://www.pololu.com/product/2736/specs"
ROWS: dict[str, dict[str, Any]] = {
    "R1.01": {"quantity": "driver peak output current", "value": 3, "unit": "A", "url": URL},
    "R1.02": {"quantity": "stall current", "value": 2.4, "unit": "A", "url": URL},
    "R1.03": {"quantity": "stall current, faster winding", "value": 2.6, "unit": "A", "url": URL},
    "R1.04": {
        "quantity": "driver continuous output current",
        "value": 3.2,
        "unit": "A",
        "url": URL,
    },
    "R1.05": {"quantity": "stall current, fastest winding", "value": 3.5, "unit": "A", "url": URL},
    "R2.01": {"quantity": "gyroscope rate options", "value": None, "unit": None, "url": SENSOR_URL},
}


def _sourced(payload: dict[str, Any], url: str) -> dict[str, Any]:
    payload = json.loads(json.dumps(payload))
    for quantity in payload["quantities"].values():
        quantity["source"] = url
    return payload


SENSOR = _sourced(ic.IMU, SENSOR_URL)
BASE = (ic.DRIVER, ic.MOTOR, SENSOR)
M1: dict[str, Any] = {
    **ic.MAGNITUDE_ARTEFACT,
    "clean": {"nodes": [ic.with_quantity(SENSOR, "sample_rate", 800, "Hz")]},
    "injected": {"nodes": [ic.with_quantity(SENSOR, "sample_rate", 50_000, "Hz")]},
}
P1: dict[str, Any] = ic.PROPAGATION_ARTEFACT
#: A unit item whose clean twin the gate refuses for headroom against a continuous rating.
U1: dict[str, Any] = {
    "id": "u1",
    "error_class": "unit",
    "expected_check": "units",
    "assigned_role": "electrical",
    "description": "the motor's stall current is written in volts",
    "edge": None,
    "clean": {
        "nodes": [
            ic.with_quantity(ic.MOTOR, "stall_current", 3.5, "A"),
            ic.with_quantity(ic.DRIVER, "current_limit", 3.2, "A"),
        ]
    },
    "injected": {
        "nodes": [
            ic.with_quantity(ic.MOTOR, "stall_current", 3.5, "V"),
            ic.with_quantity(ic.DRIVER, "current_limit", 3.2, "A"),
        ]
    },
}


def write_set(root: Path, stated: bool = False) -> Path:
    """The sourced test set: m1 and p1, and u1 when ``stated``."""
    artefacts = (M1, P1, U1) if stated else (M1, P1)
    return ic.write_corpus(root, artefacts=artefacts, base_nodes=BASE, rows=ROWS)


def _usage(n: int) -> tuple[MessageUsage, ...]:
    return (
        MessageUsage(
            message_id=f"msg-{n}",
            usage=Usage(
                input_tokens=10,
                output_tokens=20,
                cache_read_input_tokens=30,
                cache_creation_input_tokens=40,
            ),
        ),
    )


#: One review's script: ("pass",), ("fail", [(item, section, evidence)], failing item),
#: ("blocked",) or ("unavailable", cause).
Script = tuple[Any, ...]


@dataclass
class Scripted:
    """A stand-in reviewer answering each item from its script, by the item's run id."""

    scripts: Mapping[str, Script]
    model: str = MODEL
    seen: list[str] = field(default_factory=list)

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact.subtask_id)
        script = self.scripts.get(artefact.subtask_id, ("pass",))
        n = len(self.seen)
        if script[0] == "unavailable":
            raise ReviewUnavailableError(
                "scripted",
                cause=script[1],
                session_id=f"s{n}",
                reviewer_model=self.model,
                usage=_usage(1000 + n),
            )
        if script[0] == "blocked":
            return ReviewResult(
                verdict="blocked",
                finding="no load is given for the safety check",
                reviewer_model=self.model,
                session_id=f"s{n}",
                usage=_usage(n),
                spec_defects=(SpecDefect(finding="no load is given", blocking=True),),
            )
        if script[0] == "pass":
            return ReviewResult(
                verdict="pass",
                finding="every item is met",
                reviewer_model=self.model,
                session_id=f"s{n}",
                usage=_usage(n),
            )
        _, items, failing = script
        return ReviewResult(
            verdict="fail",
            finding="a rejecting item is unmet in the revision",
            reviewer_model=self.model,
            session_id=f"s{n}",
            usage=_usage(n),
            failing_item=failing,
            items=tuple(
                ItemVerdict(item=i, section=s, result="unmet", evidence=e) for i, s, e in items
            ),
        )


def scripts_for(seed: int, by_item: Mapping[str, tuple[Script, Script]]) -> dict[str, Script]:
    """Each item's (injected, twin) scripts under the run ids the seed gives them."""
    out: dict[str, Script] = {}
    for aid, (injected, twin) in by_item.items():
        out[review_id(seed, aid)] = injected
        out[control_id(seed, aid)] = twin
    return out


def real_run(
    set_dir: Path,
    into: Path,
    seed: int,
    by_item: Mapping[str, tuple[Script, Script]],
    kind: str = "paired",
    lanes: int = 1,
) -> Path:
    """A real instrument run over ``set_dir``, its reviews scripted; returns the run dir."""
    corpus = load_corpus(set_dir)
    reviewer = Scripted(scripts_for(seed, by_item))
    run_instrument(
        corpus,
        {"electrical": reviewer},
        run_dir=into / "run",
        scratch=into / "scratch",
        run_id=f"fixture-{seed}-{kind}",
        seed=seed,
        review_clean_twins=True,
        lanes=lanes,
        lane_reviewers=[{"electrical": reviewer}] * lanes if lanes > 1 else None,
        reviewer_kind=kind,  # type: ignore[arg-type]
        progress=lambda _line: None,
    )
    return into / "run"
