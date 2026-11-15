"""A run that asks for no parts list writes exactly what a run wrote before one could be asked for.

The reference is a seeded run with no model in it (``off_identity_rig``): the decomposition's
prompt and schema for three sets of roles, the files a loop over stand-in sessions leaves once
it has carried two subtasks to their merges, and the store's journal and node files after three
fixed writes. Its digests were recorded from the code at 9c7e19ef, the commit this work
is based on, which holds nothing of the switch, and are kept beside this test. (First recorded
at df68ef09, an earlier base: the base has since gained a sentence on how a unit is spelt in
every prompt, which changed the three prompt digests and no other.) Recorded runs,
and the experiments that pin the decomposition's prompt and schema, stay comparable with every
run made with the switch off.

A digest that differs names the file or the text that changed.
"""

from __future__ import annotations

import json
from pathlib import Path

from off_identity_rig import reference

RECORDED = json.loads((Path(__file__).parent / "off_identity_reference.json").read_text())


def test_the_reference_covers_what_a_run_sends_and_writes() -> None:
    # A check over a collection first shows the collection is there.
    assert len(RECORDED) == 16
    assert RECORDED["run:ended"] == "done" and RECORDED["run:events"] == "42"
    assert {name.split(":")[0] for name in RECORDED} == {"prompt", "schema", "run", "store"}


def test_the_seeded_run_leaves_the_bytes_recorded_before_the_switch(tmp_path: Path) -> None:
    now = reference(tmp_path)
    changed = sorted(
        name for name in RECORDED.keys() | now.keys() if RECORDED.get(name) != now.get(name)
    )
    assert changed == []


def test_the_seeded_run_is_the_same_run_twice(tmp_path: Path) -> None:
    assert reference(tmp_path / "one") == reference(tmp_path / "two")
