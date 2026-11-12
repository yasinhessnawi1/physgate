"""The operator interface names every extractor, and the loop's two traces, as the harness does.

A graph quantity read off a simulation record names its extractor; the Simulation screen says
each one in words, and draws a loop's frequency response from the two traces the harness's own
extractors read. Both lists are held here to the harness's, so an extractor it gains, or a trace
it renames, turns this red until the screen can say it in words and draw it.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

from physgate.series.extract import MAGNITUDE_TRACE, PHASE_TRACE
from physgate.state.schema import Extractor

ROOT = Path(__file__).resolve().parents[3]
SERIES = ROOT / "ui" / "src" / "api" / "series.ts"
WORDS = ROOT / "ui" / "src" / "words" / "series.ts"


def test_the_interface_s_extractors_are_the_schema_s() -> None:
    text = SERIES.read_text()
    listed = re.search(r"export const EXTRACTORS = \[(.*?)\] as const;", text, re.DOTALL)
    assert listed is not None
    assert re.findall(r'"([a-z_]+)"', listed.group(1)) == list(typing.get_args(Extractor))


def test_the_interface_says_every_extractor_in_words() -> None:
    words = WORDS.read_text()
    table = re.search(
        r"export const EXTRACTOR_WORDS: Readonly<Record<Extractor, string>> = \{(.*?)\};",
        words,
        re.DOTALL,
    )
    assert table is not None
    named = re.findall(r'\n  ([a-z_]+): "([^"]+)",', table.group(1))
    assert [name for name, _ in named] == list(typing.get_args(Extractor))
    assert all(said.strip() for _, said in named)


def test_the_interface_draws_the_loop_from_the_harness_s_two_traces() -> None:
    text = SERIES.read_text()
    assert f'export const LOOP_MAGNITUDE = "{MAGNITUDE_TRACE}";' in text
    assert f'export const LOOP_PHASE = "{PHASE_TRACE}";' in text
