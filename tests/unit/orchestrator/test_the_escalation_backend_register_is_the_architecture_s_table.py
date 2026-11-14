"""The escalation backend register in code is the architecture's table, row by row.

ARCH-132 states the register as a table in the architecture specification: one row per backend,
its status, and the experiments its entry condition rests on. The code carries the same register
(``escalation.REGISTER``), and a run's backend flag takes its values from it. Two copies of one
table drift apart unless something holds them together, so this test reads the table from the
tracked specification and holds the code's rows to it: the same names in the same order, the
same status, and the same experiments cited.

The table words each status as prose. The mapping below states which prose reads as which of the
code's three statuses; a status the mapping does not state fails the test, so a new wording is
classed here before it can pass.
"""

from __future__ import annotations

import re
from pathlib import Path

from physgate.orchestrator import escalation

SPECIFICATION = Path(__file__).resolve().parents[3] / ".docs" / "02-architecture-specification.md"

#: The table's bold status words, and the code status each one reads as.
STATUS_OF = {
    "ships": "ships",
    "listed, off and refused": "off",
    "contingent, parked": "parked",
    "parked": "parked",
}

_EXPERIMENT = re.compile(r"\bR-[A-Z]+-[0-9]{2}\b")


def _section(text: str, decision: str) -> str:
    start = text.find(f"### {decision} ")
    assert start != -1, f"the specification has no {decision} section"
    end = text.find("\n### ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _table(section: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """Each row as (backend, status words, experiments cited, in order of first citation)."""
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        assert len(cells) == 3, f"a register row with {len(cells)} cells: {line[:60]!r}"
        name = re.fullmatch(r"`([a-z][a-z0-9_]*)`", cells[0])
        status = re.match(r"\*\*(.+?)\*\*", cells[1])
        assert name is not None, f"a register row names no backend: {cells[0]!r}"
        assert status is not None, f"the row for {name.group(1)} words no status in bold"
        cited = tuple(dict.fromkeys(_EXPERIMENT.findall(cells[2])))
        rows.append((name.group(1), status.group(1), cited))
    return rows


def _architecture_rows() -> list[tuple[str, str, tuple[str, ...]]]:
    assert SPECIFICATION.is_file(), f"the architecture specification is not at {SPECIFICATION}"
    rows = _table(_section(SPECIFICATION.read_text(encoding="utf-8"), "ARCH-132"))
    assert rows, "ARCH-132 states no register row"
    return rows


def test_every_status_the_architecture_words_is_one_the_mapping_states() -> None:
    unmapped = [(name, words) for name, words, _ in _architecture_rows() if words not in STATUS_OF]
    assert unmapped == []


def test_the_code_s_backends_are_the_architecture_s_in_its_order() -> None:
    assert [row.name for row in escalation.REGISTER.rows] == [
        name for name, _, _ in _architecture_rows()
    ]


def test_each_backend_s_status_is_the_one_the_architecture_states() -> None:
    assert {row.name: row.status for row in escalation.REGISTER.rows} == {
        name: STATUS_OF.get(words, f"unmapped: {words}") for name, words, _ in _architecture_rows()
    }


def test_each_backend_cites_the_experiments_its_architecture_row_cites() -> None:
    assert {row.name: row.evidence for row in escalation.REGISTER.rows} == {
        name: cited for name, _, cited in _architecture_rows()
    }


def test_only_the_default_backend_ships() -> None:
    # ARCH-132's acceptance: only the default is enabled by default.
    shipping = [name for name, words, _ in _architecture_rows() if STATUS_OF.get(words) == "ships"]
    assert shipping == ["rules"]
    assert [row.name for row in escalation.REGISTER.rows if row.status == "ships"] == shipping
