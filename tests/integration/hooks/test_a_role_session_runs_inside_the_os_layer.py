"""Through the real binary: a role session installed with the OS layer runs its shell inside it.

The session is installed as the dispatcher installs one where the OS layer runs:
its settings come from the hook installer, with the sandbox generated from the
session's configuration, and the session starts with the generated arguments
and environment, its own temporary directory included. Its worktree is a linked
worktree of a run repository, as a role session's is.

Every command here gets past the first layer: each builds its path at run time
inside an interpreter fed a program, the residual the shell parser cannot see.
So whatever stops it is the OS layer. Every write is the word ``marker``, every
read aims at a stand-in file holding a marker string.

Where the layer cannot run on this machine, the tests that need it are skipped,
and the one that needs its absence runs: a session told the layer is required
refuses to start, and the session's end says why.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import MARKER, Layout, layer_here, make_layout, python, run_session

from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.queue import read_queue
from physgate.oslayer.placement import machine_writable, placement_refusal
from physgate.oslayer.probe import shared_temp_dirs
from physgate.series.collect import writer_source

pytestmark = pytest.mark.integration


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here (judged when the test runs, not at collection)."""
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def no_layer() -> None:
    """Skip unless this is Linux and the OS layer cannot run here."""
    if sys.platform != "linux":
        pytest.skip("only Linux can lack the layer's programs")
    if layer_here():
        pytest.skip("the OS layer runs here, so it cannot be missing")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


def _steps(layout: Layout) -> list[dict[str, object]]:
    # Only the test's own root is written literally; every protected path is joined at
    # run time from pieces, so the first layer cannot see it in the program's text.
    root = str(layout.root)
    attempt = (
        "import os\nroot = {root!r}\np = os.path.join(root, *{parts!r})\n"
        "try:\n    {action}\nexcept OSError as e:\n    print('denied:', e.strerror)\n"
    )
    write = "open(p, 'a').write('marker'); print('wrote')"
    targets = [
        (("outside", "held" + "out", "stand.txt"), "print(open(p).read())"),
        (("run", "queue_" + "decisions.jsonl"), write),
        (("run", "repo", ".g" + "it", "probe-marker"), write),
        (("outside", "pl" + "ain"), write),
    ]
    programs = [attempt.format(root=root, parts=parts, action=action) for parts, action in targets]
    programs += [
        "open('made' + '.txt', 'w').write('marker'); print('wrote-worktree')",
        "import os\nd = os.environ['TMPDIR']\n"
        "open(os.path.join(d, 't'), 'w').write('marker'); print('TMPDIR=' + d)",
    ]
    return [
        tool("Bash", command=python(p), description=f"step {n}") for n, p in enumerate(programs)
    ]


#: The residual forms the shell parser leaves to this layer (its own list of what parsing
#: cannot see), each reading the held-out stand-in through a path built at run time:
#: an interpreter fed a program, a link, a shell handed the path, xargs, a sourced file, the
#: directory after ``cd $(...)``, a second name, and a program opening a path it is given.
RESIDUAL_READS = {
    "sqlite3-import": (
        "command -v sqlite3 >/dev/null || {{ echo no-sqlite3; exit 0; }}; "
        'sqlite3 :memory: "create table t(a)" ".import ${{d}}/stand.txt t" "select * from t"'
    ),
    "symlink": 'ln -s "${{d}}/stand.txt" lnk && cat lnk; rm -f lnk',
    # A shell fed by pipe is refused by the first layer now; a shell handed the path as
    # an argument is not, since a positional parameter is the first layer's residual.
    "shell-argument": 'sh -c \'cat "$1"\' _ "${{d}}/stand.txt"',
    "xargs": "printf '%s/stand.txt' \"$d\" | xargs cat",
    "sourced-file": "printf 'cat %s/stand.txt\\n' \"$d\" > s.sh; . ./s.sh; rm -f s.sh",
    "cd-substitution": 'cd "$(printf %s "$d")" && cat stand.txt',
    "hard-link": 'ln "${{d}}/stand.txt" hl && cat hl; rm -f hl',
    "awk": "awk '{{print}}' \"${{d}}/stand.txt\"",
}


def _residual(layout: Layout) -> list[dict[str, object]]:
    held = f"d=$(printf %s {layout.root}/outside/held)out; "
    return [
        tool("Bash", command=held + form.format(), description=name)
        for name, form in RESIDUAL_READS.items()
    ]


def test_a_layout_lies_outside_every_place_the_os_layer_makes_writable(layout: Layout) -> None:
    # Inside one, its sessions would share the sandbox's placeholders with every other
    # session there, and abort each other's commands.
    for place in (layout.root, layout.worktree):
        assert placement_refusal(place, machine_writable()) is None, place


def test_a_step_told_bubblewrap_s_own_words_fails_the_test(layout: Layout) -> None:
    # An aborted command never ran, so a refusal test must not pass on it. The step ends
    # as an abort does, bubblewrap's line and exit 1; no layer is needed to show the rig.
    abort = 'echo "bwrap: Can\'t find source path /x/.mcp.json" >&2; exit 1'
    with pytest.raises(AssertionError, match="bubblewrap aborted 1 step"):
        run_session(layout, [tool("Bash", command=abort, description="abort")], layer=False)
    shown = run_session(
        layout, [tool("Bash", command=abort, description="abort")], layer=False, aborts_fail=False
    )
    assert shown["aborted"] == [0]


@pytest.mark.usefixtures("layer")
def test_with_the_layer_no_residual_form_reads_the_held_out_stand_in(layout: Layout) -> None:
    run = run_session(layout, _residual(layout), layer=True)
    told = run["told"]
    assert isinstance(told, list) and len(told) == len(RESIDUAL_READS)
    reached = [name for name, said in zip(RESIDUAL_READS, told, strict=True) if MARKER in said]
    assert reached == []


def test_without_the_layer_the_residual_forms_read_it_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    run = run_session(layout, _residual(layout), layer=False)
    told = run["told"]
    assert isinstance(told, list)
    reached = {name for name, said in zip(RESIDUAL_READS, told, strict=True) if MARKER in said}
    missing = set(RESIDUAL_READS) - reached
    # sqlite3 may be absent from a machine; every other form must reach without the layer.
    assert missing <= {"sqlite3-import"}, missing


@pytest.mark.usefixtures("layer")
def test_with_the_layer_nothing_the_parser_cannot_see_reaches_a_protected_path(
    layout: Layout,
) -> None:
    run = run_session(layout, _steps(layout), layer=True)
    told = run["told"]
    assert isinstance(told, list)
    read, decisions, common, outside, worktree, temp = told
    assert MARKER not in read
    for refused in (read, decisions, common):
        assert "denied:" in refused and "wrote" not in refused, refused
    assert layout.decisions.read_text() == ""
    assert not (layout.common / "probe-marker").exists()
    # A path no root protects is writable where it lies in the machine's shared temporary
    # directories (as this test's own does on macOS), and denied anywhere else.
    shared = [Path(d).resolve() for d in shared_temp_dirs()]
    in_shared = any(layout.outside.resolve().is_relative_to(d) for d in shared)
    assert ("wrote" in outside) == in_shared, outside
    assert "wrote-worktree" in worktree and (layout.worktree / "made.txt").exists()
    uid = os.getuid()
    assert f"TMPDIR={layout.temp.resolve()}/claude-{uid}" in temp


@pytest.mark.usefixtures("layer")
def test_the_generated_sandbox_is_the_one_the_session_ran_with(layout: Layout) -> None:
    run = run_session(layout, [], layer=True)
    settings = run["settings"]
    assert isinstance(settings, dict)
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] and sandbox["failIfUnavailable"]
    assert sandbox["allowUnsandboxedCommands"] is False and sandbox["excludedCommands"] == []
    assert str(layout.common) in sandbox["filesystem"]["denyWrite"]
    assert str(layout.held) in sandbox["filesystem"]["denyRead"]


@pytest.mark.usefixtures("layer")
def test_without_the_layer_the_same_commands_reach_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    run = run_session(layout, _steps(layout), layer=False)
    told = run["told"]
    assert isinstance(told, list)
    # Each reached: the read printed the marker and each write went through. (The
    # sentinel puts the git directory back afterwards; the session was told it wrote.)
    assert MARKER in told[0]
    for reached in told[1:4]:
        assert "wrote" in reached and "denied:" not in reached, reached
    assert (layout.outside / "plain").exists()
    assert "sandbox" not in run["settings"]  # type: ignore[operator]


@pytest.mark.usefixtures("no_layer")
def test_a_session_told_the_layer_is_required_refuses_to_start_where_it_cannot_run(
    layout: Layout,
) -> None:
    run = run_session(layout, [tool("Bash", command="echo marker > made.txt")], layer=True)
    assert run["exit"] != 0
    assert not (layout.worktree / "made.txt").exists()
    result = run["result"]
    assert isinstance(result, dict)
    end = classify_session_end(result, exit_code=run["exit"], stopped_at_wall_clock=False)  # type: ignore[arg-type]
    assert end.cause == "sandbox_unavailable"


#: Writes into the worktree by spellings the hooks judge one way or the other, each joined at
#: run time; the OS layer must give every one the hooks' answer. ``True``: refused.
SPELLINGS = {
    "src/physgate/gate/x.py": True,  # a root that does not exist yet, its parent does
    "src/physgate/gatex/x.py": False,  # its sibling sharing a prefix
    ".physgate/lib/x.py": True,
    ".physgate/libx/x.py": False,
    ".physgate/lib/./y.py": True,
    ".physgate/series/r.json": False,  # the outbox: a script's write is how a record arrives
    "knowledge/stagingx/x.md": True,  # inside the knowledge tree, beside its staging
    "knowledge/staging/x.md": False,
    "corpora/x.json": True,
    "corpora-other/x.json": False,
}


def _spelling_steps(layout: Layout, *, case_variant: bool) -> list[dict[str, object]]:
    steps = []
    for spelling in SPELLINGS:
        written = spelling.upper() if case_variant else spelling
        # Each part written reversed and turned round at run time, so no protected name
        # appears in the program's text for the first layer to refuse it by.
        reversed_parts = [part[::-1] for part in written.split("/")]
        program = (
            "import os\n"
            f"p = os.path.join({str(layout.worktree)!r}, *(q[::-1] for q in {reversed_parts!r}))\n"
            "try:\n    os.makedirs(os.path.dirname(p), exist_ok=True)\n"
            "    open(p, 'w').write('marker'); print('wrote')\n"
            "except OSError as e:\n    print('denied:', e.strerror)\n"
        )
        steps.append(tool("Bash", command=python(program), description=spelling))
    return steps


@pytest.mark.usefixtures("layer")
def test_the_os_layer_judges_each_spelling_as_the_hooks_do(layout: Layout) -> None:
    for name in ("knowledge/staging", "knowledge/stagingx", "corpora", "src/physgate", ".physgate"):
        (layout.worktree / name).mkdir(parents=True, exist_ok=True)
    run_session(layout, _spelling_steps(layout, case_variant=False), layer=True)
    # Judged by what reached the disk, not by what the command was told: on Linux a write
    # into a directory no shell command may read lands in the empty layer bubblewrap lays
    # over it, and is gone when the command ends.
    got = {s: not (layout.worktree / s).exists() for s in SPELLINGS}
    assert got == SPELLINGS


@pytest.mark.usefixtures("layer")
def test_a_case_variant_of_a_root_is_refused_where_the_volume_ignores_case(
    layout: Layout,
) -> None:
    probe = layout.worktree / "Case-Probe"
    probe.write_text("")
    insensitive = (layout.worktree / "case-probe").exists()
    probe.unlink()
    if not insensitive:
        pytest.skip("this volume tells case apart, so a case variant is another path")
    for name in ("knowledge/staging", "knowledge/stagingx", "corpora", "src/physgate", ".physgate"):
        (layout.worktree / name).mkdir(parents=True, exist_ok=True)
    run_session(layout, _spelling_steps(layout, case_variant=True), layer=True)
    reached = {s for s in SPELLINGS if (layout.worktree / s.upper()).exists()}
    assert not reached & {s for s, r in SPELLINGS.items() if r}


@pytest.mark.usefixtures("layer")
def test_a_link_to_a_root_reaches_nothing(layout: Layout) -> None:
    (layout.worktree / ".physgate" / "lib").mkdir(parents=True)
    (layout.worktree / "via").symlink_to(layout.worktree / ".physgate" / "lib")
    program = (
        f"p = {str(layout.worktree)!r} + '/vi' + 'a/x.py'\n"
        "try:\n    open(p, 'w').write('marker'); print('wrote')\n"
        "except OSError as e:\n    print('denied:', e.strerror)\n"
    )
    run = run_session(
        layout, [tool("Bash", command=python(program), description="link")], layer=True
    )
    told = run["told"]
    assert isinstance(told, list) and "denied:" in str(told[0])
    assert not (layout.worktree / ".physgate" / "lib" / "x.py").exists()


@pytest.mark.usefixtures("layer")
def test_a_root_whose_parent_is_missing_never_keeps_a_command_from_making_that_parent(
    layout: Layout,
) -> None:
    # Measured on 2.1.301: a denied, absent path keeps a command from making its missing
    # parent, so such a root is the hooks' alone, and ordinary work can still make src/.
    step = tool("Bash", command="mkdir -p src/other && echo made", description="mkdir")
    run = run_session(layout, [step], layer=True)
    told = run["told"]
    assert isinstance(told, list) and "made" in str(told[0])


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("given", ["through-a-link", "real"])
def test_a_denial_bites_however_the_path_is_spelled(tmp_path: Path, given: str) -> None:
    # The session's places named through a link, or by their real path; each command reads
    # the held-out stand-in and writes the decisions file by the other spelling and by its own.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    base = link if given == "through-a-link" else real
    with make_layout(base) as made:
        spellings = {"link": link, "real": real}
        steps = []
        for name, prefix in spellings.items():
            held = str(prefix / "outside" / "heldout")
            decisions = str(prefix / "run" / "queue_decisions.jsonl")
            program = (
                f"h = {held[::-1]!r}[::-1] + '/stand.txt'\n"
                f"d = {decisions[::-1]!r}[::-1]\n"
                "for path, mode in ((h, 'r'), (d, 'a')):\n"
                "    try:\n"
                "        f = open(path, mode)\n"
                "        print('reached', f.read() if mode == 'r' else f.write('marker'))\n"
                "    except OSError as e:\n"
                "        print('denied:', e.strerror)\n"
            )
            steps.append(tool("Bash", command=python(program), description=name))
        run = run_session(made, steps, layer=True)
        told = run["told"]
        assert isinstance(told, list)
        for said in told:
            assert MARKER not in str(said) and "reached" not in str(said), said
        assert (real / "run" / "queue_decisions.jsonl").read_text() == ""
        # What the loop reads at a boundary: the denied append left it no decision to take.
        assert read_queue(real / "run").decisions == ()


#: A role's simulation script under its module: it writes one record through the run's copy
#: of the series writer, as the writer's own usage shows, with the marker in its title, under
#: the id it is given (``step_nominal`` by default), and says whether the writer refused it.
SIMULATION = f"""\
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer

record_id = sys.argv[1] if len(sys.argv) > 1 else "step_nominal"
try:
    series_writer.record(
        record_id,
        title={MARKER!r},
        axis="time",
        x=("time", "s", [0.0, 0.1, 0.2]),
        traces=[("position", "m", [0.0, 0.05, 0.1])],
    )
    print("recorded", record_id)
except series_writer.SeriesWriterError as exc:
    print("refused:", exc)
"""

#: The command a role session ran after a command naming the outbox was refused: it joins
#: the outbox's path at run time from the module directory, lists it and reads every record.
READ_BACK = """\
import os
p = os.path.join('..', '..', '.physgate', 'ser' + 'ies')
try:
    names = sorted(os.listdir(p))
    print('listed', names)
except OSError as e:
    print('denied:', e.strerror)
    names = ['step_nominal.json']
for name in names:
    try:
        print('read', open(os.path.join(p, name)).read())
    except OSError as e:
        print('denied:', e.strerror)
"""

#: The same, after moving the outbox out from under its name.
MOVE_AND_READ = """\
import os
p = os.path.join('..', '..', '.physgate', 'ser' + 'ies')
try:
    os.rename(p, 'moved')
    print('moved', open(os.path.join('moved', 'step_nominal.json')).read())
except OSError as e:
    print('denied:', e.strerror)
"""


def _module(layout: Layout) -> Path:
    """The module directory, holding the simulation script, with the writer at its place."""
    lib = layout.worktree / ".physgate" / "lib"
    lib.mkdir(parents=True)
    (lib / "series_writer.py").write_bytes(writer_source())
    module = layout.worktree / "modules" / "control"
    module.mkdir(parents=True)
    (module / "sim.py").write_text(SIMULATION)
    return module


def _series_steps(layout: Layout) -> list[dict[str, object]]:
    # By its full path each time: the shell's directory carries over from one command to the next.
    into = f"cd {_module(layout)} && "
    return [
        tool("Bash", command=into + "python3 sim.py", description="simulate"),
        tool("Bash", command=into + python(READ_BACK), description="read back"),
        tool("Bash", command=into + python(MOVE_AND_READ), description="move and read"),
    ]


@pytest.mark.usefixtures("layer")
def test_with_the_layer_the_writer_writes_a_record_once(layout: Layout) -> None:
    into = f"cd {_module(layout)} && "
    twice = tool("Bash", command=into + "python3 sim.py; python3 sim.py", description="twice")
    run = run_session(layout, [twice], layer=True)
    told = run["told"]
    assert isinstance(told, list)
    # Written, then refused under the same id in the same command: the first is the one on
    # the disk, whole, and nothing of the writer's is left beside the outbox.
    assert "recorded step_nominal" in str(told[0]), told
    assert "refused: the record 'step_nominal' is already in the outbox" in str(told[0]), told
    outbox = layout.worktree / ".physgate" / "series"
    assert sorted(p.name for p in outbox.iterdir()) == ["step_nominal.json"]
    assert json.loads((outbox / "step_nominal.json").read_text())["title"] == MARKER
    # Beside the outbox: the writer's place, and the proposals the installer made, empty.
    assert sorted(p.name for p in outbox.parent.iterdir()) == ["lib", "proposals", "series"]
    assert list((outbox.parent / "proposals").iterdir()) == []


@pytest.mark.usefixtures("layer")
def test_a_later_command_reads_no_record_from_the_outbox_by_a_path_built_at_run_time(
    layout: Layout,
) -> None:
    # The first layer refuses a command naming the outbox; this one joins its path at run
    # time, so only the OS layer can keep it from the records an earlier command wrote.
    run = run_session(layout, _series_steps(layout), layer=True)
    told = run["told"]
    assert isinstance(told, list)
    simulated, read_back, moved = (str(said) for said in told)
    assert "recorded" in simulated, simulated
    assert MARKER not in read_back and "denied:" in read_back, read_back
    if sys.platform == "darwin":
        # Seatbelt denies the directory whole, its listing included; on Linux a command
        # lists the names of the records earlier commands wrote, and reads none of them.
        assert "listed" not in read_back, read_back
    # Nor by moving the outbox, or a directory above it, out from under its name first.
    assert MARKER not in moved and "denied:" in moved, moved
    assert not (layout.worktree / "modules" / "control" / "moved").exists()
    record = layout.worktree / ".physgate" / "series" / "step_nominal.json"
    assert json.loads(record.read_text())["title"] == MARKER


@pytest.mark.usefixtures("layer")
def test_a_record_id_an_earlier_command_wrote_is_refused_never_rewritten(layout: Layout) -> None:
    # Run again in a later command, on either platform: the writer refuses the id and says
    # why, and the record the earlier command wrote stays as it was.
    first = _series_steps(layout)[0]
    run = run_session(layout, [first, first], layer=True)
    told = run["told"]
    assert isinstance(told, list)
    assert "recorded" in str(told[0]), told[0]
    assert "already in the outbox" in str(told[1]) and "under a new id" in str(told[1]), told[1]
    record = layout.worktree / ".physgate" / "series" / "step_nominal.json"
    assert json.loads(record.read_text())["title"] == MARKER


#: A file of the session's own, linked into the outbox under the name the simulation will
#: record, so that the record would be readable through the session's own name for it.
PLANT_BAIT = """\
import os
p = os.path.join('..', '..', '.physgate', 'ser' + 'ies')
os.makedirs(p, exist_ok=True)
open('bait.txt', 'w').write('BAIT')
try:
    os.link('bait.txt', os.path.join(p, 'step_nominal.json'))
    print('linked')
except OSError as e:
    print('link denied:', e.strerror)
"""


@pytest.mark.usefixtures("layer")
def test_a_record_is_never_written_through_a_name_the_session_linked_into_the_outbox(
    layout: Layout,
) -> None:
    # The writer used to fall back to writing a record in place when the outbox refused the
    # rename over it: through a hard link the session had planted, the session then read the
    # record by its own name and unlinked it, and the record sealed with one name again.
    into = f"cd {_module(layout)} && "
    steps = [
        tool("Bash", command=into + python(PLANT_BAIT), description="plant"),
        tool("Bash", command=into + "python3 sim.py", description="simulate"),
        tool(
            "Bash", command=into + python("print(open('ba' + 'it.txt').read())"), description="read"
        ),
    ]
    run = run_session(layout, steps, layer=True)
    told = run["told"]
    assert isinstance(told, list)
    planted, simulated, read = (str(said) for said in told)
    assert "linked" in planted, planted
    assert "refused:" in simulated and "already in the outbox" in simulated, simulated
    assert MARKER not in read and "BAIT" in read, read
    assert (layout.worktree / "modules" / "control" / "bait.txt").read_text() == "BAIT"


#: Started by one command and left running after it, in a session of its own: for fifteen
#: seconds it catches every file it can beside and in the outbox, by a link of its own, as
#: fast as it can (it holds no open file, so its catches are read by the next command).
WATCHER = """\
import os, time
d = os.path.join('..', '..', '.physgate')
p = os.path.join(d, 'ser' + 'ies')
end = time.time() + 15
n = 0
while time.time() < end:
    try:
        names = [os.path.join(d, x) for x in os.listdir(d)]
    except OSError:
        names = []
    names += [os.path.join(p, 'step_%d.json' % k) for k in range(5)]
    for name in names:
        if name.endswith(('.tmp', '.json')):
            try:
                os.link(name, 'caught%d' % n)
                n += 1
            except OSError:
                pass
"""

SPAWN_WATCHER = (
    "import subprocess, sys\n"
    f"subprocess.Popen([sys.executable, '-c', {WATCHER!r}], start_new_session=True,"
    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    "print('spawned')"
)

READ_CATCHES = """\
import glob
caught = sorted(glob.glob('cau' + 'ght*'))
print('caught', len(caught))
for name in caught:
    print(name, open(name).read()[:200])
"""


@pytest.mark.usefixtures("layer")
def test_a_process_left_running_catches_no_record_as_it_is_written(layout: Layout) -> None:
    # A process that outlived its command linked every temporary record the writer made
    # beside the outbox before it was renamed in. No such file is made now, and a record in
    # the outbox can be neither linked out nor opened by any process of the session.
    into = f"cd {_module(layout)} && "
    steps = [
        tool("Bash", command=into + python(SPAWN_WATCHER), description="watch"),
        tool(
            "Bash",
            command=into + "sleep 2; for k in 0 1 2 3 4; do python3 sim.py step_$k; done",
            description="simulate",
        ),
        tool("Bash", command=into + "sleep 1; " + python(READ_CATCHES), description="read"),
    ]
    run = run_session(layout, steps, layer=True)
    told = run["told"]
    assert isinstance(told, list)
    spawned, simulated, read = (str(said) for said in told)
    assert "spawned" in spawned, spawned
    assert all(f"recorded step_{k}" in simulated for k in range(5)), simulated
    assert MARKER not in read, read
    outbox = layout.worktree / ".physgate" / "series"
    assert sorted(p.name for p in outbox.iterdir()) == [f"step_{k}.json" for k in range(5)]


def test_without_the_layer_the_outbox_reads_back_which_shows_the_probe_works(
    layout: Layout,
) -> None:
    run = run_session(layout, _series_steps(layout)[:2], layer=False)
    told = run["told"]
    assert isinstance(told, list)
    simulated, read_back = (str(said) for said in told)
    assert "recorded" in simulated, simulated
    assert MARKER in read_back, read_back


#: Started by one command in a session of its own, so the shell's job control does not see
#: it: for twenty seconds it appends a line to a file in the worktree every tenth of a second.
LINGERER = """\
import time
end = time.time() + 20
with open('alive.log', 'a', buffering=1) as log:
    while time.time() < end:
        log.write('x\\n')
        time.sleep(0.1)
"""

SPAWN_LINGERER = (
    "import subprocess, sys\n"
    f"subprocess.Popen([sys.executable, '-c', {LINGERER!r}], start_new_session=True,"
    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    "import time; time.sleep(0.5)\n"
    "print('spawned')"
)

#: In a later command: whether the file is still growing.
STILL_GROWING = """\
import os, time
before = os.path.getsize('alive.log')
time.sleep(1.5)
print('growing' if os.path.getsize('alive.log') > before else 'still')
"""


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("reaper", [True, False], ids=["reaper", "red-control-without-it"])
def test_nothing_a_command_starts_outlives_it(layout: Layout, *, reaper: bool) -> None:
    # A process started in a session of its own got past the refusal of backgrounding and,
    # on macOS, lived on across later commands (M-128). Linux's process namespace ends it
    # with its command; on macOS the reaper, inside the command's own sandbox, stops it,
    # and the hook layer refuses the command that left it.
    if not reaper and sys.platform != "darwin":
        pytest.skip("the reaper exists on macOS only; Linux has no control to run")
    into = f"cd {layout.worktree} && "
    steps = [
        tool("Bash", command=into + python(SPAWN_LINGERER), description="spawn"),
        tool("Bash", command=into + python(STILL_GROWING), description="look"),
    ]
    run = run_session(layout, steps, layer=True, reaper=reaper)
    told = run["told"]
    assert isinstance(told, list)
    spawned, looked = (str(said) for said in told)
    assert "spawned" in spawned, spawned
    log_path = layout.sdir / "state" / "hooks.log.jsonl"
    lines = log_path.read_text().splitlines() if log_path.exists() else []
    caught = [
        json.loads(line)
        for line in lines
        if '"survivors"' in line and json.loads(line).get("hook") == "survivors"
    ]
    if not reaper:
        # Without the reaper the survivor is still writing in the next command, and the
        # hook, told by the configuration that the reaper is on, refuses each command that
        # gave no "done" line: a reaper that is missing is not taken for one that finished.
        assert "growing" in looked, looked
        assert [(c["event"], c["decision"]) for c in caught] == [("PostToolUse", "refuse")] * 2
        assert all("did not finish" in c["reason"] for c in caught)
        return
    assert "still" in looked, looked
    if sys.platform == "darwin":
        assert [(c["event"], c["decision"]) for c in caught] == [("PostToolUse", "refuse")]
        assert "left 1 process(es) running after it ended" in caught[0]["reason"]
    else:
        assert caught == []
    log = layout.worktree / "alive.log"
    size = log.stat().st_size
    time.sleep(1.0)
    assert log.stat().st_size == size
