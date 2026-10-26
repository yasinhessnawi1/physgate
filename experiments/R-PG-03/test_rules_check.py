"""Tests of rules_check.py (§2.5 item 4): every rule, the listing, the template and the copies.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

Every design and sheet here is invented.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import rules_check as rc  # noqa: E402

URL = "https://example.invalid/part"
ROWS = {
    "R4.04": {
        "quantity": "absolute maximum supply voltage",
        "value": None,
        "unit": None,
        "url": URL,
        "given": "-0.3 to 12 V",
    },
    "R7.09": {"quantity": "supply voltage, abs max", "value": 6, "unit": "V", "url": URL},
    "R7.03": {"quantity": "supply voltage, recommended", "value": 5, "unit": "V", "url": URL},
    "R1.19": {"quantity": "current at peak efficiency", "value": 0.4, "unit": "A", "url": URL},
    "R1.21": {"quantity": "stall current", "value": 1.6, "unit": "A", "url": URL},
}


def sheet() -> rc.Sheet:
    return rc.Sheet(json.dumps({"label": "an invented sheet", "rows": ROWS}).encode())


def node(nid: str, kind: str = "component", **quantities: tuple[float, str, str]) -> dict[str, Any]:
    return {
        "id": nid,
        "kind": kind,
        "quantities": {
            n: {"value": v, "unit": u, "source": s, "written_by": "electrical"}
            for n, (v, u, s) in quantities.items()
        },
    }


def named(nid: str, name: str, quantity: tuple[float, str, str]) -> dict[str, Any]:
    """A node with one quantity whose name is given as a value."""
    payload = node(nid)
    v, u, s = quantity
    payload["quantities"][name] = {"value": v, "unit": u, "source": s, "written_by": "electrical"}
    return payload


def design(tmp: Path, base: list[dict[str, Any]], *revisions: list[dict[str, Any]]) -> Path:
    (tmp / "clean").mkdir(parents=True)
    (tmp / "base.json").write_text(json.dumps({"label": "x", "nodes": base}))
    for k, nodes in enumerate(revisions, 1):
        rid = f"a{k:02d}"
        (tmp / "clean" / f"{rid}.json").write_text(
            json.dumps(
                {
                    "id": rid,
                    "assigned_role": "electrical",
                    "summary": "s",
                    "clean": {"nodes": nodes},
                }
            )
        )
    return tmp


BASE = [node("electrical.motor", stall_current=(1.6, "A", URL), supply=(5, "V", URL))]


def test_rule_3_a_revision_s_node_that_lacks_a_quantity_of_the_base_s_node(tmp_path: Path) -> None:
    d = design(tmp_path, BASE, [node("electrical.motor", supply=(5, "V", URL))])
    got = rc.check(d, ["a01"], sheet())
    assert [(f["check"], f["node"], f["quantity"]) for f in got["facts"]] == [
        ("rule 3", "electrical.motor", "stall_current")
    ]


def test_a_revision_that_keeps_every_quantity_and_adds_one_holds(tmp_path: Path) -> None:
    rev = node(
        "electrical.motor", stall_current=(1.6, "A", URL), supply=(5, "V", URL), extra=(1, "W", URL)
    )
    assert rc.check(design(tmp_path, BASE, [rev]), ["a01"], sheet())["facts"] == []


def test_rule_2_by_arithmetic_and_by_the_url_and_the_number(tmp_path: Path) -> None:
    rev = node(
        "electrical.mcu",
        voltage_margin=(1, "V", "derived: [R7.09] - [R7.03]"),
        supply_cap=(6, "V", URL),
        supply=(5, "V", URL),
    )
    got = rc.check(design(tmp_path, BASE, [rev]), ["a01"], sheet())["facts"]
    assert sorted((f["check"], f["quantity"]) for f in got) == [
        ("rule 2", "supply_cap"),
        ("rule 2", "voltage_margin"),
    ]


def test_a_number_at_the_url_that_is_another_row_s_does_not_cite_the_abs_max_row(
    tmp_path: Path,
) -> None:
    rev = node("electrical.mcu", supply=(5, "V", URL), tiny=(5.02, "V", URL))
    got = rc.check(design(tmp_path, BASE, [rev]), ["a01"], sheet())["facts"]
    assert got == []


def test_rule_2_holds_on_the_base_too(tmp_path: Path) -> None:
    base = [node("electrical.mcu", margin=(1, "V", "derived: [R7.09] - [R7.03]"))]
    got = rc.check(design(tmp_path, base), [], sheet())["facts"]
    assert [(f["check"], f["place"]) for f in got] == [("rule 2", "base.json")]


@pytest.mark.parametrize(
    "name", ["current_limit", "max_current", "current_max", "rated_current", "current_rating"]
)
def test_rule_5_a_limit_named_so_that_cites_an_operating_point(tmp_path: Path, name: str) -> None:
    rev = named("electrical.driver", name, (0.4, "A", URL))
    got = rc.check(design(tmp_path, BASE, [rev]), ["a01"], sheet())["facts"]
    assert [(f["check"], f["quantity"]) for f in got] == [("rule 5", name)]


@pytest.mark.parametrize(
    ("name", "value"),
    [("efficient_current", 0.4), ("current_limit", 1.6), ("min_current", 0.4)],
    ids=["not-a-limit-name", "not-a-listed-row", "a-minimum-is-not-a-limit-for-rule-5"],
)
def test_rule_5_holds_otherwise(tmp_path: Path, name: str, value: float) -> None:
    rev = named("electrical.driver", name, (value, "A", URL))
    assert rc.check(design(tmp_path, BASE, [rev]), ["a01"], sheet())["facts"] == []


def test_every_rule_5_row_and_rule_2_row_is_the_criteria_s() -> None:
    assert rc.ABS_MAX_ROWS == ("R4.04", "R4.07", "R6.06", "R7.09")
    assert len(rc.TYPICAL_ROWS) == len(set(rc.TYPICAL_ROWS)) == 18
    assert rc.TYPICAL_ROWS[:5] == ("R1.16", "R1.17", "R1.18", "R1.19", "R1.20")


def test_rule_4_lists_every_requirement_change_and_every_limit_change_old_and_new(
    tmp_path: Path,
) -> None:
    base = [
        node("electrical.motor", stall_current=(1.6, "A", URL)),
        node("cross.req", kind="requirement", min_margin=(1, "V", URL)),
    ]
    rev = [
        node("electrical.motor", stall_current=(1.6, "A", URL), current_limit=(2, "A", URL)),
        node("cross.req", kind="requirement", min_margin=(0.5, "V", URL)),
    ]
    got = rc.check(design(tmp_path, base, rev), ["a01"], sheet())
    assert got["listed"]["requirement_changes"] == [
        {"place": "clean/a01.json", "node": "cross.req", "new": False}
    ]
    changes = {
        (c["node"], c["quantity"]): (c["old"], c["new"]) for c in got["listed"]["limit_changes"]
    }
    assert changes == {
        ("electrical.motor", "current_limit"): (None, {"value": 2, "unit": "A"}),
        ("cross.req", "min_margin"): ({"value": 1, "unit": "V"}, {"value": 0.5, "unit": "V"}),
    }
    assert got["facts"] == []  # listed, never returned


def test_the_message_is_appendix_b_s_template_with_one_line_per_fact() -> None:
    f = rc.fact("rule 3", "clean/a01.json", "electrical.motor", "stall_current", "it is gone")
    text = rc.message([f, f])
    lines = text.split("\n")
    assert lines[0] == "The design was checked. These facts need a change before the next check:"
    assert (
        lines[1]
        == lines[2]
        == "- rule 3 (clean/a01.json); node electrical.motor; quantity stall_current: it is gone"
    )
    assert lines[3] == (
        "Change only what these facts need, and keep every rule of `rules.md`. Then add one line "
        "to "
        "`done.md` saying the facts are answered, and stop."
    )
    assert text.endswith("\n") and len(lines) == 5


def test_the_template_is_the_criteria_s_words() -> None:
    text = (HERE / "CRITERIA.md").read_text().replace("\n> ", "\n")
    crit = " ".join(text.split())
    assert rc.TEMPLATE_HEAD in crit
    assert " ".join(rc.TEMPLATE_TAIL.split()) in crit


def test_a_passed_copy_changed_gone_or_behind_a_symlink_is_found(tmp_path: Path) -> None:
    d = design(tmp_path / "d", BASE, BASE)
    record = {
        "base.json": common.sha256_file(d / "base.json"),
        "clean/a01.json": common.sha256_file(d / "clean" / "a01.json"),
    }
    assert rc.copies(d, record)["holds"]
    (d / "clean" / "a01.json").write_text("{}")
    assert rc.copies(d, record)["changed"] == ["clean/a01.json"]
    (d / "clean" / "a01.json").unlink()
    assert rc.copies(d, record)["gone"] == ["clean/a01.json"]
    outside = tmp_path / "outside.json"
    outside.write_text((d / "base.json").read_text())
    (d / "base.json").unlink()
    os.symlink(outside, d / "base.json")
    assert rc.copies(d, record)["gone"] == ["base.json", "clean/a01.json"]


def test_the_cli_writes_the_facts_and_the_message_and_prints_counts_only(tmp_path: Path) -> None:
    d = design(tmp_path / "d", BASE, [node("electrical.motor", supply=(5, "V", URL))])
    s = tmp_path / "sheet.json"
    s.write_text(json.dumps({"label": "x", "rows": ROWS}))
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "rules_check.py"),
            "check",
            "--dir",
            str(d),
            "--sheet",
            str(s),
            "--ids",
            "a01",
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=common.REPO,
    )
    assert done.returncode == 1
    printed = json.loads(done.stdout)
    assert printed["facts"]["rule 3"] == 1 and "stall_current" not in done.stdout
    assert (tmp_path / "out" / "message.txt").read_text().startswith("The design was checked.")
