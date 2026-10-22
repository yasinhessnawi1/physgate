"""R-LAW-01 §2.5 and §5.5 on invented forms: the sheet refusal and the machine verification.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import law_extract as X
import law_verify as V
import pytest

NODES: dict[str, dict[str, Any]] = {
    "e.heater": {
        "id": "e.heater",
        "constrains": ["e.supply"],
        "requirements": ["the heater shall draw at most 20.0 W", "no number here"],
        "quantities": {
            "supply_voltage": {"value": 12.0, "unit": "V"},
            "resistance": {"value": 6.0, "unit": "ohm"},
            "power_draw": {"value": 12.0, "unit": "W"},
            "max_power": {"value": 10.0, "unit": "W"},
            "temperature": {"value": 25.0, "unit": "degC"},
            "max_temperature": {"value": 20.0, "unit": "degC"},
            "rise": {"value": 5.0, "unit": "delta_degC"},
        },
    },
    "e.supply": {
        "id": "e.supply",
        "constrains": [],
        "requirements": [],
        "quantities": {"power_supply": {"value": 11.0, "unit": "W"}},
    },
    "e.far": {
        "id": "e.far",
        "constrains": [],
        "requirements": [],
        "quantities": {"rated_power": {"value": 1.0, "unit": "W"}},
    },
}


def inp(sym: str, node: str, q: str) -> dict[str, Any]:
    v = NODES[node]["quantities"][q]
    return {"symbol": sym, "node": node, "quantity": q, "value": v["value"], "unit": v["unit"]}


def form(code: str = "L", **kw: Any) -> dict[str, Any]:  # noqa: ANN401
    f: dict[str, Any] = {
        "id": "F1",
        "defect": "d",
        "code": code,
        "multiple_defects": False,
        "reason": "r",
    }
    if code in ("G", "L"):
        f.update(
            {
                "gate_relation": "none",
                "relation": "P == V**2 / R",
                "law": "Joule heating",
                "kind": "law",
                "inputs": [
                    inp("P", "e.heater", "power_draw"),
                    inp("V", "e.heater", "supply_voltage"),
                    inp("R", "e.heater", "resistance"),
                ],
                "tolerance": "rounding",
                "evaluation": "24 W against 12 W",
                "family": 4,
                "fallback_code": "N",
            }
        )
    f.update(kw)
    return f


def verified(f: dict[str, Any]) -> dict[str, Any]:
    return V.verify_form(f, NODES)


# ---------------------------------------------------------------- the sheet


def test_a_packet_without_the_sheet_at_its_digest_is_refused() -> None:
    sheet = "| row | value |\n| R1 | 1 |\n"
    d = X.sha256_bytes(sheet.encode())
    good = "# Packet P1\n\nbody\n" + V.SHEET_MARK + sheet
    assert V.sheet_ok(good, d)
    assert not V.sheet_ok(good + "x", d)
    assert not V.sheet_ok("# Packet P1\n\nbody\n", d)
    assert not V.sheet_ok(good + V.SHEET_MARK + sheet, d)
    assert not V.sheet_ok(good)  # the frozen digest is not this sheet's


# ---------------------------------------------------------------- the fields


def test_required_fields_per_code() -> None:
    V.check_fields(form())
    V.check_fields(form("D", d_kind="table"))
    V.check_fields(form("N", n_kind="wording"))
    with pytest.raises(V.Invalid):
        V.check_fields(form("D"))
    with pytest.raises(V.Invalid):
        V.check_fields(form("N", n_kind="taste"))
    with pytest.raises(V.Invalid):
        V.check_fields({k: v for k, v in form().items() if k != "fallback_code"})
    with pytest.raises(V.Invalid):
        V.check_fields(form(tolerance="relative"))
    with pytest.raises(V.Invalid):
        V.check_fields(form(multiple_defects=True))
    V.check_fields(form(multiple_defects=True, further=[{"defect": "x", "code": "N"}]))
    with pytest.raises(V.Invalid):
        V.check_fields(form("N", n_kind="wording"), adjudicator=True)
    V.check_fields(form("N", n_kind="wording", chosen="A"), adjudicator=True)


# ---------------------------------------------------------------- the relation


def test_a_law_violated_beyond_rounding_stays_l() -> None:
    out = verified(form())
    assert out["code"] == "L" and out["failure"] is None
    assert out["relation_facts"]["literals"] == [2]


def test_a_miss_within_rounding_falls_back() -> None:
    nodes = json.loads(json.dumps(NODES))
    nodes["e.heater"]["quantities"]["power_draw"]["value"] = 24.1
    f = form()
    f["inputs"][0]["value"] = 24.1
    out = V.verify_form(f, nodes)
    assert out["failure"] == "within_tolerance" and out["code"] == "N"


def test_rounding_counts_every_additive_term() -> None:
    f = form(
        relation="P + P == V**2 / R + P",
        tolerance="rounding",
    )
    # 24 vs 36: miss 12, allowance 0.5 % of 12+12+24+12 = 0.3
    assert verified(f)["code"] == "L"


def test_inequality_and_comparator_classes() -> None:
    f = form(
        relation="P <= Pm",
        inputs=[inp("P", "e.heater", "power_draw"), inp("Pm", "e.heater", "max_power")],
        tolerance="inequality",
    )
    assert verified(f)["code"] == "L"
    f2 = dict(f, tolerance="rounding")
    assert verified(f2)["failure"] == "comparator_class"
    f3 = dict(f, relation="P == Pm", tolerance="inequality")
    assert verified(f3)["failure"] == "comparator_class"
    f4 = dict(f, relation="P >= Pm")
    assert verified(f4)["failure"] == "within_tolerance"


def test_relative_tolerance_is_capped_at_25_percent() -> None:
    f = form(tolerance="relative", tolerance_percent=30)
    assert verified(f)["failure"] == "relative_above_25"
    f = form(tolerance="relative", tolerance_percent=25)
    assert verified(f)["code"] == "L"  # 24 vs 12: a 50 % miss
    f = form(tolerance="relative", tolerance_percent=10, relation="P * 2 == V**2 / R")
    assert verified(f)["failure"] == "within_tolerance"


def test_values_and_units_must_be_the_nodes() -> None:
    f = form()
    f["inputs"][0]["value"] = 13.0
    assert verified(f)["failure"] == "value_differs"
    f = form()
    f["inputs"][0]["unit"] = "mW"
    assert verified(f)["failure"] == "unit_differs"


def test_an_input_on_no_node_makes_l_if_data() -> None:
    f = form()
    f["inputs"][2] = {
        "symbol": "R",
        "node": "e.heater",
        "quantity": "winding_resistance",
        "value": 6.0,
        "unit": "ohm",
    }
    out = verified(f)
    assert out["failure"] == "on_no_node" and out["code"] == "L-if-data"
    f["inputs"][2]["node"] = "e.missing"
    assert verified(f)["code"] == "L-if-data"


def test_the_restricted_syntax_refuses_anything_else() -> None:
    for rel in (
        "P == __import__('os')",
        "P == V.real",
        "P == V**2 / R == P",
        "P",
        "P == max(V, R)",
        "P == V ** R",
        "P == [V]",
        "P == 'x'",
        "P == True",
    ):
        assert verified(form(relation=rel))["failure"] in ("unparsed", "dimension"), rel
    assert verified(form(relation="P == Q * 2"))["failure"] == "undefined_symbol"
    assert verified(form(relation="P == sqrt(V**4) / R"))["code"] == "L"


def test_a_dimension_mismatch_falls_back() -> None:
    assert verified(form(relation="P == V / R"))["failure"] == "dimension"
    assert verified(form(relation="P == V + R"))["failure"] == "dimension"


def test_constants_pi_and_standard_gravity() -> None:
    f = form(relation="P <= pi * g_n * R * 0", tolerance="inequality")
    assert verified(f)["failure"] == "dimension"


def test_temperatures_convert_absolute_and_difference() -> None:
    f = form(
        relation="T <= Tm",
        kind="limit",
        tolerance="inequality",
        inputs=[inp("T", "e.heater", "temperature"), inp("Tm", "e.heater", "max_temperature")],
    )
    assert verified(f)["code"] == "L"
    f2 = form(
        relation="Tm + d <= T",
        tolerance="inequality",
        inputs=[
            inp("T", "e.heater", "temperature"),
            inp("Tm", "e.heater", "max_temperature"),
            inp("d", "e.heater", "rise"),
        ],
    )
    # 293.15 K + 5 K = 298.15 K <= 298.15 K holds: not violated
    assert verified(f2)["failure"] == "within_tolerance"


def test_the_pairing_check_for_a_limit() -> None:
    ok = form(
        relation="P <= S",
        kind="limit",
        tolerance="inequality",
        inputs=[inp("P", "e.heater", "power_draw"), inp("S", "e.supply", "power_supply")],
    )
    # no rating token on either side
    assert verified(ok)["failure"] == "pairing"
    rated = dict(ok, inputs=[inp("P", "e.heater", "power_draw"), inp("S", "e.heater", "max_power")])
    assert verified(rated)["code"] == "L"
    literal = dict(rated, relation="P <= 1 * S")
    assert verified(literal)["failure"] == "pairing"
    strict = dict(rated, relation="P < S")
    assert verified(strict)["failure"] == "pairing"
    far = dict(ok, inputs=[inp("P", "e.heater", "power_draw"), inp("S", "e.far", "rated_power")])
    assert verified(far)["failure"] == "pairing"


def test_a_requirement_input_quotes_its_number_and_unit() -> None:
    req = {"symbol": "Q", "node": "e.heater", "requirement": 0, "value": 20.0, "unit": "W"}
    f = form(
        relation="P >= Q",
        kind="limit",
        tolerance="inequality",
        inputs=[inp("P", "e.heater", "power_draw"), req],
    )
    assert verified(f)["code"] == "L"  # 12 W >= 20 W is violated
    f["relation"] = "Q <= P"
    assert verified(f)["code"] == "L"
    f["relation"] = "P <= Q"
    assert verified(f)["failure"] == "within_tolerance"
    bad = dict(req, value=21.0)
    f2 = dict(f, inputs=[inp("P", "e.heater", "power_draw"), bad])
    assert verified(f2)["failure"] == "value_differs"
    none = dict(req, requirement=1)
    f3 = dict(f, inputs=[inp("P", "e.heater", "power_draw"), none])
    assert verified(f3)["failure"] == "value_differs"
    gone = dict(req, requirement=5)
    f4 = dict(f, inputs=[inp("P", "e.heater", "power_draw"), gone])
    assert verified(f4)["code"] == "L-if-data"


def test_l_if_data_listing_a_present_quantity_is_inconsistent() -> None:
    f = form(
        "L-if-data",
        relation="x",
        law="l",
        kind="law",
        inputs=[],
        family=4,
        missing=[{"node": "e.heater", "quantity": "resistance"}],
    )
    out = verified(f)
    assert out["code"] == "L-if-data" and out["inconsistent"]
    f["missing"] = [{"node": None, "quantity": "resistance"}]
    assert not verified(f)["inconsistent"]


def test_d_and_n_pass_unchanged() -> None:
    assert verified(form("D", d_kind="source"))["code"] == "D"
    assert verified(form("N", n_kind="process"))["code"] == "N"


# ---------------------------------------------------------------- sessions and deciding forms


def write_try(path: Path, findings: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "type": "result",
                    "structured_output": {"findings": findings},
                    "usage": {"input_tokens": 5, "output_tokens": 7},
                }
            ]
        )
    )


def test_a_line_takes_the_first_valid_try(tmp_path: Path) -> None:
    sheet = "sheet\n"
    d = X.sha256_bytes(sheet.encode())
    (tmp_path / "P0001.md").write_text("# Packet P0001\n" + V.SHEET_MARK + sheet)
    (tmp_path / "key.json").write_text(
        json.dumps({"P0001": {"findings": {"F1": "L0001", "F2": "L0002", "F3": "L0003"}}})
    )
    write_try(tmp_path / "P0001.try1.json", [form("D", d_kind="table"), form("D", id="F2")])
    write_try(tmp_path / "P0001.try2.json", [form("N", id="F2", n_kind="wording")])
    forms, used = V.session_forms(tmp_path, tmp_path, "P0001", "coder", d)
    assert used == {"F1": "try1", "F2": "try2", "F3": "none"}
    assert forms["F3"] is None
    assert V.tokens_of(tmp_path / "P0001.try1.json") == 12
    with pytest.raises(X.Refused):
        V.session_forms(tmp_path, tmp_path, "P0001", "coder")


def row(who: str, lid: str, code: str | None, failure: str | None = None) -> dict[str, Any]:
    f = None if code is None else form(code, d_kind="table", n_kind="wording")
    return {
        "step": "measured",
        "who": who,
        "line_id": lid,
        "code": code,
        "form": f,
        "failure": failure,
    }


def test_the_deciding_form() -> None:
    codes = [
        row("c1", "L1", "N"),
        row("c2", "L1", "N"),
        row("c1", "L2", "N", "within_tolerance"),
        row("c2", "L2", "N"),
        row("c1", "L3", "N"),
        row("c2", "L3", "D"),
        row("adj", "L3", "D"),
        row("c1", "L4", "N"),
        row("c2", "L4", None),
        row("c1", "L5", "N"),
        row("c2", "L5", "D"),
    ]
    d = V.deciding_forms(codes)
    assert d["L1"]["_verified"]["who"] == "c1"
    assert d["L2"]["_verified"]["who"] == "c2"
    assert d["L3"]["_verified"]["who"] == "adj"
    assert d["L4"] is None and d["L5"] is None
