"""Sheets, lines and runs for the price-sheet check's rows, built here and never read from a run.

A sheet is built as the data a file would hold, so each row can break exactly one field of it. A
run is the shared parts fixture's event log (a synthetic run, written as data in this tree), cut
or changed where a row needs another shape.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from parts_bom_fixture import LINES

from physgate.build.bom.check import Line
from physgate.build.bom.sheet import Count, Sheet

EXAMPLE = {"kind": "example"}
READ = {"kind": "read", "where": "a distributor's page", "read_on": "2026-11-20"}

HEADER: dict[str, Any] = {
    "kind": "example fixture",
    "statement": "An example sheet for these rows, not live distributor data.",
    "written_for": "the rows' own node ids",
    "written_on": "2026-11-24",
}


def facts(**changed: Any) -> dict[str, Any]:  # noqa: ANN401 - a fact or None, as a row needs
    """All five facts present and within both limits, with ``changed`` put over them."""
    held: dict[str, Any] = {
        "availability": {"status": "in_stock", "source": EXAMPLE},
        "unit_price": {"value": 12.5, "unit": "NOK", "source": EXAMPLE},
        "minimum_order_quantity": {"value": 1, "unit": "1", "source": EXAMPLE},
        "order_multiple": {"value": 1, "unit": "1", "source": EXAMPLE},
        "lead_time_to_norway": {"value": 7, "unit": "d", "scope": "norway", "source": READ},
    }
    held.update(changed)
    return {name: fact for name, fact in held.items() if fact is not None}


def entry(answers: list[str], **changed: Any) -> dict[str, Any]:  # noqa: ANN401
    """One entry answering ``answers``, with facts as :func:`facts` gives them."""
    return {
        "answers": answers,
        "description": "a part for the rows",
        "maker": {"value": "A maker", "source": EXAMPLE},
        "maker_part_number": {"value": "PN-1", "source": EXAMPLE},
        "facts": facts(**changed),
    }


def sheet_data(*entries: dict[str, Any]) -> dict[str, Any]:
    """A sheet's data: the rows' header and ``entries``."""
    return {"header": copy.deepcopy(HEADER), "entries": list(entries)}


def sheet(*entries: dict[str, Any]) -> Sheet:
    """The sheet ``entries`` make, validated as a file would be."""
    return Sheet.model_validate_json(json.dumps(sheet_data(*entries)))


def line(node: str = "electrical.wheel_encoder", domain: str = "electrical") -> Line:
    """A line to find, as the run gives it."""
    return Line(node=node, domain=domain, label="a part")


def count(value: int) -> Count:
    """A quantity needed, as a person states it."""
    return Count(value=value, unit="1")


def write_run(run_dir: Path, lines: list[dict[str, Any]] | None = None) -> Path:
    """A run directory holding ``lines`` (by default the whole fixture run) as its event log."""
    run_dir.mkdir(parents=True, exist_ok=True)
    held = [dict(one) for one in LINES] if lines is None else lines
    (run_dir / "events.jsonl").write_bytes(
        b"".join(json.dumps(one).encode() + b"\n" for one in held)
    )
    return run_dir


def before(kind: str) -> list[dict[str, Any]]:
    """The fixture run's lines up to the first of ``kind``."""
    kinds = [one["kind"] for one in LINES]
    return [copy.deepcopy(dict(one)) for one in LINES[: kinds.index(kind)]]


def not_asking() -> list[dict[str, Any]]:
    """The fixture's opening as a run that does not ask which parts a person has."""
    lines = before("decision_taken")
    del lines[0]["parts_on_hand"]
    del lines[2]["components"]
    return lines


def write_json(path: Path, data: object) -> Path:
    """``data`` as a JSON file at ``path``."""
    path.write_text(json.dumps(data))
    return path


#: The fixture run's one part a person answered "find".
FIXTURE_FIND = "electrical.wheel_encoder"


def renamed(node: str) -> list[dict[str, Any]]:
    """The fixture run with its part to find named ``node``, its release record digest remade.

    The release line names the digest and length of the decisions' record (each component's
    node, label, choice and what it stated, as canonical JSON), so a renamed part needs it remade
    from the renamed lines for replay to take the log.
    """
    lines = [
        json.loads(json.dumps(one).replace(json.dumps(FIXTURE_FIND), json.dumps(node)))
        for one in LINES
    ]
    (planned,) = [one for one in lines if one["kind"] == "decomposed"]
    (release,) = [one for one in lines if one["kind"] == "parts_released"]
    labels = {one["node"]: one["label"] for one in planned["components"]}
    record = json.dumps(
        {
            "components": [
                {
                    "node": one["node"],
                    "label": labels[one["node"]],
                    "choice": one["choice"],
                    "declared": (one["parts"] or {}).get("declared", {}),
                    "texts": list((one["parts"] or {}).get("texts", [])),
                }
                for one in release["components"]
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    release["record_sha256"] = hashlib.sha256(record).hexdigest()
    release["record_length"] = len(record)
    return lines
