"""Through the real binary: inside the OS layer no role session writes a role's tier register.

The register and the run roots lie beneath the role's withheld root, which every run on the
role withholds. The first layer refuses a command that names it; these steps build the path at
run time inside an interpreter fed a program, which the shell parser cannot see, so whatever
stops them is the OS layer. One step writes the register directly; the others run each of the
three writers with the harness's session markers taken out of their environment, as a session
can, so the writers' own refusal inside a session does not stop them either. The hand mark is
run on a terminal of the step's own making, for a version the store holds, so its terminal check
and its version check pass and only the layer is left to stop it.

Each step must show the operating system's own denial, not merely fail: a writer that failed
for another reason (an interpreter it could not run, an import that failed) proves nothing.
Without the layer the same steps write there, which shows the probe works; the sentinel puts
back what they wrote after each call, so that row reads what each step says.

In a job that is meant to have the layer (``PHYSGATE_REQUIRE_OS_LAYER`` set), a machine where
the layer cannot run fails the row instead of skipping it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "exposure"))
from exposure_fixtures import StandInStore, stand_in_store  # noqa: E402

pytestmark = pytest.mark.integration

#: What the operating system says when the layer refuses an open or a write.
DENIALS = ("Operation not permitted", "Permission denied", "Read-only file system")


@pytest.fixture
def store(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "outside" / "st")


@pytest.fixture
def layout(tmp_path: Path, store: StandInStore) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        withheld = store.store / "control" / "withheld"
        (tmp_path / "runs").mkdir()
        yield replace(made, held=withheld)


def _writers(version: str) -> tuple[tuple[str, ...], ...]:
    return (
        ("scan-exposures",),
        ("mark-exposed", "--version", version, "--by", "someone", "--reason", "two words"),
        ("add-run-root", "--path"),
    )


def _steps(layout: Layout, version: str) -> list[dict[str, object]]:
    # The withheld root is joined from pieces at run time, so the first layer cannot see it.
    joined = (
        "import os, pty, subprocess\n"
        f"w = os.path.join({str(layout.root)!r}, 'outside', 'st', 'control', 'with' + 'held')\n"
    )
    direct = joined + (
        "try:\n    open(os.path.join(w, 'register.jsonl'), 'a').write('marker'); print('wrote')\n"
        "except OSError as e:\n    print('denied:', e.strerror)\n"
    )
    # The hand mark asks for a terminal: it is given one of the step's own making.
    on_a_terminal = (
        "pid, fd = pty.fork()\n"
        "if pid == 0:\n    os.execve(argv[0], argv, env)\n"
        "out = b''\n"
        "while True:\n"
        "    try:\n        chunk = os.read(fd, 4096)\n"
        "    except OSError:\n        break\n"
        "    if not chunk:\n        break\n"
        "    out += chunk\n"
        "code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])\n"
        "print('exit', code, out.decode(errors='replace')[-600:])\n"
    )
    piped = (
        "done = subprocess.run(argv, env=env, capture_output=True, text=True)\n"
        "print('exit', done.returncode, done.stdout[-600:], done.stderr[-600:])\n"
    )
    steps: list[str] = []
    for writer in _writers(version):
        steps.append(
            joined
            + "RUN = 'import sys; from physgate.cli import main; sys.exit(main(sys.argv[1:]))'\n"
            + "env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_CODE_')}\n"
            # The harness's interpreter, which the first layer refuses by name, written reversed.
            + f"argv = [{sys.executable[::-1]!r}[::-1], '-c', RUN, 'tiers', {writer[0]!r}, "
            + f"'--withheld', w, *{writer[1:]!r}]\n"
            + (f"argv.append({str(layout.root / 'runs')!r})\n" if writer[-1] == "--path" else "")
            + (on_a_terminal if writer[0] == "mark-exposed" else piped)
        )
    steps.append(direct)
    return [tool("Bash", command=python(p), description=f"step {n}") for n, p in enumerate(steps)]


def _contents(layout: Layout) -> dict[str, bytes]:
    return {
        str(p.relative_to(layout.held)): p.read_bytes()
        for p in sorted(layout.held.rglob("*"))
        if p.is_file() and not p.name.endswith(".lock")
    }


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here; fail instead where the job is meant to have it."""
    if layer_here():
        return
    if os.environ.get("PHYSGATE_REQUIRE_OS_LAYER"):
        pytest.fail("this job is meant to run the OS layer, and the layer cannot run here")
    pytest.skip("the OS layer cannot run here")


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_step_writes_beneath_the_withheld_root(
    layout: Layout, store: StandInStore
) -> None:
    before = _contents(layout)
    run = run_session(layout, _steps(layout, store.version), layer=True)
    told = run["told"]
    assert isinstance(told, list) and len(told) == 4, told
    for step, said in zip(("scan-exposures", "mark-exposed", "add-run-root"), told, strict=False):
        text = str(said)
        assert "exit 0" not in text, f"{step} ran to its end inside the layer: {text}"
        assert "not_at_a_terminal" not in text, f"{step} was stopped by its terminal check: {text}"
        assert any(d in text for d in DENIALS), f"{step} was not stopped by the layer: {text}"
    assert "denied:" in str(told[-1]) and "wrote" not in str(told[-1]), told[-1]
    assert any(d in str(told[-1]) for d in DENIALS), told[-1]
    assert _contents(layout) == before, "a step changed what lies beneath the withheld root"


def test_without_the_layer_the_steps_write_there_which_shows_the_probe_works(
    layout: Layout, store: StandInStore
) -> None:
    # What the steps wrote is put back by the sentinel after each call, so what they say is
    # read: the scan ran to its end, the hand mark passed its terminal check and wrote its line,
    # and the direct write landed.
    run = run_session(layout, _steps(layout, store.version), layer=False)
    told = run["told"]
    assert isinstance(told, list) and len(told) == 4, told
    assert "exit 0" in str(told[0]), told
    assert "exit 0" in str(told[1]) and "marked" in str(told[1]), told
    assert "wrote" in str(told[-1]), told
