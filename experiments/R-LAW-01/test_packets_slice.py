"""R-LAW-01 §4, §6 and §7 on the synthetic fixture: prompts, packets, the slice and the bank rule.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import pytest

import law_extract as X
import law_fixture as F
import law_packets as P
import law_slice as SL
import law_verify as V


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    fx = F.build(tmp_path_factory.mktemp("fx"))
    lines, _, sets = F.extract_fixture(fx)
    return {**fx, "lines": lines, "setdata": sets, "out": tmp_path_factory.mktemp("pk")}


# ---------------------------------------------------------------- prompts


def test_the_reality_prompt_and_schema_are_the_prior_ones() -> None:
    prompt, schema = P.reality_prompt()
    assert hashlib.sha256(prompt.encode()).hexdigest() == P.REALITY_PROMPT_SHA256
    assert hashlib.sha256(json.dumps(schema).encode()).hexdigest() == P.REALITY_SCHEMA_SHA256


def test_version_0_holds_the_fourteen_examples_and_no_placeholder() -> None:
    p = P.coder_prompt()
    assert P.EXAMPLES_PLACEHOLDER not in p
    assert "\n14. **N, process.**" in p and "\n1. **G.**" in p
    assert "\n15. " not in p
    a = P.adjudicator_prompt(p)
    assert P.CODER_SPAN_PLACEHOLDER not in a
    assert "THE DESIGN DATA" in a and "14. **N, process.**" in a
    assert a.rstrip().endswith("that names the step of the procedure that decides it.")


def test_a_taken_rewording_replaces_its_sentence_only() -> None:
    p0, p1 = P.coder_prompt(), P.coder_prompt(("W7",))
    assert "Records: absent and required" in p0 and "Records: absent and required" not in p1
    assert "Absent means the field or record is not there at all." in p1
    assert len(p1.splitlines()) < len(p0.splitlines()) + 1


def test_taken_examples_follow_example_14_in_bank_order() -> None:
    p = P.coder_prompt(("X8", "X2"))
    i14, i15, i16 = p.index("\n14. "), p.index("\n15. "), p.index("\n16. ")
    assert i14 < i15 < i16
    assert "runtime of 2.00 h" in p[i15:i16]
    assert "rated voltage of 10.0 V" in p[i16:]


def test_an_unknown_bank_item_is_refused() -> None:
    with pytest.raises(X.Refused):
        P.coder_prompt(("W9",))


def test_the_coder_schema_names_every_gate_relation() -> None:
    s = P.coder_schema()
    props = s["properties"]["findings"]["items"]["properties"]
    assert set(props["gate_relation"]["enum"]) >= {
        "power_budget",
        "mass_sum",
        "propagation",
        "none",
    }
    assert "chosen" not in props
    assert "chosen" in P.coder_schema(True)["properties"]["findings"]["items"]["required"]


# ---------------------------------------------------------------- coder packets


def test_coder_packets_cut_at_ten_and_shuffle_per_seed(fx: dict[str, Any]) -> None:
    lines = [
        dict(x, line_id=f"L{i:04d}", pair="m1", side="injected", set="fresh")
        for i, x in enumerate(fx["lines"] * 2, 1)
    ]
    k1 = P.build_coder_packets(lines, fx["setdata"], P.SEED_C1, fx["out"] / "c1")
    k2 = P.build_coder_packets(lines, fx["setdata"], P.SEED_C2, fx["out"] / "c2")
    sizes = [len(k["findings"]) for k in k1.values()]
    assert max(sizes) <= 10 and sum(sizes) == len(lines)
    order1 = [lid for k in k1.values() for lid in k["findings"].values()]
    order2 = [lid for k in k2.values() for lid in k["findings"].values()]
    assert sorted(order1) == sorted(order2) and order1 != order2
    want = sorted(x["line_id"] for x in lines)
    random.Random(29).shuffle(want)
    assert order1 == want


def test_a_coder_packet_shows_the_design_without_updated_or_written_by(fx: dict[str, Any]) -> None:
    text = (fx["out"] / "c1" / "P0001.md").read_text()
    design = text.split("## The design, all nodes\n\n")[1].split(V.SHEET_MARK)[0]
    nodes = json.loads(design)
    assert all("updated" not in n for n in nodes)
    assert all("written_by" not in q for n in nodes for q in n["quantities"].values())
    assert V.sheet_ok(text, X.sha256_bytes(F.SHEET.encode()))
    assert P.blind_counts(fx["out"] / "c1")["blind"]


def test_the_blind_check_finds_a_planted_field(tmp_path: Path) -> None:
    good = (
        "# Packet P0001\n\nintro\n\n## Findings (x)\n\n### F1\nthe twin is fine\n\n"
        "## The design, all nodes\n\n[]\n" + V.SHEET_MARK + "sheet\n"
    )
    (tmp_path / "P0001.md").write_text(good)
    res = P.blind_counts(tmp_path)
    assert res["blind"] and res["hits"]["findings_words"] == 1
    (tmp_path / "P0002.md").write_text(good.replace("intro", "arm a-fresh, injected"))
    assert not P.blind_counts(tmp_path)["blind"]
    (tmp_path / "P0002.md").write_text(good.replace("the twin", "ES-3 says"))
    assert not P.blind_counts(tmp_path)["blind"]


def test_adjudicator_packets_label_forms_by_a_seeded_draw(fx: dict[str, Any]) -> None:
    lines = fx["lines"][:4]
    codes = []
    for x in lines:
        codes.append(
            {
                "step": "s",
                "who": "c1",
                "line_id": x["line_id"],
                "code": "N",
                "form": {"code": "N", "id": "F9", "n_kind": "wording"},
            }
        )
        codes.append(
            {
                "step": "s",
                "who": "c2",
                "line_id": x["line_id"],
                "code": "D",
                "form": {"code": "D", "id": "F3", "d_kind": "table"},
            }
        )
    codes[-1]["code"] = "N"  # the last line is agreed, so not disputed
    key = P.build_adjudicator_packets(lines, codes, "s", fx["setdata"], fx["out"] / "adj")
    found = [lid for k in key.values() for lid in k["findings"].values()]
    assert sorted(found) == sorted(x["line_id"] for x in lines[:3])
    for pid, k in key.items():
        text = (fx["out"] / "adj" / f"{pid}.md").read_text()
        for fid, lab in k["labels"].items():
            a = json.loads(text.split(f"### {fid}\n")[1].split("Form A:\n")[1].split("\n")[0])
            assert a["id"] == fid
            assert a["code"] == ("N" if lab["A"] == "c1" else "D")


def test_the_audit_draws_twenty_percent_rounded_up(fx: dict[str, Any], tmp_path: Path) -> None:
    src = tmp_path / "c1"
    src.mkdir()
    key = {f"P{i:04d}": {"findings": {}} for i in range(1, 12)}
    for pid in key:
        (src / f"{pid}.md").write_text(pid)
    (src / "key.json").write_text(json.dumps(key))
    picked = P.build_audit(src, tmp_path / "audit")
    assert len(picked) == math.ceil(0.2 * 11) == 3
    assert picked == sorted(random.Random(47).sample(sorted(key), 3))
    for pid in picked:
        assert (tmp_path / "audit" / f"{pid}.md").read_text() == pid


# ---------------------------------------------------------------- the slice and the bank


def test_the_slice_draws_one_fresh_pair_per_class_then_two_practice_classes(
    fx: dict[str, Any],
) -> None:
    pairs = SL.draw(fx["lines"], fx["setdata"])
    assert len(pairs["fresh"]) == 4 and len(pairs["practice"]) == 2
    classes = {fx["setdata"]["fresh"].artefacts[p]["error_class"] for p in pairs["fresh"]}
    assert len(classes) == 4
    assert SL.draw(fx["lines"], fx["setdata"]) == pairs


def test_the_slice_refuses_a_class_without_an_eligible_pair(fx: dict[str, Any]) -> None:
    lines = [x for x in fx["lines"] if not (x["set"] == "fresh" and x["pair"] == "p1")]
    with pytest.raises(X.Refused):
        SL.draw(lines, fx["setdata"])


def test_the_bank_rule_takes_items_at_two_disagreements() -> None:
    codes = []
    for i, (a, b) in enumerate([("L", "N"), ("N", "L"), ("D", "L"), ("G", "G"), ("D", "N")]):
        codes.append({"step": "slice-r1", "who": "c1", "line_id": f"L{i}", "code": a})
        codes.append({"step": "slice-r1", "who": "c2", "line_id": f"L{i}", "code": b})
    counts = SL.disagreements(codes, "slice-r1")
    assert counts == {"L–N": 2, "D–L": 1, "D–N": 1}
    items = P.bank(P.criteria_text())
    assert SL.taken(counts, items) == ["W1", "W2", "W8", "X1", "X5", "X7", "X8"]
    assert SL.taken({"D–L": 1}, items) == []
