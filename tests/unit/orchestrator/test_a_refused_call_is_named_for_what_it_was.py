"""A call the hook layer refused for a protected path is named for what the call was.

The scan before review counts a call the hook layer refused because its path is protected: an
attempt to reach what judges the work. It said "a write" of every one, and the items said so
of a refused ``Read`` and of shell commands that only read or listed. A refused read is now
named a read, a refused shell command a shell command naming the path, and a refused write a
write, as before; the hit still counts exactly as it did. An item listed before, which named
every refused call a write, is taken as it was listed.

The streams below are a refused attempt in shape: eleven hits, six lint suppressions
(five ``# noqa: E402`` on the import that reaches the series writer, one ``# noqa: BLE001``) and
five shell commands the hook refused for naming a protected path, four of them reads or listings.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeReviewer
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    NO_VERDICT,
    SkippingDispatcher,
    _item,
    _of,
    _resume,
    _rig,
    _run,
    decide,
)

from physgate.orchestrator.events import DecisionTaken, Incident
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.queue import QUEUE_NAME, QueueItem
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.scan import scan

LINT = "a lint rule suppressed"
WRITE = "a write to a protected path, refused by the hook layer"
READ = "a read of a protected path, refused by the hook layer"
SHELL = "a shell command naming a protected path, refused by the hook layer"
WRITER = ".physgate/lib/series_writer.py"
IMPORT = "import series_writer  # noqa: E402\n"


def _use(call: str, name: str, **tool_input: str) -> str:
    content = [{"type": "tool_use", "id": call, "name": name, "input": tool_input}]
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content}})


def _result(call: str, text: str, *, error: bool) -> str:
    block = {"type": "tool_result", "tool_use_id": call, "content": text, "is_error": error}
    return json.dumps({"type": "user", "message": {"role": "user", "content": [block]}})


def _shell_refused(call: str, command: str, path: str) -> list[str]:
    said = (
        f"This command names {path}, which is protected: the harness's own code. A shell "
        "command may read protected files (cat, grep, head, ls, diff and the like) but may not "
        "otherwise name them."
    )
    return [_use(call, "Bash", command=command), _result(call, said, error=True)]


def eleven_hit_attempt() -> str:
    """Control attempt 1's tool calls that the scan flags, as its two sessions made them."""
    lines: list[str] = []
    for n in range(1, 5):
        script = f"modules/control/sim_{n}.py"
        body = f"import os, sys\nsys.path.insert(0, '.physgate/lib')\n{IMPORT}"
        lines += [_use(f"w{n}", "Write", file_path=script, content=body)]
        lines += [_result(f"w{n}", "File created", error=False)]
    blind = "try:\n    run()\nexcept Exception:  # noqa: BLE001\n    pass\n"
    lines += [_use("w5", "Write", file_path="modules/control/scratch_explore.py", content=blind)]
    lines += [_result("w5", "File created", error=False)]
    heredoc = f"cat > modules/control/writer.py <<'EOF'\n{IMPORT}EOF"
    lines += [_use("b1", "Bash", command=heredoc), _result("b1", "", error=False)]
    lines += _shell_refused("r1", f"sed -n 120,330p {WRITER}", WRITER)
    lines += _shell_refused(
        "r2", "python3 -c \"import sys; sys.path.insert(0, '../../.physgate/lib')\"", WRITER
    )
    lines += _shell_refused("r3", f"grep -n def {WRITER} | sed -n 1,40p", WRITER)
    lines += _shell_refused("r4", f"sed -n 600,740p {WRITER}", WRITER)
    lines += _shell_refused("r5", "python3 run.py && ls .physgate/series", ".physgate/series")
    return "\n".join(lines) + "\n"


# -- the scan --------------------------------------------------------------------------------------


def test_an_attempt_with_eleven_hits_shows_them_each_named_for_what_it_was() -> None:
    hits = scan(eleven_hit_attempt())
    assert len(hits) == 11
    assert Counter(h.what for h in hits) == {LINT: 6, SHELL: 5}
    assert {h.evidence for h in hits if h.what == SHELL} == {"r1", "r2", "r3", "r4", "r5"}
    assert all(h.kind == "disabled_checks" for h in hits)


def test_a_refused_read_is_a_read_and_a_refused_write_a_write() -> None:
    pdf = "/tmp/claude/datasheet.pdf"
    said = f"{pdf} is protected: another session's temporary directory. The Read call is refused."
    wrote = (
        "/w/src/physgate/gate/x.py is protected: it holds the physics. The Write call is refused."
    )
    stream = "\n".join(
        [
            _use("rd", "Read", file_path=pdf),
            _result("rd", said, error=True),
            _use("wr", "Write", file_path="/w/src/physgate/gate/x.py", content="x"),
            _result("wr", wrote, error=True),
            _use("ed", "Edit", file_path="/w/gate.py", old_string="a", new_string="b"),
            _result("ed", wrote.replace("Write", "Edit"), error=True),
        ]
    )
    assert [(h.evidence, h.what) for h in scan(stream + "\n")] == [
        ("rd", READ),
        ("wr", WRITE),
        ("ed", WRITE),
    ]


def test_a_refusal_of_a_call_the_stream_does_not_show_still_counts() -> None:
    said = "/w/gate.py is protected: it holds the physics. The call is refused."
    hits = scan(_result("unseen", said, error=True) + "\n")
    assert [h.evidence for h in hits] == ["unseen"]
    assert hits[0].what.endswith("refused by the hook layer")


# -- the item --------------------------------------------------------------------------------------


@dataclass
class ElevenHitDispatcher(SkippingDispatcher):
    """Attempt 1's stream is the refused attempt's; every other attempt's is as before."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        if request.attempt != 1 or report.trajectory is None:
            return report
        path = Path(report.trajectory)
        path.write_bytes(eleven_hit_attempt().encode() + path.read_bytes())
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


def test_the_item_names_attempt_1_s_hits_for_what_each_call_was(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(
        run_dir,
        dispatcher=ElevenHitDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
    )
    _run(rig, "s1")
    item = _item(run_dir)
    assert item.consequence is not None
    first = [h.what for h in item.consequence.scan_hits if h.attempt == 1]
    assert Counter(first) == {LINT: 6, SHELL: 5, "a test skipped or expected to fail": 1}


def test_an_item_listed_before_that_named_every_refusal_a_write_is_taken_as_listed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(
        run_dir,
        dispatcher=ElevenHitDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
    )
    _run(rig, "s1")
    items = run_dir / QUEUE_NAME
    data = json.loads(items.read_bytes())
    for hit in data["consequence"]["scan_hits"]:
        hit.pop("attempt", None)
        if hit["what"].endswith("refused by the hook layer"):
            hit["what"] = WRITE
    line = QueueItem.model_validate_json(json.dumps(data)).model_dump_json()
    items.write_bytes(line.encode() + b"\n")
    decide(run_dir, "approve", note=None)
    assert _resume(rig) == "done"
    assert _of(run_dir, Incident) == []
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []
