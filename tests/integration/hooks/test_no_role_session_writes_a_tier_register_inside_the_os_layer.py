"""Through the real binary: inside the OS layer no role session writes a role's tier register.

The register and the run roots lie beneath the role's withheld root, which every run on the
role withholds. The first layer refuses a command that names it; these steps build the path at
run time inside an interpreter fed a program, which the shell parser cannot see, so whatever
stops them is the OS layer. One step writes the register directly; the others run each of the
three writers with the harness's session markers taken out of their environment, as a session
can, so the writers' own refusal inside a session does not stop them either.

Without the layer the same steps write there, which shows the probe works; the sentinel puts
back what they wrote after each call, so that row reads what each step says.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

pytestmark = pytest.mark.integration

WRITERS = (
    ("scan-exposures",),
    ("mark-exposed", "--version", "0" * 64, "--by", "someone", "--reason", "two words"),
    ("add-run-root", "--path"),
)


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        withheld = tmp_path / "outside" / "store" / "control" / "withheld"
        withheld.mkdir(parents=True)
        (tmp_path / "runs").mkdir()
        yield replace(made, held=withheld)


def _steps(layout: Layout) -> list[dict[str, object]]:
    # The withheld root is joined from pieces at run time, so the first layer cannot see it.
    joined = (
        "import os, subprocess\n"
        f"w = os.path.join({str(layout.root)!r}, 'outside', 'st' + 'ore', 'control', "
        "'with' + 'held')\n"
    )
    direct = joined + (
        "try:\n    open(os.path.join(w, 'register.jsonl'), 'a').write('marker'); print('wrote')\n"
        "except OSError as e:\n    print('denied:', e.strerror)\n"
    )
    steps: list[str] = []
    for writer in WRITERS:
        steps.append(
            joined
            + "env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_CODE_')}\n"
            # The harness's interpreter, which the first layer refuses by name, written reversed.
            + f"argv = [{sys.executable[::-1]!r}[::-1], '-m', 'physgate', 'tiers', {writer[0]!r}, "
            + f"'--withheld', w, *{writer[1:]!r}]\n"
            + (f"argv.append({str(layout.root / 'runs')!r})\n" if writer[-1] == "--path" else "")
            + "done = subprocess.run(argv, env=env, capture_output=True, text=True)\n"
            + "print('exit', done.returncode, done.stdout[-300:], done.stderr[-300:])\n"
        )
    steps.append(direct)
    return [tool("Bash", command=python(p), description=f"step {n}") for n, p in enumerate(steps)]


def _written(layout: Layout) -> list[str]:
    return sorted(p.name for p in layout.held.iterdir())


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here (judged when the test runs, not at collection)."""
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.mark.usefixtures("layer")
def test_inside_the_layer_no_step_writes_beneath_the_withheld_root(layout: Layout) -> None:
    run = run_session(layout, _steps(layout), layer=True)
    told = run["told"]
    assert isinstance(told, list) and len(told) == 1 + len(WRITERS)
    assert "denied:" in told[-1] and "wrote" not in told[-1], told[-1]
    assert "exit 0" not in told[0] and "exit 0" not in told[2], told
    assert _written(layout) == [], _written(layout)


def test_without_the_layer_the_steps_write_there_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    # What the steps wrote is put back by the sentinel after each call, so what they say is
    # read: the direct write landed, and the scan ran to its end and wrote its head.
    run = run_session(layout, _steps(layout), layer=False)
    told = run["told"]
    assert isinstance(told, list) and len(told) == 1 + len(WRITERS), told
    assert "wrote" in told[-1], told
    assert "exit 0" in told[0], told
