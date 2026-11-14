"""A parameter range narrowed by stability evidence keeps both ranges and says why, in plain words.

"The real kit balances with the published controller" may bound the plant, as stability
evidence only (never as margin evidence): the real robot is one point of the ranges. A parameter so
narrowed keeps its range as sourced or assumed (``low``, ``high``) and gains a ``bounded``
range beside it, with an evidence line that says so and names the recorded report the bound
was computed in. The scorer's corners then run over the bounded range; a reader still sees
what the evidence did.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MODULE = "physgate.evaluation.whole.plant"
_DRAFT = Path(__file__).resolve().parents[4] / "src/physgate/evaluation/whole/plant_v0_draft.json"
_DIGEST = "ab" * 32
_EVIDENCE = (
    "bounded by stability evidence: the kit balances with the published controller; see "
    f"scripts/whole_design_corners.py --bound, report sha256 {_DIGEST}"
)


class _Module:
    """The plant module, each name it lacks an assertion's failure rather than an error."""

    def __init__(self, module: ModuleType) -> None:
        self._module = module

    def __getattr__(self, name: str) -> Any:
        assert hasattr(self._module, name), f"the plant module has no {name}"
        return getattr(self._module, name)


def _plant() -> Any:
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return _Module(importlib.import_module(_MODULE))


def _bound_of(p: Any) -> Any:
    assert hasattr(p, "bounded"), "a parameter carries no bounded range"
    return p.bounded


def _draft() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_DRAFT.read_text())
    for p in loaded["parameters"].values():
        p.pop("bounded", None)
    return loaded


def _bounded(low: float, high: float, **over: Any) -> dict[str, Any]:
    bound: dict[str, Any] = {"low": low, "high": high, "evidence": _EVIDENCE, "report": _DIGEST}
    bound.update(over)
    return bound


def _with_com_bound(**over: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_draft())
    doc["parameters"]["com_height"]["bounded"] = _bounded(0.005, 0.060, **over)
    return doc


def _parse(doc: dict[str, Any]) -> Any:
    return _plant().parse_plant(json.dumps(doc).encode())


def _refused(doc: dict[str, Any], says: str) -> None:
    plant = _plant()
    try:
        plant.parse_plant(json.dumps(doc).encode())
    except plant.PlantError as exc:
        assert says in str(exc), str(exc)
        return
    pytest.fail(f"the plant file was taken; it should be refused for {says!r}")


def test_a_bounded_parameter_keeps_its_stated_range_beside_the_bounded_one() -> None:
    p = _parse(_with_com_bound()).parameters["com_height"]
    assert (p.low, p.high) == (0.005, 0.078)
    b = _bound_of(p)
    assert (b.low, b.high) == (0.005, 0.060)
    assert b.evidence == _EVIDENCE
    assert b.report == _DIGEST


def test_an_unbounded_parameter_has_no_bounded_range() -> None:
    assert _bound_of(_parse(_with_com_bound()).parameters["body_inertia"]) is None


def test_the_span_is_the_bounded_range_where_there_is_one_and_the_stated_one_elsewhere() -> None:
    plant = _plant()
    parsed = _parse(_with_com_bound())
    assert plant.span(parsed.parameters["com_height"]) == (0.005, 0.060)
    assert plant.span(parsed.parameters["body_inertia"]) == (
        parsed.parameters["body_inertia"].low,
        parsed.parameters["body_inertia"].high,
    )


def test_the_corners_run_over_the_bounded_range() -> None:
    plant = _plant()
    found = list(plant.corners(_parse(_with_com_bound()), ("com_height",)))
    assert sorted(c["com_height"] for c in found) == [0.005, 0.060]


def test_a_parameter_bounded_to_a_point_is_not_ranged() -> None:
    plant = _plant()
    doc = copy.deepcopy(_draft())
    doc["parameters"]["com_height"]["bounded"] = _bounded(0.019, 0.019)
    parsed = _parse(doc)
    assert plant.ranged(parsed, ("com_height", "body_inertia")) == ("body_inertia",)
    assert [c["com_height"] for c in plant.corners(parsed, ("com_height",))] == [0.019]


def _blank_evidence(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"]["evidence"] = "   "


def _no_evidence(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"].pop("evidence")


def _evidence_without_its_report(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"]["evidence"] = (
        "bounded by stability evidence: the kit balances with the published controller"
    )


def _no_report(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"].pop("report")


def _report_not_a_digest(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"].update(report="ab12", evidence=_EVIDENCE + " ab12")


def _bound_below_the_range(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"]["low"] = 0.004


def _bound_above_the_range(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"]["high"] = 0.080


def _bound_without_the_value(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"].update(low=0.020, high=0.060)


def _bound_reversed(d: dict[str, Any]) -> None:
    d["parameters"]["com_height"]["bounded"].update(low=0.060, high=0.010)


def _frozen_assumption_bounded_to_a_point(d: dict[str, Any]) -> None:
    d.update(status="frozen")
    d["parameters"]["com_height"]["bounded"].update(low=0.019, high=0.019)


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (_blank_evidence, "names no evidence"),
        (_no_evidence, "plant parameter file"),
        (_evidence_without_its_report, "names no report"),
        (_no_report, "plant parameter file"),
        (_report_not_a_digest, "plant parameter file"),
        (_bound_below_the_range, "inside its stated range"),
        (_bound_above_the_range, "inside its stated range"),
        (_bound_without_the_value, "inside its stated range"),
        (_bound_reversed, "inside its stated range"),
        (_frozen_assumption_bounded_to_a_point, "a point"),
    ],
    ids=[
        "evidence_blank",
        "evidence_missing",
        "evidence_without_report",
        "report_missing",
        "report_not_a_digest",
        "below_range",
        "above_range",
        "without_value",
        "reversed",
        "frozen_point",
    ],
)
def test_a_bounded_range_off_its_rules_is_refused(change: Any, says: str) -> None:
    doc = _with_com_bound()
    change(doc)
    _refused(doc, says)


def test_a_draft_may_bound_an_assumption_to_a_point() -> None:
    doc = copy.deepcopy(_draft())
    doc["parameters"]["com_height"]["bounded"] = _bounded(0.019, 0.019)
    assert _bound_of(_parse(doc).parameters["com_height"]).low == 0.019


def test_every_bounded_range_in_the_draft_says_so_in_plain_words() -> None:
    parsed = _plant().parse_plant(_DRAFT.read_bytes())
    bounds = {n: _bound_of(p) for n, p in parsed.parameters.items()}
    bounded = {n: b for n, b in bounds.items() if b is not None}
    for name, bound in bounded.items():
        assert bound.evidence.startswith(
            "bounded by stability evidence: the kit balances with the published controller; "
            "see scripts/whole_design_corners.py --bound"
        ), name
        assert bound.report in bound.evidence, name


def test_friction_is_never_bounded_by_the_stability_evidence() -> None:
    parsed = _plant().parse_plant(_DRAFT.read_bytes())
    assert _bound_of(parsed.parameters["gearbox_friction"]) is None
