"""The queue route reads each open item's trajectories through the allowlist, as the item view does.

The listing names each open item's digest and trajectory statuses, so it reads the streams the
item links. The route hands it the allowlist's own reader: a stream replaced by a link (to a copy
of its sealed bytes outside every root, or into the held-out tier) is refused before it is
opened, and reads as tampered; the target is never opened.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from ui_rig import RECORDER, context_over, escalated_run, fake_ui, serving

from physgate.orchestrator.queue import read_queue

RUN = "run-esc"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"run": escalated_run(base, RUN), "ui": fake_ui(base / "checkout")}


@pytest.mark.parametrize("toward", ["outside every root", "held-out tier"])
def test_a_stream_linked_out_of_the_run_is_never_opened_and_reads_as_tampered(
    built: dict[str, Path], tmp_path: Path, toward: str
) -> None:
    root = tmp_path / "root"
    shutil.copytree(
        built["run"], root / RUN, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    run_dir = root / RUN
    stream = Path(read_queue(run_dir).items[0].trajectories[0])
    stream = run_dir / "sessions" / stream.parent.name / stream.name
    held = tmp_path / "held"
    place = held if toward == "held-out tier" else tmp_path / "outside"
    place.mkdir()
    target = place / "stdout.jsonl"
    target.write_bytes(stream.read_bytes())  # the sealed bytes: a reader that follows says "holds"
    stream.unlink()
    stream.symlink_to(target)
    context = context_over(root, ui_root=built["ui"], held_out=(str(held),))
    with serving(context) as live, RECORDER.recording():
        listing = live.json(f"/api/runs/0/{RUN}/queue")
    assert isinstance(listing, dict)
    assert listing["open"][0]["trajectory_statuses"][0] == "tampered"
    real = str(target.resolve())
    assert [p for p in RECORDER.opened if str(Path(p).resolve()) == real] == []
