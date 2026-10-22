"""R-LAW-01 §4, §6 and §7 on the synthetic fixture: prompts, packets, the slice and the bank rule.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import law_extract as X
import law_fixture as F
import law_packets as P
import law_reality as R
import law_slice as SL
import law_verify as V
import pytest


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


def _one_packet(src: Path, dst: Path, edit: Callable[[str], str] | None = None) -> Path:
    """A packet dir holding the first packet of ``src`` and its key, the packet edited."""
    dst.mkdir()
    key = json.loads((src / "key.json").read_text())
    pid = sorted(key)[0]
    text = (src / f"{pid}.md").read_text()
    (dst / f"{pid}.md").write_text(edit(text) if edit else text)
    (dst / "key.json").write_text(json.dumps({pid: key[pid]}))
    return dst


def _role_and_class(fx: dict[str, Any], src: Path) -> tuple[str, str]:
    key = json.loads((src / "key.json").read_text())
    k = key[sorted(key)[0]]
    art = fx["setdata"][k["set"]].artefacts[k["pair"]]
    return str(art["assigned_role"]), str(art["error_class"])


def test_the_blind_check_passes_built_packets_and_finds_a_planted_word(
    fx: dict[str, Any], tmp_path: Path
) -> None:
    sets = fx["setdata"]
    c1 = tmp_path / "c1"
    P.build_coder_packets(fx["lines"], sets, P.SEED_C1, c1)
    assert P.blind_counts(c1, sets)["blind"]
    head = "## Findings (the reviewers'"
    planted = _one_packet(c1, tmp_path / "a", lambda t: t.replace(head, "arm a-fresh\n\n" + head))
    assert not P.blind_counts(planted, sets)["blind"]
    item = _one_packet(c1, tmp_path / "b", lambda t: t.replace("### F1\n", "### F1\nES-3 says ", 1))
    assert not P.blind_counts(item, sets)["blind"]
    word = _one_packet(c1, tmp_path / "c", lambda t: t.replace("### F1\n", "### F1\nthe twin ", 1))
    res = P.blind_counts(word, sets)
    assert res["blind"] and res["hits"]["findings_words"] == 1


def test_the_blind_check_catches_the_role_and_class_of_a_coder_packet(
    fx: dict[str, Any], tmp_path: Path
) -> None:
    sets = fx["setdata"]
    c1 = tmp_path / "c1"
    P.build_coder_packets(fx["lines"], sets, P.SEED_C1, c1)
    role, cls = _role_and_class(fx, c1)
    head = "## Findings (the reviewers'"
    said = f"A reviewer of the {role} domain, class {cls}.\n\n"
    bad = _one_packet(c1, tmp_path / "a", lambda t: t.replace(head, said + head, 1))
    res = P.blind_counts(bad, sets)
    assert not res["blind"]
    assert any(w.endswith(f"role:{role}") for w in res["where"])
    assert any(w.endswith(f"class:{cls}") for w in res["where"])
    # a field the design never holds, planted in a node
    field = _one_packet(
        c1, tmp_path / "b", lambda t: t.replace('"id": ', f'"error_class": "{cls}",\n  "id": ', 1)
    )
    assert not P.blind_counts(field, sets)["blind"]
    # a value planted where the design holds another: the design must be the version's, exactly
    node = _one_packet(
        c1, tmp_path / "c", lambda t: t.replace('"domain": "', f'"domain": "{cls} ', 1)
    )
    assert not P.blind_counts(node, sets)["blind"]


def test_the_blind_check_reads_adjudicator_packets_and_their_forms(
    fx: dict[str, Any], tmp_path: Path
) -> None:
    sets = fx["setdata"]
    lines = fx["lines"][:3]
    codes = []
    for x in lines:
        for who, code, extra in (
            ("c1", "N", {"n_kind": "wording"}),
            ("c2", "D", {"d_kind": "table"}),
        ):
            form = {"id": "F1", "code": code, "defect": "d", "reason": "r", **extra}
            codes.append(
                {"step": "s", "who": who, "line_id": x["line_id"], "code": code, "form": form}
            )
    codes[0]["form"]["who_wrote_it"] = "c1"  # a key outside the schema never reaches a packet
    adj = tmp_path / "adj"
    P.build_adjudicator_packets(lines, codes, "s", sets, adj)
    assert P.blind_counts(adj, sets)["blind"]
    assert "who_wrote_it" not in "".join(p.read_text() for p in adj.glob("P*.md"))
    role, cls = _role_and_class(fx, adj)
    head = "## Findings and the two forms"
    said = f"A reviewer of the {role} domain, class {cls}.\n\n"
    bad = _one_packet(adj, tmp_path / "a", lambda t: t.replace(head, said + head, 1))
    assert not P.blind_counts(bad, sets)["blind"]
    keyed = _one_packet(
        adj, tmp_path / "b", lambda t: t.replace('{"code"', '{"who": "c1", "code"', 1)
    )
    assert not P.blind_counts(keyed, sets)["blind"]


def test_the_blind_check_lets_a_reality_packet_name_its_role_and_nothing_more(
    fx: dict[str, Any], tmp_path: Path
) -> None:
    sets = fx["setdata"]
    rp = tmp_path / "reality"
    R.build_packets(fx["lines"], sets, rp)
    assert P.blind_counts(rp, sets)["blind"]
    role, cls = _role_and_class(fx, rp)
    said = f"A reviewer of the {role} domain"
    bad = _one_packet(rp, tmp_path / "a", lambda t: t.replace(said, f"{said} (class {cls})", 1))
    res = P.blind_counts(bad, sets)
    assert not res["blind"] and any(w.endswith(f"class:{cls}") for w in res["where"])
    other = next(r for r in X.ROLES if r != role)
    wrong = _one_packet(
        rp, tmp_path / "b", lambda t: t.replace(said, f"A reviewer of the {other} domain", 1)
    )
    assert not P.blind_counts(wrong, sets)["blind"]
    field = _one_packet(
        rp, tmp_path / "c", lambda t: t.replace('"id":', f'"expected_check":"{cls}","id":', 1)
    )
    assert not P.blind_counts(field, sets)["blind"]


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


def test_the_slice_draw_on_the_fixture_is_the_one_drawn_before_the_refusals(
    fx: dict[str, Any],
) -> None:
    # pinned at d642c06, before draw() held the classes to CLASSES: the RNG's calls are unchanged
    assert SL.draw(fx["lines"], fx["setdata"]) == {
        "fresh": ["e1", "m1", "p1", "u1"],
        "practice": ["u1", "m1"],
    }


def _reclassed(sets: dict[str, X.SetData], pair: str, cls: str) -> dict[str, X.SetData]:
    out = {}
    for name, sd in sets.items():
        arts = {p: dict(a) for p, a in sd.artefacts.items()}
        arts[pair]["error_class"] = cls
        out[name] = X.SetData(sd.name, sd.seed, sd.base, arts, sd.sheet)
    return out


@pytest.mark.parametrize("cls", ["thermal", "propagations"])
def test_the_slice_refuses_classes_other_than_the_frozen_four(fx: dict[str, Any], cls: str) -> None:
    # every class still has an eligible pair, so only the frozen list can refuse the draw
    sets = _reclassed(fx["setdata"], "p1", cls)
    with pytest.raises(X.Refused, match="classes"):
        SL.draw(fx["lines"], sets)


def test_the_slice_refuses_a_draw_it_does_not_implement(
    fx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SL, "FRESH_PER_CLASS", 2)
    with pytest.raises(X.Refused, match="per class"):
        SL.draw(fx["lines"], fx["setdata"])


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
