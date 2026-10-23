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
        "requirements": [
            "the heater shall draw at most 20.0 W",
            "no number here",
            "the heater shall draw at most 20.0W in standby",
            "the pack shall store at least 20.0 Wh",
        ],
        "quantities": {
            "supply_voltage": {"value": 12.0, "unit": "V"},
            "resistance": {"value": 6.0, "unit": "ohm"},
            "power_draw": {"value": 12.0, "unit": "W"},
            "max_power": {"value": 10.0, "unit": "W"},
            "estimated_power": {"value": 10.0, "unit": "W"},
            "maximum_power": {"value": 10.0, "unit": "W"},
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


def test_rounding_allows_half_a_percent_of_the_terms_not_of_the_sides() -> None:
    # a - b == c with a = 100 W, b = 99.0 W, c = 1.10 W: the sides are 1.00 W and 1.10 W, a miss
    # of 0.10 W. Over every additive term the allowance is 0.5 % of 200.1 W = 1.0 W, so the
    # relation holds; over the two sides alone it would be 0.5 % of 2.1 W and would not.
    nodes: dict[str, dict[str, Any]] = {
        "e.a": {
            "id": "e.a",
            "constrains": [],
            "requirements": [],
            "quantities": {
                "p_in": {"value": 100.0, "unit": "W"},
                "p_loss": {"value": 99.0, "unit": "W"},
                "p_out": {"value": 1.1, "unit": "W"},
            },
        }
    }

    def i(sym: str, q: str) -> dict[str, Any]:
        v = nodes["e.a"]["quantities"][q]
        return {"symbol": sym, "node": "e.a", "quantity": q, "value": v["value"], "unit": v["unit"]}

    f = form(
        relation="a - b == c",
        inputs=[i("a", "p_in"), i("b", "p_loss"), i("c", "p_out")],
    )
    out = V.verify_form(f, nodes)
    assert out["failure"] == "within_tolerance" and out["code"] == "N"


def test_a_relation_without_inputs_falls_back() -> None:
    for code in ("G", "L"):
        f = form(code, relation="0.6 + 0.5 <= 1", inputs=[], tolerance="inequality")
        out = verified(f)
        assert out["failure"] == "no_input" and out["code"] == "N", code
    f = form(relation="0.6 + 0.5 <= 1", inputs=[], tolerance="inequality", fallback_code="D")
    assert verified(f)["code"] == "D"


def test_every_listed_input_must_be_used_in_the_relation() -> None:
    f = form(
        relation="P <= Pm",
        inputs=[
            inp("P", "e.heater", "power_draw"),
            inp("Pm", "e.heater", "max_power"),
            inp("R", "e.heater", "resistance"),
        ],
        tolerance="inequality",
    )
    out = verified(f)
    assert out["failure"] == "unused_input" and out["code"] == "N"
    f["inputs"] = f["inputs"][:2]
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
    f = form(relation="P <= pi * g_n * R * V * 0", tolerance="inequality")
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


def test_a_rating_token_is_a_whole_token_of_the_name() -> None:
    # "estimated" holds "rated" and "maximum" holds "max", but neither is the token
    for name in ("estimated_power", "maximum_power"):
        f = form(
            relation="P <= M",
            kind="limit",
            tolerance="inequality",
            inputs=[inp("P", "e.heater", "power_draw"), inp("M", "e.heater", name)],
        )
        assert verified(f)["failure"] == "pairing", name


def test_a_limit_pairs_across_one_edge_in_either_direction() -> None:
    # e.heater constrains e.supply; the left input on e.supply reaches e.heater only backwards
    f = form(
        relation="S <= M",
        kind="limit",
        tolerance="inequality",
        inputs=[inp("S", "e.supply", "power_supply"), inp("M", "e.heater", "max_power")],
    )
    assert verified(f)["code"] == "L"  # 11 W <= 10 W is violated
    f["relation"] = "M >= S"
    assert verified(f)["code"] == "L"


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


def test_a_requirement_unit_is_a_whole_unit_token() -> None:
    def with_req(index: int, unit: str) -> dict[str, Any]:
        req = {"symbol": "Q", "node": "e.heater", "requirement": index, "value": 20.0, "unit": unit}
        return form(
            relation="P >= Q",
            kind="limit",
            tolerance="inequality",
            inputs=[inp("P", "e.heater", "power_draw"), req],
        )

    # "h" is in "heater" and "W" is in "Wh", but neither is the requirement's unit
    assert verified(with_req(0, "h"))["failure"] == "unit_differs"
    assert verified(with_req(3, "W"))["failure"] == "unit_differs"
    # a number may stand right before its unit
    assert verified(with_req(2, "W"))["code"] == "L"
    assert verified(with_req(0, "W"))["code"] == "L"


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


DATA = Path(__file__).resolve().parent / "testdata"


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("smoke_out.json", 2 + 219 + 0 + 1351),
        ("schema_fail_probe_out.json", 10 + 533 + 4042 + 1696),
    ],
)
def test_the_ledger_row_of_a_real_session_output(tmp_path: Path, name: str, tokens: int) -> None:
    led = tmp_path / "ledger.jsonl"
    out = DATA / name
    args = ["ledger", str(led), "measured-c1", "P0001", "1", "claude-opus-5-5", str(out)]
    assert V.main([*args, "0", "1", "0", ""]) == 0
    assert V.main([*args, "1", "0", "1", "usage_limit"]) == 0
    a, b = (json.loads(x) for x in led.read_text().splitlines())
    assert a["tokens"] == b["tokens"] == tokens == V.tokens_of(out)
    assert a["models_used"] == ["claude-opus-5-5"] == V.model_of(out)
    assert (a["exit"], a["valid"], a["standin"], a["infrastructure"]) == (0, True, False, None)
    assert (b["exit"], b["valid"], b["standin"], b["infrastructure"]) == (
        1,
        False,
        True,
        "usage_limit",
    )
    assert V.ledger_total(led) == 2 * tokens


def _charged(led: Path, out: Path, cause: str = "") -> dict[str, Any]:
    args = ["ledger", str(led), "s", "P0009", "1", "claude-opus-5-5", str(out), "1", "0", "0"]
    assert V.main([*args, cause]) == 0
    return V.ledger_rows(led)[-1]


def _ledger_rows(led: Path, rows: list[dict[str, Any]]) -> None:
    led.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_a_call_that_reports_no_usage_is_charged_from_the_ledger(tmp_path: Path) -> None:
    led = tmp_path / "ledger.jsonl"
    live = DATA / "retry_exhausted_probe_out.json"  # two turns, modelUsage {}, every count 0
    assert V.tokens_of(live) == 0 and V.model_of(live) == []
    # no completed try yet: one session of CRITERIA §12's 50,000
    r = _charged(led, live)
    assert (r["tokens"], r["tokens_estimated"], r["models_used"]) == (50_000, True, [])
    # then the largest count a completed try reported, never an estimate or a failed call's
    _ledger_rows(
        led,
        [
            {"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000, "infrastructure": None},
            {"step": "s", "packet": "P0002", "try": 2, "tokens": 4_000},
            {"step": "s", "packet": "P0003", "try": 1, "tokens": 90_000, "tokens_estimated": True},
            {"step": "s", "packet": "P0004", "try": 1, "tokens": 80_000, "infrastructure": "x"},
        ],
    )
    assert _charged(led, live)["tokens"] == 7_000
    # ceil(turns / 2) sessions of it: five turns are three
    many = tmp_path / "five.json"
    many.write_text(json.dumps({**json.loads(live.read_text()), "num_turns": 5}))
    assert _charged(led, many)["tokens"] == 3 * 7_000
    # no result at all is one turn; so is a cut-off output
    (tmp_path / "broke.json").write_text("Error: something broke")
    r = _charged(led, tmp_path / "broke.json", "no_result")
    assert (r["tokens"], r["tokens_estimated"], r["infrastructure"]) == (7_000, True, "no_result")
    (tmp_path / "cut.json").write_text('[{"type":"system"')
    assert _charged(led, tmp_path / "cut.json")["tokens"] == 7_000
    # an output that reports its usage is counted as it reports it
    r = _charged(led, DATA / "smoke_out.json")
    assert r["tokens"] == 1572 and "tokens_estimated" not in r


@pytest.mark.parametrize(
    ("cause", "charge"),
    [
        ("usage_limit", 0),
        ("rate_limit (429)", 0),
        ("credential_refused (401)", 0),
        ("credential_refused (403)", 0),
        ("api_error (500)", 7_000),
        ("api_error", 7_000),
        ("error_result", 7_000),
        ("exit 2", 7_000),
    ],
)
def test_a_call_refused_before_any_work_is_charged_nothing(
    tmp_path: Path, cause: str, charge: int
) -> None:
    led = tmp_path / "ledger.jsonl"
    _ledger_rows(led, [{"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000}])
    (tmp_path / "out.json").write_text('{"type":"result","is_error":true}')
    r = _charged(led, tmp_path / "out.json", cause)
    assert r["tokens"] == charge and r.get("tokens_estimated", False) is (charge > 0)


@pytest.mark.parametrize(
    ("cause", "turns", "charge"),
    [
        ("usage_limit", None, 0),  # no result: no model turn completed
        ("usage_limit", 1, 0),
        ("usage_limit", 2, 7_000),
        ("rate_limit (429)", 3, 2 * 7_000),
        ("credential_refused (401)", 1, 0),
        ("credential_refused (403)", 4, 2 * 7_000),
    ],
)
def test_a_refusal_after_model_turns_ran_is_charged(
    tmp_path: Path, cause: str, turns: int | None, charge: int
) -> None:
    led = tmp_path / "ledger.jsonl"
    _ledger_rows(led, [{"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000}])
    out = tmp_path / "out.json"
    if turns is None:
        out.write_text("Error: You've hit your usage limit")
    else:
        out.write_text(json.dumps({"type": "result", "is_error": True, "num_turns": turns}))
    r = _charged(led, out, cause)
    assert r["tokens"] == charge and r.get("tokens_estimated", False) is (charge > 0)


def test_a_charge_never_falls_below_what_the_output_reports(tmp_path: Path) -> None:
    led = tmp_path / "ledger.jsonl"
    _ledger_rows(led, [{"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000}])
    out = tmp_path / "out.json"
    big = {"type": "result", "num_turns": 2, "usage": {"input_tokens": 100_000}, "modelUsage": {}}
    out.write_text(json.dumps(big))
    r = _charged(led, out)
    assert (r["tokens"], r["tokens_estimated"]) == (100_000, True)


def test_no_usage_is_an_empty_model_usage_not_a_count_of_zero(tmp_path: Path) -> None:
    led = tmp_path / "ledger.jsonl"
    _ledger_rows(led, [{"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000}])
    out = tmp_path / "out.json"
    named = {"type": "result", "num_turns": 2, "usage": {}, "modelUsage": {"claude-opus-5-5": {}}}
    out.write_text(json.dumps(named))
    r = _charged(led, out)
    assert r["tokens"] == 0 and "tokens_estimated" not in r


def test_a_ledger_that_cannot_be_read_charges_one_session_unit(tmp_path: Path) -> None:
    led = tmp_path / "ledger.jsonl"
    led.write_text(
        '{"step": "s", "packet": "P0001", "try": 1, "tokens": 7_000}\n{"step": "s", "tok'
    )
    assert V.charge_unit(led) == 50_000
    tokens, estimated = V.charged(DATA / "retry_exhausted_probe_out.json", "", led)
    assert (tokens, estimated) == (50_000, True)


def test_the_ledger_total_refuses_a_ledger_it_cannot_read(tmp_path: Path) -> None:
    led = tmp_path / "ledger.jsonl"
    assert V.ledger_total(led) == 0  # no ledger yet: nothing spent
    led.write_text('{"step": "s", "packet": "P", "try": 1, "tokens": 3}\n\n')
    assert V.ledger_total(led) == 3
    for bad in ('{"step": "s", "tok', '{"tokens": true}', '{"tokens": 2.5}', '"x"'):
        led.write_text('{"step": "s", "packet": "P", "try": 1, "tokens": 3}\n' + bad + "\n")
        with pytest.raises(V.LedgerUnreadable):
            V.ledger_total(led)
    assert V.main(["spent", str(led)]) == 1


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
