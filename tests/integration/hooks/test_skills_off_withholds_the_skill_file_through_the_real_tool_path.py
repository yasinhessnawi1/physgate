"""Through the real binary: under ``skills: off`` the skill file is withheld and the rest is read.

A role session of an ablation run's ``skills: off`` arm is installed with what the dispatcher gives
it under that arm: the two standards files and the module specification to read, and the role's
skill file withheld. Every attempt is a real Claude Code tool call, driven by the scripted endpoint
so no model can decline it, and judged mechanically. **Shown** is the skill file's marker appearing
in anything the session was told; **caught** is the hook layer's own log holding a refusal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.knowledge import loader

pytestmark = pytest.mark.integration

ROLE = "electrical"
SPEC = Path(".physgate/specs/e1.md")
#: A line only the skill file holds.
MARKER = "skill-marker-" + "ab" * 12
DOC = "A line of required reading.\n" * 12

FILES = {
    "knowledge/cross/standards.md": DOC,
    f"knowledge/{ROLE}/standards.md": DOC,
    f"knowledge/{ROLE}/skill.md": MARKER + "\n" + DOC,
    SPEC.as_posix(): DOC,
}
SKILL = f"knowledge/{ROLE}/skill.md"


def bash(command: str) -> dict[str, Any]:
    return tool("Bash", command=command, description="x")


def _session(root: Path, steps: list[dict[str, Any]], **fields: Any) -> SessionRun:  # noqa: ANN401
    session_reading = getattr(loader, "session_reading", None)
    assert session_reading is not None, "the loader names no session's reading by the skills switch"
    given = session_reading(ROLE, SPEC, skills="off")
    worktree = root / "worktree"
    record = root / "outside" / "run" / "run.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}\n")
    return run_session(
        root,
        Script(main=[*steps, text("end")]),
        files=FILES,
        required_reading=tuple(str(worktree / p) for p in given.required),
        always_loaded=tuple(str(worktree / p) for p in given.always_loaded),
        withheld=(str(record), *(str(worktree / p) for p in given.withheld)),
        **fields,
    )


def _reads(root: Path) -> list[dict[str, Any]]:
    """The Read calls of the files a session under the arm must read, in full."""
    worktree = root / "worktree"
    names = ("knowledge/cross/standards.md", f"knowledge/{ROLE}/standards.md", SPEC.as_posix())
    return [tool("Read", file_path=str(worktree / name)) for name in names]


def _shown(run: SessionRun) -> bool:
    return any(MARKER in request.last_user for request in run.api.requests)


def test_a_call_waits_for_the_standards_and_the_session_acts_without_the_skill_file(
    tmp_path: Path,
) -> None:
    steps = [bash("echo early > early.txt"), *_reads(tmp_path), bash("echo done > done.txt")]
    run = _session(tmp_path, steps)
    refused = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert not (run.worktree / "early.txt").exists(), "a call ran before the standards were read"
    assert [e["hook"] for e in refused] == ["reading"]
    assert (run.worktree / "done.txt").exists(), "the session waited for the withheld skill file"
    assert not _shown(run)


#: Every way a session's own tools offer to read a file, as for the run's configuration.
ATTEMPTS: list[tuple[str, dict[str, Any]]] = [
    ("read-tool", tool("Read", file_path="@S")),
    ("read-relative", tool("Read", file_path=SKILL)),
    ("cat", bash(f"cat {SKILL}")),
    ("grep", bash(f"grep -o skill-marker.* {SKILL}")),
    ("redirect", bash(f"while read -r l; do echo $l; done < {SKILL}")),
    ("heredoc", bash(f"python3 - <<'PY'\nprint(open('{SKILL}').read())\nPY")),
    ("copy-out", bash(f"cp {SKILL} leaked.md && cat leaked.md")),
]


def _place(step: dict[str, Any], skill: Path) -> dict[str, Any]:
    placed = dict(step)
    placed["input"] = {
        k: v.replace("@S", str(skill)) if isinstance(v, str) else v
        for k, v in step["input"].items()
    }
    return placed


@pytest.mark.parametrize(("name", "step"), ATTEMPTS, ids=[n for n, _ in ATTEMPTS])
def test_no_way_of_reading_shows_the_session_the_withheld_skill_file(
    tmp_path: Path, name: str, step: dict[str, Any]
) -> None:
    skill = tmp_path / "worktree" / SKILL
    run = _session(tmp_path, [*_reads(tmp_path), _place(step, skill)])
    caught = [e for e in run.hook_log if e.get("decision") == "refuse"]
    assert not _shown(run), f"{name}: the session was shown the withheld skill file"
    assert caught, f"{name}: no refusal from the hook layer is on record"
    assert not (run.worktree / "leaked.md").exists()


def test_inside_the_os_layer_a_path_built_at_run_time_does_not_read_it(tmp_path: Path) -> None:
    from os_layer_rig import layer_here

    if not layer_here():
        pytest.skip("the OS layer cannot run here")
    # The name is joined while the program runs, so no hook can see it: the sandbox alone judges.
    program = (
        f"import os\np = os.path.join('know' + 'ledge', {ROLE!r}, 'sk' + 'ill.md')\n"
        "try:\n    print(open(p).read())\nexcept OSError as e:\n    print('denied:', e.strerror)\n"
    )
    steps = [*_reads(tmp_path), bash(f"python3 - <<'PY'\n{program}PY")]
    run = _session(tmp_path, steps, os_layer=True)
    told = run.told_after(4)
    assert not _shown(run), "the sandbox let a built path read the withheld skill file"
    assert "denied:" in told, told
