"""The decomposition prompt names every law the gate loads, generated from its law table.

A law is judged only where the nodes and their ``constrains`` edges form it, by exact catalogue
names, as a relation is. So the prompt that asks for a plan names each law the gate holds: its
id, its statement, and the names it reads and where, generated from the table the gate loads,
never copied by hand. A law the table holds that the prompt does not name fails a test here,
for a table of the tests' own, for the table in this checkout, and for every law card staged
for promotion, promoted in a temporary library.

With no law in the table the prompt has no law sentence and is sent byte for byte as before;
with laws it gains that one paragraph, after the relations', and nothing else.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import test_without_the_cross_cutting_roles_the_decomposition_is_sent_as_before as before
from law_rows import sound_law, toml_value

from physgate.gate import laws
from physgate.knowledge import law_promotion
from physgate.knowledge.promote import PromotionError
from physgate.orchestrator import decompose

BRIEF = "Build a robot."
ROOT = Path(__file__).resolve().parents[3]
ON = datetime.date(2026, 11, 6)


def laws_sentence() -> str:
    """The prompt's law sentence for the table the gate loads, or a failed test."""
    found = getattr(decompose, "laws_sentence", None)
    if found is None:
        pytest.fail("the decomposition prompt has no sentence naming the gate's laws yet")
    sentence: str = found()
    return sentence


def _symbols(**places: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {s: {"name": name, "place": place} for s, (name, place) in places.items()}


def _example(outcome: str, **values: Any) -> dict[str, Any]:
    def one(value: Any) -> Any:
        if isinstance(value, list):
            return [one(v) for v in value]
        number, unit = value
        return {"value": number, "unit": unit}

    return {
        "outcome": outcome,
        "source": "the test's own numbers",
        "values": {k: one(v) for k, v in values.items()},
    }


#: One law of each pattern, the tests' own: a members law, a node law and an edge law, written
#: out of id order, so the sentence's order is its own.
TEST_LAWS = (
    sound_law(
        "reaction_moment_sum",
        statement="a carrier reacts the sum of the moments of the units it carries",
        expression="M == T",
        pattern="members",
        anchor="M",
        symbols=_symbols(M=("reaction_moment", "subject"), T=("reaction_moment", "each")),
        example=[
            _example("pass", M=(3, "N*m"), T=[(1, "N*m"), (2, "N*m")]),
            _example("fail", M=(4, "N*m"), T=[(1, "N*m"), (2, "N*m")]),
        ],
    ),
    sound_law(),
    sound_law(
        "rate_throughput",
        statement="a consumer is updated no faster than its producer delivers",
        expression="U <= R",
        pattern="edge",
        anchor="U",
        tolerance="inequality",
        symbols=_symbols(U=("update_rate", "self"), R=("output_data_rate", "target")),
        example=[
            _example("pass", U=(100, "Hz"), R=(200, "Hz")),
            _example("fail", U=(400, "Hz"), R=(200, "Hz")),
        ],
    ),
)

#: The law sentence for ``TEST_LAWS``, word for word: each law in id order, the names it reads
#: listed at each place its pattern binds them.
TEST_LAWS_SENTENCE = (
    "The gate also judges these laws, each only where the nodes and their constrains edges form "
    "it and only under these exact names: "
    "`electrical_power`: the power a node draws is its supply voltage times the current it "
    "draws, reading `power_draw`, `supply_voltage` and `current_draw` on one node; "
    "`rate_throughput`: a consumer is updated no faster than its producer delivers, reading "
    "`update_rate` on one node and `output_data_rate` on the node its constrains edge names; "
    "`reaction_moment_sum`: a carrier reacts the sum of the moments of the units it carries, "
    "reading `reaction_moment` on one node and `reaction_moment` on each node whose constrains "
    "edge names it. A law the nodes do not form is not judged."
)


def _table_text(rows: tuple[dict[str, Any], ...]) -> str:
    lines = ["# the law table", "[meta]", "format = 1", ""]
    for row in rows:
        lines.append("[[law]]")
        lines.extend(f"{key} = {toml_value(value)}" for key, value in row.items())
        lines.append("")
    return "\n".join(lines)


def _lines(rows: tuple[dict[str, Any], ...]) -> str:
    return "".join(
        json.dumps(
            {
                "candidate_id": row["approved"]["candidate_id"],
                "kind": "law",
                "law_id": row["id"],
                "promoted": "2026-11-06T12:00:00Z",
                "promoted_by": "a person",
            },
            sort_keys=True,
        )
        + "\n"
        for row in rows
    )


@pytest.fixture
def gate_loads(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path, Path], laws.LawTable]:
    """Point the table every caller that names none loads at ``table`` and ``record``."""

    def point(table: Path, record: Path) -> laws.LawTable:
        monkeypatch.setattr(laws, "LAWS_PATH", table)
        monkeypatch.setattr(laws, "PROMOTIONS_PATH", record)
        return laws.load_laws()

    return point


@pytest.fixture
def table_of(
    tmp_path: Path, gate_loads: Callable[[Path, Path], laws.LawTable]
) -> Callable[[tuple[dict[str, Any], ...]], laws.LawTable]:
    """Write ``rows`` as the table the gate loads, with their promotion lines; return it loaded."""

    def write(rows: tuple[dict[str, Any], ...]) -> laws.LawTable:
        where = tmp_path / f"table-{len(rows)}"
        where.mkdir()
        (where / "laws.toml").write_text(_table_text(rows), encoding="utf-8")
        (where / "promotions.jsonl").write_text(_lines(rows), encoding="utf-8")
        return gate_loads(where / "laws.toml", where / "promotions.jsonl")

    return write


def _named(sentence: str, law: laws.Law) -> None:
    """``law`` is named in ``sentence`` by its id, its statement and every name it reads."""
    assert f"`{law.id}`" in sentence, law.id
    assert law.statement in sentence, law.id
    for symbol in law.symbols.values():
        assert f"`{symbol.name}`" in sentence, (law.id, symbol.name)


@pytest.mark.parametrize("run_roles", sorted(before.PROMPT_SHA256), ids=", ".join)
def test_with_no_law_the_prompt_has_no_law_sentence_and_is_sent_as_before(
    run_roles: tuple[str, ...],
    table_of: Callable[[tuple[dict[str, Any], ...]], laws.LawTable],
) -> None:
    assert not table_of(()).laws
    assert laws_sentence() == ""
    prompt = decompose.prompt_for(BRIEF, run_roles)
    assert hashlib.sha256(prompt.encode()).hexdigest() == before.PROMPT_SHA256[run_roles]


def test_every_law_in_the_table_is_named_with_its_statement_and_the_names_it_reads(
    table_of: Callable[[tuple[dict[str, Any], ...]], laws.LawTable],
) -> None:
    table = table_of(TEST_LAWS)
    assert len(table.laws) == len(TEST_LAWS)
    assert list(table.laws) != sorted(table.laws)
    sentence = laws_sentence()
    for law in table.laws.values():
        _named(sentence, law)
    # Where each pattern reads its names, in id order, each law once.
    assert sentence == TEST_LAWS_SENTENCE


@pytest.mark.parametrize("run_roles", sorted(before.PROMPT_SHA256), ids=", ".join)
def test_the_law_sentence_follows_the_relations_and_is_the_one_paragraph_added(
    run_roles: tuple[str, ...],
    table_of: Callable[[tuple[dict[str, Any], ...]], laws.LawTable],
) -> None:
    table_of(())
    without = decompose.prompt_for(BRIEF, run_roles).split("\n\n")
    table_of(TEST_LAWS)
    sentence = laws_sentence()
    assert sentence
    relations = without.index(decompose.relations_sentence())
    expected = [*without[: relations + 1], sentence, *without[relations + 1 :]]
    assert decompose.prompt_for(BRIEF, run_roles).split("\n\n") == expected


@pytest.mark.parametrize("run_roles", sorted(before.PROMPT_SHA256), ids=", ".join)
def test_every_law_this_checkout_s_gate_loads_is_named_in_its_prompt(
    run_roles: tuple[str, ...],
) -> None:
    table = laws.load_laws()
    sentence = laws_sentence()
    prompt = decompose.prompt_for(BRIEF, run_roles)
    if not table.laws:
        assert sentence == ""
        return
    assert prompt.split("\n\n").count(sentence) == 1
    for law in table.laws.values():
        _named(sentence, law)


@pytest.fixture
def staged_library(tmp_path: Path) -> Iterator[Mapping[str, Path]]:
    """A temporary copy of this checkout's law table, record and staged law cards."""
    knowledge = tmp_path / "knowledge"
    (knowledge / "laws").mkdir(parents=True)
    shutil.copyfile(ROOT / "knowledge" / "laws" / "laws.toml", knowledge / "laws" / "laws.toml")
    shutil.copyfile(ROOT / "knowledge" / "promotions.jsonl", knowledge / "promotions.jsonl")
    staging = tmp_path / "staging"
    (staging / "laws").mkdir(parents=True)
    for card in sorted((ROOT / "knowledge" / "staging" / "laws").glob("*.toml")):
        shutil.copyfile(card, staging / "laws" / card.name)
    yield {
        "staging_root": staging,
        "knowledge_root": knowledge,
        "promotions_path": knowledge / "promotions.jsonl",
    }


def test_every_staged_law_card_once_promoted_is_named_in_the_prompt(
    staged_library: Mapping[str, Path],
    gate_loads: Callable[[Path, Path], laws.LawTable],
) -> None:
    # The cards a person may promote next, promoted here in a temporary library by the
    # promotion's own write step, one by one: after each, every law promoted so far is named.
    staged = sorted(p.stem for p in (staged_library["staging_root"] / "laws").glob("*.toml"))
    promoted: list[str] = []
    for candidate_id in staged:
        try:
            law_promotion._apply_law(
                candidate_id, by="a person", on=ON, notice=None, **staged_library
            )
        except PromotionError as exc:
            raise AssertionError(f"the staged card {candidate_id} was refused: {exc}") from None
        table = gate_loads(
            staged_library["knowledge_root"] / "laws" / "laws.toml",
            staged_library["promotions_path"],
        )
        promoted.extend(
            law.id for law in table.laws.values() if law.approved.candidate_id == candidate_id
        )
        sentence = laws_sentence()
        assert (
            decompose.prompt_for(BRIEF, ["control", "firmware"]).split("\n\n").count(sentence) == 1
        )
        for law_id in promoted:
            _named(sentence, table.laws[law_id])
            assert table.laws[law_id].status == "warn"
    assert len(promoted) == len(staged)
