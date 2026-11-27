"""Through the real binary: inside the OS layer no role session writes a role's tier register.

The register and the run roots lie beneath the role's withheld root, which every run on the
role withholds. The first layer refuses a command that names it; these steps build the path at
run time inside an interpreter fed a program, which the shell parser cannot see, so whatever
stops them is the OS layer. One step writes the register directly; the others run each of the
five writers (the register's four and the gaps vector's) with the harness's session markers
taken out of their environment, as a session can, so the writers' own refusal inside a session
does not stop them either. The hand mark and the settle are
run on a terminal of the step's own making, the hand mark for a version the store holds and the
settle for a directory beneath the run root the step before registered, whose parameters record
the step tears first, so their own checks pass and only the layer is left to stop them. The
target check is no step: it is given no withheld root and writes nothing anywhere.

What the layer does to the withheld place differs by platform, so what each step must show
does too. On macOS the layer refuses the place: each step shows the operating system's own
denial, not merely a failure, since a writer that failed for another reason (an interpreter it
could not run, an import that failed) proves nothing. On Linux the layer masks the place with an
empty directory: inside it the place lists empty and a read of a log by its known path fails,
every writer refuses because the register is missing, and a write tried there leaves the logs
outside byte-identical.

Without the layer the same probe reaches the logs: the place lists them, the log reads, and the
steps write there, the settle among them. The sentinel cannot put back a log no session may
read, so it refuses every call after the first write; each step therefore runs in a session of
its own, in both rows.

In a job that is meant to have the layer (``PHYSGATE_REQUIRE_OS_LAYER`` set), a machine where
the layer cannot run fails the row instead of skipping it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import layer_here, make_layout, python, run_session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "exposure"))
from exposure_fixtures import StandInStore, stand_in_store  # noqa: E402

pytestmark = pytest.mark.integration

#: What the operating system says when the layer refuses a listing, an open or a write (macOS);
#: a layer that hides a withheld directory leaves it absent inside the sandbox. The row without
#: the layer shows the same path is there, so absence inside is the layer's doing.
DENIALS = (
    "Operation not permitted",
    "Permission denied",
    "Read-only file system",
    "No such file or directory",
)


@pytest.fixture
def store(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "outside" / "st")


def _withheld(store: StandInStore) -> Path:
    return store.store / "control" / "withheld"


def _each_in_its_own_session(tmp_path: Path, store: StandInStore, *, layer: bool) -> list[str]:
    """What each step said, every step run in a fresh session of its own.

    A call follows each step: where the step wrote what the sentinel cannot put back, the
    session's end is refused too, and the binary's next request, with that refusal, then
    stands in for the last call's result, not for the step's.
    """
    # The settle's directory is there before any step, empty, so a scan beneath the run root
    # reads it whole; the settle's own step tears its record (where the place lets it).
    (tmp_path / "runs" / "cut").mkdir(parents=True, exist_ok=True)
    after = tool("Bash", command="true", description="after the step")
    said: list[str] = []
    for n, step in enumerate(_steps(tmp_path, store.version)):
        with make_layout(tmp_path / f"session{n}") as made:
            run = run_session(replace(made, held=_withheld(store)), [step, after], layer=layer)
        told = run["told"]
        assert isinstance(told, list) and len(told) == 2, told
        said.append(str(told[0]))
    return said


#: Each writer of the withheld place, by its command and the arguments after ``--withheld``.
STEPS = ("scan-exposures", "mark-exposed", "add-run-root", "gaps vector", "settle", "write")


def _writers(root: Path, version: str) -> tuple[tuple[str, ...], ...]:
    return (
        ("tiers", "scan-exposures"),
        ("tiers", "mark-exposed", "--version", version, "--by", "someone", "--reason", "two words"),
        ("tiers", "add-run-root", "--path"),
        # The vector writer reads the run set and the records beneath the same place.
        ("gaps", "vector", "--version", version, "--tier", "held_out"),
        # After the vector writer, which reads the run root: a torn record there would refuse it.
        ("tiers", "settle", "--directory", str(root / "runs" / "cut"), "--by", "someone")
        + ("--reason", "two words"),
    )


def _steps(root: Path, version: str) -> list[dict[str, object]]:
    # The withheld root is joined from pieces at run time, so the first layer cannot see it.
    joined = (
        "import os, pty, subprocess\n"
        f"w = os.path.join({str(root)!r}, 'outside', 'st', 'st' + 'ore', 'control', "
        "'with' + 'held')\n"
        # What the operating system itself says of the place, before any writer runs: what it
        # lists, and whether the log reads by its known path.
        "try:\n    print('probe: listed', sorted(os.listdir(w)))\n"
        "except OSError as e:\n    print('probe:', e.strerror)\n"
        "try:\n"
        "    open(os.path.join(w, 'register' + '.jsonl'), 'rb').read(1); print('read: ok')\n"
        "except OSError as e:\n    print('read:', e.strerror)\n"
    )
    direct = joined + (
        "try:\n"
        "    open(os.path.join(w, 'register' + '.jsonl'), 'a').write('marker'); print('wrote')\n"
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
    # The settle's directory refuses the register as read: its parameters record is torn.
    torn = (
        "try:\n"
        f"    open(os.path.join({str(root / 'runs' / 'cut')!r}, 'params' + '_source.json'), 'w')"
        ".write('{')\n"
        "except OSError as e:\n    print('torn:', e.strerror)\n"
    )
    steps: list[str] = []
    for writer in _writers(root, version):
        steps.append(
            joined
            + "RUN = 'import sys; from physgate.cli import main; sys.exit(main(sys.argv[1:]))'\n"
            + "env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_CODE_')}\n"
            # The harness's interpreter, which the first layer refuses by name, written reversed.
            + f"argv = [{sys.executable[::-1]!r}[::-1], '-c', RUN, *{writer[:2]!r}, "
            + f"'--withheld', w, *{writer[2:]!r}]\n"
            + (f"argv.append({str(root / 'runs')!r})\n" if writer[-1] == "--path" else "")
            + (
                "argv += ['--runs', os.path.join(w, 'r.json'), '--trials', os.path.join(w, 't')]\n"
                if writer[0] == "gaps"
                else ""
            )
            + (torn if writer[1] == "settle" else "")
            + (on_a_terminal if writer[1] in ("mark-exposed", "settle") else piped)
        )
    steps.append(direct)
    return [tool("Bash", command=python(p), description=f"step {n}") for n, p in enumerate(steps)]


def _contents(withheld: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(withheld)): p.read_bytes()
        for p in sorted(withheld.rglob("*"))
        if p.is_file() and not p.name.endswith(".lock")
    }


def _line(text: str, label: str) -> str:
    return text.split(f"{label}:", 1)[-1].splitlines()[0].strip()


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
    tmp_path: Path, store: StandInStore
) -> None:
    withheld = _withheld(store)
    before = _contents(withheld)
    assert "register.jsonl" in before, before
    told = _each_in_its_own_session(tmp_path, store, layer=True)
    assert len(told) == len(STEPS), told
    masked = sys.platform.startswith("linux")
    for step, text in zip(STEPS, told, strict=True):
        probe, read = _line(text, "probe"), _line(text, "read")
        if masked:
            # The layer masks the place: it lists empty, and the log does not read.
            assert probe == "listed []", f"the layer did not mask {step}'s place: {text}"
            assert read != "ok" and read, f"the log read inside the layer at {step}: {text}"
        else:
            assert any(d in probe for d in DENIALS), (
                f"the layer did not deny {step}'s place: {text}"
            )
        if step == "write":
            # On Linux a write there lands in the mask, if anywhere: the logs outside are
            # compared below.
            if not masked:
                assert "denied:" in text and "wrote" not in text, text
                assert any(d in _line(text, "denied") for d in DENIALS), text
            continue
        assert "exit 0" not in text, f"{step} ran to its end inside the layer: {text}"
        assert "not_at_a_terminal" not in text, f"{step} was stopped by its terminal check: {text}"
        if masked:
            assert "register_missing" in text, f"{step} did not refuse a missing register: {text}"
    assert _contents(withheld) == before, "a step changed what lies beneath the withheld root"


def test_without_the_layer_the_steps_write_there_which_shows_the_probe_works(
    tmp_path: Path, store: StandInStore
) -> None:
    # Each step reaches the logs: the place lists them and the log reads. The scan ran to its
    # end, the hand mark passed its terminal check and wrote its line, the vector writer read
    # that line, the settle wrote its line for the directory its step tore, and the direct write
    # landed; the sentinel could not put back a log no session may read, which is why each step
    # had a session of its own.
    withheld = _withheld(store)
    before = _contents(withheld)
    told = _each_in_its_own_session(tmp_path, store, layer=False)
    assert len(told) == len(STEPS), told
    for text in told:
        assert "register.jsonl" in _line(text, "probe"), text
        assert _line(text, "read") == "ok", text
    assert "exit 0" in told[0], told
    assert "exit 0" in told[1] and "marked" in told[1], told
    # The vector writer reads the register before it opens its inputs, so its refusal here is
    # the version the hand mark (two steps before) marked exposed: it read the register whole.
    # Inside the layer the same read is what refuses it as missing (Linux).
    assert STEPS[3] == "gaps vector" and "version_exposed" in told[3], told
    assert STEPS[4] == "settle" and "exit 0" in told[4] and "settled" in told[4], told
    assert "wrote" in told[-1], told
    assert _contents(withheld)["register.jsonl"] != before["register.jsonl"], told
